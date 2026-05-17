"""US종합 / KR종합 개요 페이지 렌더링.

섹션:
1. 종합 시장 점수 히어로
2. 시장 카드
3. 섹터 히트맵
4. 섹터 리더십
5. 당일 Top 종목
6. 워치리스트 패널
"""
from __future__ import annotations

from datetime import datetime
from html import escape
from itertools import groupby

from market_scanner.reports.site import layout
from market_scanner.reports.site.data import (
    MarketCard,
    MacroPriceSeries,
    MacroQuote,
    OverviewPageData,
    SectorCell,
    TopStock,
    WatchlistStock,
)
from market_scanner.reports.site.pages.main_page import (
    _macro_chart_html,
    _quote_groups_for_chart,
    _series_sort_key,
)


def _sym_link(symbol: str, display: str) -> str:
    url = layout.quote_url(symbol)
    return f'<a href="{escape(url)}" target="_blank" rel="noopener">{escape(display)}</a>'


def _market_card_html(card: MarketCard) -> str:
    breadth = card.bullish_breadth_pct
    if breadth is None:
        denom = card.advance_count + card.decline_count
        breadth = (card.advance_count / denom * 100.0) if denom else 0.0
    breadth = max(0.0, min(100.0, breadth))

    regime = card.regime or "—"
    risk = card.risk_level or "normal"
    chg_class = layout.change_class(card.avg_change_pct)
    href = f"../../markets/{card.market_key}/index.html"
    return f"""
<a class="card card-link" href="{escape(href)}">
  <div class="name">{escape(card.label)}</div>
  <div class="meta">{escape(card.trade_date.strftime('%Y-%m-%d'))} · {escape(card.universe_key)} · {layout.fmt_int(card.total_count)}종목</div>
  <div class="row"><span class="k">평균 등락률</span><span class="v {chg_class}">{layout.fmt_pct(card.avg_change_pct)}</span></div>
  <div class="row"><span class="k">상승 / 하락</span><span class="v"><span class="up">{layout.fmt_int(card.advance_count)}</span> / <span class="down">{layout.fmt_int(card.decline_count)}</span></span></div>
  <div class="row"><span class="k">평균 RSI14</span><span class="v">{layout.fmt_num(card.avg_rsi14, 1)}</span></div>
  <div class="row"><span class="k">시장 점수</span><span class="v">{layout.fmt_num(card.market_score, 1)}</span></div>
  <div class="row"><span class="k">국면 / 리스크</span><span class="v">
    <span class="pill {layout.regime_pill(regime)}">{escape(regime)}</span>
    <span class="pill {layout.risk_pill(risk)}">{escape(risk)}</span>
  </span></div>
  <div class="breadth" title="상승 폭 {breadth:.1f}%"><span style="width: {breadth:.1f}%;"></span></div>
</a>"""


def _score_hero_section(cards: list[MarketCard]) -> str:
    if not cards:
        return ""
    total_advance = sum(c.advance_count for c in cards)
    total_decline = sum(c.decline_count for c in cards)
    scores = [c.market_score for c in cards if c.market_score is not None]
    avg_score = sum(scores) / len(scores) if scores else None
    rsies = [c.avg_rsi14 for c in cards if c.avg_rsi14 is not None]
    avg_rsi = sum(rsies) / len(rsies) if rsies else None
    breadths = [c.bullish_breadth_pct for c in cards if c.bullish_breadth_pct is not None]
    avg_breadth = sum(breadths) / len(breadths) if breadths else None
    chgs = [c.avg_change_pct for c in cards if c.avg_change_pct is not None]
    avg_chg = sum(chgs) / len(chgs) if chgs else None

    score_color = (
        "var(--up)" if (avg_score or 0) >= 55
        else "var(--down)" if (avg_score or 0) < 45
        else "var(--flat)"
    )
    pulse_items = [
        ("총 상승", f"{total_advance:,}", "up"),
        ("총 하락", f"{total_decline:,}", "down"),
        ("평균 등락률", layout.fmt_pct(avg_chg), layout.change_class(avg_chg)),
        ("평균 RSI14", layout.fmt_num(avg_rsi, 1), "flat"),
        ("상승 폭", f"{avg_breadth:.1f}%" if avg_breadth is not None else "—", "flat"),
    ]
    pulse_html = "\n".join(
        f'<div class="pulse-card"><div class="pc-label">{escape(lbl)}</div>'
        f'<div class="pc-value {cls}">{val}</div></div>'
        for lbl, val, cls in pulse_items
    )
    return f"""
<section class="block">
  <h2>종합 시장 점수</h2>
  <div class="score-hero">
    <div class="sh-score">
      <div class="sh-value" style="color:{score_color};">{layout.fmt_num(avg_score, 1)}</div>
      <div class="sh-label">시장 평균 점수</div>
    </div>
    <div class="pulse-grid">{pulse_html}</div>
  </div>
</section>"""


