"""시장 서브페이지 (site/v2/markets/{market}/index.html).

섹션:
1. 시장 요약 헤더 (market_snapshots)
2. 섹터 히트맵 (해당 시장의 모든 섹터)
3. Top 종목 표 (해당 시장 composite_score 상위)
4. 전략별 상위 미리보기 (pullback/breakout/box_breakout/reversal/trend_quality)
"""
from __future__ import annotations

from datetime import datetime
from html import escape

from market_scanner.reports.v2 import layout
from market_scanner.reports.v2.data import (
    STRATEGY_KEYS,
    MarketCard,
    MarketDetailData,
    SectorCell,
    TopStock,
)


def _summary_header(card: MarketCard | None) -> str:
    if card is None:
        return ('<section class="block"><h2>요약 없음</h2>'
                '<div class="sub">market_snapshots 데이터가 없습니다.</div></section>')

    breadth = card.bullish_breadth_pct
    if breadth is None:
        denom = card.advance_count + card.decline_count
        breadth = (card.advance_count / denom * 100.0) if denom else 0.0
    breadth = max(0.0, min(100.0, breadth))

    regime = card.regime or "—"
    risk = card.risk_level or "normal"
    chg_class = layout.change_class(card.avg_change_pct)

    return f"""
<section class="block">
  <h2>{escape(card.label)}</h2>
  <div class="sub">{escape(card.trade_date.strftime('%Y-%m-%d'))} · {escape(card.universe_key)} · {layout.fmt_int(card.total_count)}종목</div>
  <div class="card" style="max-width: 520px;">
    <div class="row"><span class="k">평균 등락률</span><span class="v {chg_class}">{layout.fmt_pct(card.avg_change_pct)}</span></div>
    <div class="row"><span class="k">상승 / 하락 / 보합</span><span class="v">
      <span class="up">{layout.fmt_int(card.advance_count)}</span> / <span class="down">{layout.fmt_int(card.decline_count)}</span> / <span class="flat">{layout.fmt_int(card.unchanged_count)}</span>
    </span></div>
    <div class="row"><span class="k">평균 RSI14</span><span class="v">{layout.fmt_num(card.avg_rsi14, 1)}</span></div>
    <div class="row"><span class="k">시장 점수</span><span class="v">{layout.fmt_num(card.market_score, 1)}</span></div>
    <div class="row"><span class="k">국면 / 리스크</span><span class="v">
      <span class="pill {layout.regime_pill(regime)}">{escape(regime)}</span>
      <span class="pill {layout.risk_pill(risk)}">{escape(risk)}</span>
    </span></div>
    <div class="breadth" title="상승 폭 {breadth:.1f}%"><span style="width: {breadth:.1f}%;"></span></div>
  </div>
</section>"""


def _sectors_section(sectors: list[SectorCell]) -> str:
    if not sectors:
        return ""
    sectors_sorted = sorted(sectors, key=lambda c: -(c.avg_change_pct or -999))
    tiles = []
    for c in sectors_sorted:
        chg_class = layout.change_class(c.avg_change_pct)
        tiles.append(f"""<div class="sector-tile">
  <div class="s" title="{escape(c.sector)}">{escape(c.sector)}</div>
  <div class="m">
    <span>{layout.fmt_int(c.instrument_count)}종목</span>
    <span class="{chg_class}">{layout.fmt_pct(c.avg_change_pct)}</span>
  </div>
</div>""")
    return f"""
<section class="block">
  <h2>섹터 히트맵</h2>
  <div class="sub">최신 거래일 기준, 섹터 평균 등락률 내림차순.</div>
  <div class="sector-heatmap">{''.join(tiles)}</div>
</section>"""


def _top_stocks_section(stocks: list[TopStock], title: str = "Top 종목") -> str:
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
  <h2>{escape(title)}</h2>
  <div class="sub">해당 시장 composite_score 상위 종목.</div>
  <div style="overflow-x:auto;">
  <table class="t">
    <thead>
      <tr>
        <th>#</th><th class="l">심볼</th><th class="l">종목명</th>
        <th class="l">섹터</th><th>종합점수</th><th>종가</th><th>등락률</th>
        <th>RSI14</th><th class="l">셋업</th>
      </tr>
    </thead>
    <tbody>{''.join(rows_html)}</tbody>
  </table>
  </div>
</section>"""


def _strategy_preview_section(strategy_top: dict[str, list[TopStock]]) -> str:
    """전략별 상위 미리보기. 비어 있는 전략은 그룹 자체 생략."""
    groups_html: list[str] = []
    for col, label in STRATEGY_KEYS:
        items = strategy_top.get(col) or []
        if not items:
            continue
        rows = []
        for i, s in enumerate(items, start=1):
            chg_class = layout.change_class(s.change_pct)
            name = s.name_local or s.symbol
            rows.append(f"""
<tr>
  <td>{i}</td>
  <td class="l">{escape(s.display_symbol)}</td>
  <td class="l">{escape(name)}</td>
  <td>{layout.fmt_num(s.composite_score, 1)}</td>
  <td class="{chg_class}">{layout.fmt_pct(s.change_pct)}</td>
</tr>""")
        groups_html.append(f"""
<div class="sector-group" style="min-width: 260px;">
  <div class="gname">{escape(label)}</div>
  <table class="t">
    <thead>
      <tr><th>#</th><th class="l">심볼</th><th class="l">종목명</th><th>점수</th><th>등락률</th></tr>
    </thead>
    <tbody>{''.join(rows)}</tbody>
  </table>
</div>""")

    if not groups_html:
        return ""
    return f"""
<section class="block">
  <h2>전략별 상위</h2>
  <div class="sub">각 전략 점수 상위 후보 (미리보기).</div>
  <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 16px;">
    {''.join(groups_html)}
  </div>
</section>"""


def render(data: MarketDetailData) -> str:
    sections = [
        _summary_header(data.summary),
        _sectors_section(data.sectors),
        _top_stocks_section(data.top_stocks),
        _strategy_preview_section(data.strategy_top),
    ]
    body = "".join(s for s in sections if s)
    generated_at = (
        datetime.combine(data.summary.trade_date, datetime.min.time())
        if data.summary else None
    )
    return layout.render_page(
        title=data.label,
        depth=2,
        body_html=body,
        nav_active=None,
        generated_at=generated_at,
    )
