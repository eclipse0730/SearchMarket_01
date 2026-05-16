"""섹터 서브페이지 (site/markets/{market}/sectors/{sector}/index.html).

섹션:
1. 섹터 요약 헤더 (sector_snapshots)
2. Top 종목 표 (composite_score 상위)
3. 전략별 상위 (pullback/breakout/box_breakout/reversal/trend_quality)
"""
from __future__ import annotations

from datetime import datetime
from html import escape

from market_scanner.reports.site import layout
from market_scanner.reports.site.data import (
    STRATEGY_KEYS,
    SectorDetailData,
    TopStock,
)


def _summary_header(data: SectorDetailData) -> str:
    date_str = data.trade_date.strftime("%Y-%m-%d") if data.trade_date else "—"
    chg_class = layout.change_class(data.avg_change_pct)
    return f"""
<section class="block">
  <div class="sub" style="margin-bottom:8px;">
    <a href="../../index.html">← {escape(data.market_label)}</a>
  </div>
  <h2>{escape(data.sector)}</h2>
  <div class="card summary-card">
    <div class="row"><span class="k">기준일</span><span class="v">{escape(date_str)}</span></div>
    <div class="row"><span class="k">종목수</span><span class="v">{layout.fmt_int(data.instrument_count)}</span></div>
    <div class="row"><span class="k">평균 등락률</span><span class="v {chg_class}">{layout.fmt_pct(data.avg_change_pct)}</span></div>
    <div class="row"><span class="k">평균 종합점수</span><span class="v">{layout.fmt_num(data.avg_composite_score, 1)}</span></div>
  </div>
</section>"""


def _sym_link(symbol: str, display: str) -> str:
    url = layout.quote_url(symbol)
    return f'<a href="{escape(url)}" target="_blank" rel="noopener">{escape(display)}</a>'


def _top_stocks_section(stocks: list[TopStock]) -> str:
    if not stocks:
        return ""
    rows_html: list[str] = []
    for i, s in enumerate(stocks, 1):
        chg_class = layout.change_class(s.change_pct)
        name = s.name_local or s.symbol
        rows_html.append(
            f"<tr>"
            f"<td>{i}</td>"
            f'<td class="l">{_sym_link(s.symbol, s.display_symbol)}</td>'
            f'<td class="l">{escape(name)}</td>'
            f"<td>{layout.fmt_num(s.composite_score, 1)}</td>"
            f"<td>{layout.fmt_price(s.close_price)}</td>"
            f'<td class="{chg_class}">{layout.fmt_pct(s.change_pct)}</td>'
            f"<td>{layout.fmt_num(s.rsi14, 1)}</td>"
            f'<td class="l">{escape(s.setup_label or "")}</td>'
            f"</tr>"
        )
    return f"""
<section class="block">
  <h2>Top 종목</h2>
  <div class="sub">종합점수 상위 종목.</div>
  <div style="overflow-x:auto;">
  <table class="t">
    <thead><tr>
      <th>#</th><th class="l">심볼</th><th class="l">종목명</th>
      <th>종합점수</th><th>종가</th><th>등락률</th><th>RSI14</th><th class="l">셋업</th>
    </tr></thead>
    <tbody>{"".join(rows_html)}</tbody>
  </table>
  </div>
</section>"""


def _strategy_preview_section(strategy_top: dict[str, list[TopStock]]) -> str:
    groups_html: list[str] = []
    for col, label in STRATEGY_KEYS:
        items = strategy_top.get(col) or []
        if not items:
            continue
        rows: list[str] = []
        for i, s in enumerate(items, 1):
            chg_class = layout.change_class(s.change_pct)
            name = s.name_local or s.symbol
            rows.append(
                f"<tr>"
                f"<td>{i}</td>"
                f'<td class="l">{_sym_link(s.symbol, s.display_symbol)}</td>'
                f'<td class="l">{escape(name)}</td>'
                f"<td>{layout.fmt_num(s.composite_score, 1)}</td>"
                f'<td class="{chg_class}">{layout.fmt_pct(s.change_pct)}</td>'
                f"</tr>"
            )
        groups_html.append(
            f'<div class="sector-group">'
            f'<div class="gname">{escape(label)}</div>'
            f'<table class="t"><thead><tr>'
            f'<th>#</th><th class="l">심볼</th><th class="l">종목명</th><th>점수</th><th>등락률</th>'
            f'</tr></thead><tbody>{"".join(rows)}</tbody></table>'
            f"</div>"
        )
    if not groups_html:
        return ""
    return f"""
<section class="block">
  <h2>전략별 상위</h2>
  <div class="sub">각 전략 점수 상위 후보.</div>
  <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:16px;">
    {"".join(groups_html)}
  </div>
</section>"""


def render(data: SectorDetailData) -> str:
    body = "".join(
        s for s in (
            _summary_header(data),
            _top_stocks_section(data.top_stocks),
            _strategy_preview_section(data.strategy_top),
        )
        if s
    )
    if not body:
        body = '<section class="block"><h2>데이터 없음</h2></section>'
    generated_at = (
        datetime.combine(data.trade_date, datetime.min.time())
        if data.trade_date else None
    )
    return layout.render_page(
        title=f"{data.sector} · {data.market_label}",
        depth=4,
        body_html=body,
        nav_active=None,
        generated_at=generated_at,
    )