def _market_cards_section(cards: list[MarketCard]) -> str:
    if not cards:
        return ""
    body = "\n".join(_market_card_html(c) for c in cards)
    return f"""
<section class="block">
  <h2>시장 현황</h2>
  <div class="sub">활성 시장의 최신 거래일 요약. 카드 하단 바는 상승 폭 비율.</div>
  <div class="cards">{body}</div>
</section>"""


def _sector_etf_section(
    quotes: list[MacroQuote],
    series_list: list[MacroPriceSeries],
) -> str:
    if not quotes and not series_list:
        return ""
    sorted_quotes = sorted(
        quotes,
        key=lambda q: _series_sort_key(q.market_key, q.display_symbol),
    )
    quote_groups = _quote_groups_for_chart({"sector-etfs": sorted_quotes}) if sorted_quotes else {}
    chart_row = _macro_chart_html(series_list, quote_groups)
    return f"""
<section class="block">
  <h2>미국 섹터 ETF</h2>
  <div class="sub">미국 GICS 섹터 ETF의 기간별 상대 수익률과 최신 등락률.</div>
  {chart_row}
</section>"""


def _sector_heatmap_section(cells: list[SectorCell]) -> str:
    if not cells:
        return ""
    market_labels = {"us": "US", "kospi": "KOSPI", "kosdaq": "KOSDAQ"}
    groups_html: list[str] = []
    cells_sorted = sorted(cells, key=lambda c: (c.market_key, -(c.avg_change_pct or -999)))
    for market_key, items in groupby(cells_sorted, key=lambda c: c.market_key):
        items = list(items)
        tiles = []
        for c in items:
            chg_class = layout.change_class(c.avg_change_pct)
            tiles.append(f"""<div class="sector-tile">
  <div class="s" title="{escape(c.sector)}">{escape(c.sector)}</div>
  <div class="m">
    <span>{layout.fmt_int(c.instrument_count)}종목</span>
    <span class="{chg_class}">{layout.fmt_pct(c.avg_change_pct)}</span>
  </div>
</div>""")
        label = market_labels.get(market_key, market_key)
        groups_html.append(
            f'<div class="sector-group"><div class="gname">{escape(label)}</div>'
            f'<div class="sector-heatmap">{"".join(tiles)}</div></div>'
        )
    return f"""
<section class="block">
  <h2>섹터 히트맵</h2>
  <div class="sub">시장별 섹터 평균 등락률 (종목 수 상위).</div>
  {''.join(groups_html)}
</section>"""


def _sector_leadership_section(cells: list[SectorCell]) -> str:
    if not cells:
        return ""
    top = sorted(
        [c for c in cells if c.avg_composite_score is not None],
        key=lambda c: c.avg_composite_score or 0,
        reverse=True,
    )[:15]
    market_labels = {"us": "US", "kospi": "KOSPI", "kosdaq": "KOSDAQ"}
    rows_html: list[str] = []
    for i, c in enumerate(top, 1):
        chg_class = layout.change_class(c.avg_change_pct)
        mkt = market_labels.get(c.market_key, c.market_key.upper())
        rows_html.append(
            f"<tr>"
            f"<td>{i}</td>"
            f'<td class="l">{escape(mkt)}</td>'
            f'<td class="l">{escape(c.sector)}</td>'
            f"<td>{layout.fmt_int(c.instrument_count)}</td>"
            f'<td class="{chg_class}">{layout.fmt_pct(c.avg_change_pct)}</td>'
            f"<td>{layout.fmt_num(c.avg_composite_score, 1)}</td>"
            f"</tr>"
        )
    return f"""
<section class="block">
  <h2>섹터 리더십</h2>
  <div class="sub">종합 점수 기준 상위 섹터. 시장별 최신 거래일.</div>
  <div style="overflow-x:auto;">
  <table class="t">
    <thead><tr>
      <th>#</th><th class="l">시장</th><th class="l">섹터</th>
      <th>종목수</th><th>평균등락</th><th>평균점수</th>
    </tr></thead>
    <tbody>{"".join(rows_html)}</tbody>
  </table>
  </div>
</section>"""


