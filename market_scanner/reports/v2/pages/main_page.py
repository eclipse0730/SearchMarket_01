"""메인 페이지 (종합 시장 정보) 렌더링.

섹션:
1. 시장별 카드(market_snapshots)
2. 글로벌 매크로 패널(global-indices, commodities)
3. 당일 Top 종목 통합(scan_results)
4. 섹터 히트맵 요약(sector_snapshots)
"""
from __future__ import annotations

from datetime import datetime
from html import escape
from itertools import groupby

from market_scanner.reports.v2 import layout
from market_scanner.reports.v2.data import (
    MacroQuote,
    MainPageData,
    MarketCard,
    SectorCell,
    TopStock,
)


def _market_card_html(card: MarketCard) -> str:
    breadth = card.bullish_breadth_pct
    if breadth is None:
        # advance / (advance + decline) 로 fallback
        denom = card.advance_count + card.decline_count
        breadth = (card.advance_count / denom * 100.0) if denom else 0.0
    breadth = max(0.0, min(100.0, breadth))

    regime = card.regime or "—"
    risk = card.risk_level or "normal"
    chg_class = layout.change_class(card.avg_change_pct)

    href = f"markets/{card.market_key}/index.html"
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


def _macro_panel_section(quotes: list[MacroQuote]) -> str:
    if not quotes:
        return ""
    # 시장별로 그룹
    by_market: dict[str, list[MacroQuote]] = {}
    for q in quotes:
        by_market.setdefault(q.market_key, []).append(q)

    market_labels = {
        "global-indices": "글로벌 지수",
        "commodities": "원자재",
    }

    groups_html: list[str] = []
    for market_key, items in by_market.items():
        cells = "\n".join(
            f"""<div class="macro-cell">
  <div class="sym">{escape(q.display_symbol)}</div>
  <div class="name" title="{escape(q.name_local or q.symbol)}">{escape(q.name_local or q.symbol)}</div>
  <div class="px">{layout.fmt_price(q.close_price)}</div>
  <div class="chg {layout.change_class(q.change_pct)}">{layout.fmt_pct(q.change_pct)}</div>
</div>"""
            for q in items
        )
        label = market_labels.get(market_key, market_key)
        groups_html.append(
            f'<div class="sector-group"><div class="gname">{escape(label)}</div>'
            f'<div class="macro-grid">{cells}</div></div>'
        )

    return f"""
<section class="block">
  <h2>글로벌 매크로</h2>
  <div class="sub">주요 지수와 원자재 최신 종가. 전일 대비 등락률.</div>
  {''.join(groups_html)}
</section>"""


def _top_stocks_section(stocks: list[TopStock]) -> str:
    if not stocks:
        return ""
    rows_html: list[str] = []
    for i, s in enumerate(stocks, start=1):
        chg_class = layout.change_class(s.change_pct)
        name = s.name_local or s.symbol
        setup = s.setup_label or ""
        rows_html.append(f"""
<tr>
  <td>{i}</td>
  <td class="l">{escape(s.market_label)}</td>
  <td class="l">{escape(s.display_symbol)}</td>
  <td class="l">{escape(name)}</td>
  <td class="l">{escape(s.sector or '')}</td>
  <td>{layout.fmt_num(s.composite_score, 1)}</td>
  <td>{layout.fmt_price(s.close_price)}</td>
  <td class="{chg_class}">{layout.fmt_pct(s.change_pct)}</td>
  <td>{layout.fmt_num(s.rsi14, 1)}</td>
  <td class="l">{escape(setup)}</td>
</tr>""")
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


def _sector_heatmap_section(cells: list[SectorCell]) -> str:
    if not cells:
        return ""
    market_labels = {
        "us": "US",
        "kospi": "KOSPI",
        "kosdaq": "KOSDAQ",
    }
    # 시장별로 group, 등락률 내림차순
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


def render(data: MainPageData) -> str:
    body = "".join(
        section for section in (
            _market_cards_section(data.market_cards),
            _macro_panel_section(data.macro_quotes),
            _top_stocks_section(data.top_stocks),
            _sector_heatmap_section(data.sector_cells),
        ) if section
    )
    if not body:
        body = '<section class="block"><h2>데이터 없음</h2><div class="sub">market_snapshots / scan_results / sector_snapshots 가 비어 있습니다.</div></section>'
    return layout.render_page(
        title="메인",
        depth=0,
        body_html=body,
        nav_active="home",
        generated_at=datetime.combine(data.generated_at, datetime.min.time()),
    )