def _top_stocks_section(stocks: list[TopStock]) -> str:
    if not stocks:
        return ""
    rows_html: list[str] = []
    for i, s in enumerate(stocks, start=1):
        chg_class = layout.change_class(s.change_pct)
        name = s.name_local or s.symbol
        setup = s.setup_label or ""
        rows_html.append(
            f"<tr>"
            f"<td>{i}</td>"
            f'<td class="l">{escape(s.market_label)}</td>'
            f'<td class="l">{_sym_link(s.symbol, s.display_symbol)}</td>'
            f'<td class="l">{escape(name)}</td>'
            f'<td class="l">{escape(s.sector or "")}</td>'
            f"<td>{layout.fmt_num(s.composite_score, 1)}</td>"
            f"<td>{layout.fmt_price(s.close_price)}</td>"
            f'<td class="{chg_class}">{layout.fmt_pct(s.change_pct)}</td>'
            f"<td>{layout.fmt_num(s.rsi14, 1)}</td>"
            f'<td class="l">{escape(setup)}</td>'
            f"</tr>"
        )
    return f"""
<section class="block">
  <h2>당일 Top 종목</h2>
  <div class="sub">전체 시장 통합 composite_score 상위. 시장별 최신 거래일 기준.</div>
  <div style="overflow-x:auto;">
  <table class="t">
    <thead>
      <tr>
        <th>#</th><th class="l">시장</th><th class="l">심볼</th><th class="l">종목명</th>
        <th class="l">섹터</th><th>종합점수</th><th>종가</th><th>등락률</th>
        <th>RSI14</th><th class="l">셋업</th>
      </tr>
    </thead>
    <tbody>{''.join(rows_html)}</tbody>
  </table>
  </div>
</section>"""


_WATCHLIST_META = [
    ("momentum",    "모멘텀",     "종합점수 상위"),
    ("pullback",    "MA눌림목",   "이평선 눌림 점수 상위"),
    ("oversold",    "과매도 반등","RSI<40 반전 점수 상위"),
    ("overbought",  "과열",       "RSI>65 과매수 구간"),
    ("turnaround",  "약세급등",   "금일 등락률 상위"),
    ("volume_surge","거래량급증", "거래량 비율 상위"),
]


def _watchlist_panels_section(stocks: list[WatchlistStock]) -> str:
    if not stocks:
        return ""
    by_panel: dict[str, list[WatchlistStock]] = {}
    for s in stocks:
        by_panel.setdefault(s.panel_key, []).append(s)

    panels_html: list[str] = []
    for key, label, desc in _WATCHLIST_META:
        items = by_panel.get(key, [])
        rows: list[str] = []
        for s in items:
            chg_class = layout.change_class(s.change_pct)
            name = (s.name_local or s.display_symbol)[:14]
            rows.append(
                f"<tr>"
                f'<td class="l">{_sym_link(s.symbol, s.display_symbol)}</td>'
                f'<td class="l" title="{escape(s.name_local or "")}">{escape(name)}</td>'
                f'<td class="{chg_class}">{layout.fmt_pct(s.change_pct)}</td>'
                f"<td>{layout.fmt_num(s.rsi, 1)}</td>"
                f"<td>{layout.fmt_num(s.composite_score, 1)}</td>"
                f"</tr>"
            )
        tbody = "".join(rows) if rows else (
            '<tr><td colspan="5" class="flat" style="text-align:center;padding:10px;">데이터 없음</td></tr>'
        )
        panels_html.append(f"""<div class="wl-panel">
  <div class="wl-head">
    <span class="wl-title">{escape(label)}</span>
    <span class="wl-desc">{escape(desc)}</span>
  </div>
  <table class="t">
    <thead><tr>
      <th class="l">심볼</th><th class="l">종목명</th>
      <th>등락률</th><th>RSI</th><th>점수</th>
    </tr></thead>
    <tbody>{tbody}</tbody>
  </table>
</div>""")

    return f"""
<section class="block">
  <h2>워치리스트</h2>
  <div class="sub">전략별 상위 종목.</div>
  <div class="watchlist-grid">{"".join(panels_html)}</div>
</section>"""


def render(data: OverviewPageData) -> str:
    body = "".join(
        section for section in (
            _score_hero_section(data.market_cards),
            _market_cards_section(data.market_cards),
            _sector_etf_section(data.sector_etf_quotes, data.sector_etf_price_series),
            _sector_heatmap_section(data.sector_cells),
            _sector_leadership_section(data.sector_cells),
            _top_stocks_section(data.top_stocks),
            _watchlist_panels_section(data.watchlist_stocks),
        ) if section
    )
    if not body:
        body = (
            '<section class="block"><h2>데이터 없음</h2>'
            '<div class="sub">market_snapshots / scan_results / sector_snapshots 가 비어 있습니다.</div></section>'
        )
    return layout.render_page(
        title=data.label,
        depth=2,
        body_html=body,
        nav_active=data.nav_key,
        generated_at=datetime.combine(data.generated_at, datetime.min.time()),
    )
