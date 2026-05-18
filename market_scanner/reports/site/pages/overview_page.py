"""US종합 / KR종합 개요 페이지 렌더링.

섹션:
1. 종합 시장 점수 히어로
2. 섹터 히트맵
3. 섹터 리더십
4. 당일 Top 종목
5. 워치리스트 패널
"""
from __future__ import annotations

from datetime import datetime
from html import escape
from itertools import groupby

from market_scanner.reports.site import layout
from market_scanner.reports.site.data import (
    DailyMacroItem,
    MarketCard,
    MacroPriceSeries,
    MacroQuote,
    OverviewPageData,
    SectorCell,
    TopStock,
    WatchlistStock,
)
from market_scanner.reports.site.pages.main_page import (
    _MACRO_META,
    _fmt_macro_value,
    _macro_chart_html,
    _macro_interpretation_section,
    _macro_percentile,
    _pctile_text,
    _quote_groups_for_chart,
    _series_sort_key,
    _status_class,
)


def _sym_link(symbol: str, display: str) -> str:
    url = layout.quote_url(symbol)
    return f'<a href="{escape(url)}" target="_blank" rel="noopener">{escape(display)}</a>'


def _score_hero_section(cards: list[MarketCard]) -> str:
    if not cards:
        return ""

    if len(cards) > 1:
        panels = "".join(_score_panel_html(card) for card in sorted(cards, key=_market_order_key))
        return f"""
<section class="block">
  <h2>종합 시장 점수</h2>
  <div class="score-panel-grid">{panels}</div>
</section>"""

    card = cards[0]
    breadth = _breadth_pct(card)
    score_class = _score_state_class(card.market_score)
    breadth_class = _score_state_class(breadth)
    pulse_items = [
        ("총 상승", f"{card.advance_count:,}", "up"),
        ("총 하락", f"{card.decline_count:,}", "down"),
        ("평균 등락률", layout.fmt_pct(card.avg_change_pct), _change_state_class(card.avg_change_pct)),
        ("평균 RSI14", layout.fmt_num(card.avg_rsi14, 1), "score-neutral"),
        ("상승 종목 비율", f"{breadth:.1f}%" if breadth is not None else "—", breadth_class),
    ]
    pulse_html = _score_pulse_html(pulse_items)
    return f"""
<section class="block">
  <h2>종합 시장 점수</h2>
  <div class="score-hero">
    <div class="sh-score">
      <div class="sh-value {score_class}">{layout.fmt_num(card.market_score, 1)}</div>
      <div class="sh-label">시장 평균 점수</div>
    </div>
    <div class="pulse-grid">{pulse_html}</div>
  </div>
</section>"""


def _score_panel_html(card: MarketCard) -> str:
    breadth = _breadth_pct(card)
    score_class = _score_state_class(card.market_score)
    breadth_class = _score_state_class(breadth)
    pulse_items = [
        ("총 상승", f"{card.advance_count:,}", "up"),
        ("총 하락", f"{card.decline_count:,}", "down"),
        ("평균 등락률", layout.fmt_pct(card.avg_change_pct), _change_state_class(card.avg_change_pct)),
        ("평균 RSI14", layout.fmt_num(card.avg_rsi14, 1), "score-neutral"),
        ("상승 종목 비율", f"{breadth:.1f}%" if breadth is not None else "—", breadth_class),
    ]
    return f"""<div class="score-market-panel">
  <div class="score-panel-head">
    <div>
      <div class="score-market-name">{escape(card.label)}</div>
      <div class="score-market-meta">{escape(card.trade_date.strftime('%Y-%m-%d'))} · {layout.fmt_int(card.total_count)}종목</div>
    </div>
    <div class="sh-score">
      <div class="sh-value {score_class}">{layout.fmt_num(card.market_score, 1)}</div>
      <div class="sh-label">시장 점수</div>
    </div>
  </div>
  <div class="pulse-grid">{_score_pulse_html(pulse_items)}</div>
</div>"""


def _score_pulse_html(items: list[tuple[str, str, str]]) -> str:
    return "\n".join(
        f'<div class="pulse-card"><div class="pc-label">{escape(label)}</div>'
        f'<div class="pc-value {cls}">{value}</div></div>'
        for label, value, cls in items
    )


def _breadth_pct(card: MarketCard) -> float | None:
    if card.bullish_breadth_pct is not None:
        return max(0.0, min(100.0, card.bullish_breadth_pct))
    denom = card.advance_count + card.decline_count
    if not denom:
        return None
    return max(0.0, min(100.0, card.advance_count / denom * 100.0))


def _score_state_class(value: float | None) -> str:
    if value is None:
        return "score-neutral"
    if value >= 55:
        return "up"
    if value <= 45:
        return "down"
    return "score-neutral"


def _change_state_class(value: float | None) -> str:
    if value is None:
        return "score-neutral"
    if value > 0:
        return "up"
    if value < 0:
        return "down"
    return "score-neutral"


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

    groups: list[tuple[str, list[SectorCell]]] = []
    cells_sorted = sorted(cells, key=lambda c: (c.market_key, -(c.avg_change_pct or -999)))
    for market_key, items in groupby(cells_sorted, key=lambda c: c.market_key):
        groups.append((market_key, list(items)))
    groups.sort(key=lambda item: _market_order_key(item[0]))

    if len(groups) > 1:
        panels = []
        for market_key, items in groups:
            tiles = _sector_theme_groups_html(items)
            label = market_labels.get(market_key, market_key)
            panels.append(f"""<div class="sector-compare-panel">
  <div class="gname">{escape(label)}</div>
  {tiles}
</div>""")
        return f"""
<section class="block">
  <h2>섹터 히트맵</h2>
  <div class="sub">KOSPI와 KOSDAQ 전체 섹터를 투자 테마별로 묶어 비교합니다.</div>
  <div class="sector-compare-grid">{"".join(panels)}</div>
</section>"""

    groups_html: list[str] = []
    for market_key, items in groups:
        tiles = _sector_theme_groups_html(items)
        label = market_labels.get(market_key, market_key)
        groups_html.append(
            f'<div class="sector-group"><div class="gname">{escape(label)}</div>'
            f'{tiles}</div>'
        )
    return f"""
<section class="block">
  <h2>섹터 히트맵</h2>
  <div class="sub">시장별 섹터 평균 등락률 (종목 수 상위).</div>
  {''.join(groups_html)}
</section>"""


_SECTOR_THEME_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("반도체", ("반도체",)),
    ("2차전지·전기장비", ("이차전지", "배터리", "전기제품", "전기장비", "화학·배터리")),
    ("바이오·헬스케어", (
        "제약", "바이오", "생물공학", "생명과학", "건강관리", "헬스케어", "의료기기", "의약품", "혈액",
    )),
    ("조선·방산·우주항공", ("조선", "방산", "우주항공", "항공우주")),
    ("자동차", ("자동차", "타이어")),
    ("IT·인터넷·게임", (
        "IT서비스", "소프트웨어", "인터넷", "플랫폼", "양방향미디어", "게임", "컴퓨터", "기술",
    )),
    ("전자·디스플레이·통신장비", (
        "전자장비", "전자제품", "전자부품", "전자·가전", "사무용전자제품", "핸드셋", "디스플레이", "통신장비",
    )),
    ("미디어·엔터·광고", ("방송", "엔터테인먼트", "광고", "출판", "커뮤니케이션 서비스")),
    ("금융·증권·보험", ("금융", "은행", "증권", "보험", "창업투자", "벤처투자")),
    ("소비재·유통·레저", (
        "식품", "음료", "화장품", "섬유", "의류", "신발", "호화품", "가정", "가구", "전문소매",
        "백화점", "유통", "호텔", "레저", "교육", "판매업체", "다각화된소비자", "인터넷과카탈로그소매",
        "문구", "담배",
    )),
    ("산업재·기계·건설", ("기계", "로봇", "산업재", "건설", "건축", "상업서비스", "복합기업", "복합")),
    ("소재·화학·철강", ("화학", "철강", "비철금속", "원자재", "포장재", "종이", "목재", "소재")),
    ("에너지·유틸리티", ("에너지", "석유", "가스", "정유", "유틸리티")),
    ("운송·물류", ("운송", "해운", "항공사", "항공화물", "도로", "철도", "운송인프라")),
    ("통신서비스", ("통신", "무선통신", "다각화된통신서비스")),
    ("부동산·기타", ("부동산", "Unknown")),
]


def _sector_theme_groups_html(cells: list[SectorCell]) -> str:
    grouped: dict[str, list[SectorCell]] = {}
    for cell in cells:
        grouped.setdefault(_sector_theme(cell.sector), []).append(cell)

    theme_groups: list[tuple[str, list[SectorCell]]] = []
    for theme, _ in _SECTOR_THEME_RULES:
        items = grouped.pop(theme, [])
        if not items:
            continue
        theme_groups.append((theme, items))
    for theme in sorted(grouped):
        theme_groups.append((theme, grouped[theme]))
    theme_groups.sort(key=lambda group: -_sector_theme_sort_value(group[1]))
    blocks = [_sector_theme_block_html(theme, items) for theme, items in theme_groups]
    return f'<div class="sector-theme-summary-grid">{"".join(blocks)}</div>'


def _sector_theme_sort_value(cells: list[SectorCell]) -> float:
    avg_change = _weighted_avg_change(cells)
    return avg_change if avg_change is not None else -999.0


def _sector_theme_block_html(theme: str, cells: list[SectorCell]) -> str:
    cells_sorted = sorted(cells, key=lambda c: -(c.avg_change_pct or -999))
    instrument_count = sum(cell.instrument_count for cell in cells_sorted)
    avg_change = _weighted_avg_change(cells_sorted)
    chg_class = layout.change_class(avg_change)
    leader = cells_sorted[0]
    laggard = cells_sorted[-1]
    return f"""<div class="sector-theme-card" style="{_sector_tile_style(avg_change)}">
  <div class="sector-theme-card-head">
    <div class="sector-theme-title">{escape(theme)}</div>
    <div class="sector-theme-change {chg_class}">{layout.fmt_pct(avg_change)}</div>
  </div>
  <div class="sector-theme-meta">{len(cells_sorted)}섹터 · {layout.fmt_int(instrument_count)}종목</div>
  <div class="sector-theme-pair">
    <span>강세</span><b>{escape(leader.sector)}</b><em class="{layout.change_class(leader.avg_change_pct)}">{layout.fmt_pct(leader.avg_change_pct)}</em>
  </div>
  <div class="sector-theme-pair">
    <span>약세</span><b>{escape(laggard.sector)}</b><em class="{layout.change_class(laggard.avg_change_pct)}">{layout.fmt_pct(laggard.avg_change_pct)}</em>
  </div>
</div>"""


def _weighted_avg_change(cells: list[SectorCell]) -> float | None:
    weighted_sum = 0.0
    total_weight = 0
    for cell in cells:
        if cell.avg_change_pct is None:
            continue
        weight = max(cell.instrument_count, 1)
        weighted_sum += cell.avg_change_pct * weight
        total_weight += weight
    if not total_weight:
        return None
    return weighted_sum / total_weight


def _sector_theme(sector: str) -> str:
    for theme, keywords in _SECTOR_THEME_RULES:
        if any(keyword in sector for keyword in keywords):
            return theme
    return "부동산·기타"


def _sector_tile_style(change_pct: float | None) -> str:
    value = max(-6.0, min(6.0, change_pct or 0.0))
    if value > 0:
        alpha = 0.22 + abs(value) / 6 * 0.68
        return f"background: rgba(40, 209, 124, {alpha:.3f});"
    if value < 0:
        alpha = 0.22 + abs(value) / 6 * 0.68
        return f"background: rgba(244, 91, 105, {alpha:.3f});"
    return "background: rgba(216, 169, 74, .34);"


def _market_order_key(item: MarketCard | str) -> tuple[int, str]:
    key = item.universe_key if isinstance(item, MarketCard) else item
    order = {
        "kospi": 0,
        "kosdaq": 1,
        "us": 0,
    }
    return (order.get(key, 100), key)


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
  <div class="table-scroll">
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
  <div class="table-scroll">
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
            '<tr><td colspan="5" class="flat empty-cell">데이터 없음</td></tr>'
        )
        panels_html.append(f"""<div class="wl-panel">
  <div class="wl-head">
    <span class="wl-title">{escape(label)}</span>
    <span class="wl-desc">{escape(desc)}</span>
  </div>
  <div class="table-scroll wl-table-scroll">
  <table class="t">
    <thead><tr>
      <th class="l">심볼</th><th class="l">종목명</th>
      <th>등락률</th><th>RSI</th><th>점수</th>
    </tr></thead>
    <tbody>{tbody}</tbody>
  </table>
  </div>
</div>""")

    return f"""
<section class="block">
  <h2>워치리스트</h2>
  <div class="sub">전략별 상위 종목.</div>
  <div class="watchlist-grid">{"".join(panels_html)}</div>
</section>"""


_KR_MACRO_GROUPS: list[tuple[str, list[str]]] = [
    ("환율 압력", ["USDKRW", "DXY"]),
    ("국내 금리", ["KR_10Y", "KR_INTERBANK_3M", "KR_CALL_RATE", "KR_DISCOUNT_RATE"]),
    ("증시자금", ["KR_CUSTOMER_DEPOSIT_VALUE", "KR_CREDIT_BALANCE_VALUE"]),
    ("국내 수급", ["KR_KOSPI_FOREIGN_NET_BUY_VALUE", "KR_KOSPI_INSTITUTION_NET_BUY_VALUE", "KR_KOSDAQ_FOREIGN_NET_BUY_VALUE", "KR_KOSDAQ_INSTITUTION_NET_BUY_VALUE"]),
    ("공매도", ["KR_KOSPI_SHORT_SELL_VALUE", "KR_KOSPI_SHORT_BALANCE_VALUE", "KR_KOSDAQ_SHORT_SELL_VALUE", "KR_KOSDAQ_SHORT_BALANCE_VALUE"]),
    ("글로벌 부담", ["US_10Y", "VIX"]),
    ("원자재", ["WTI", "GOLD"]),
]


def _kr_macro_environment_section(
    items: list[DailyMacroItem],
    history: dict[str, list[float]],
) -> str:
    by_code = {item.indicator_code: item for item in items}
    summary_html = _kr_macro_overview_chips(by_code, history)
    groups_html: list[str] = []

    for group_label, codes in _KR_MACRO_GROUPS:
        cells: list[str] = []
        for code in codes:
            item = by_code.get(code)
            if item is None:
                continue
            meta = _MACRO_META.get(code)
            display_name = meta[0] if meta else code
            chg_class = layout.change_class(item.change_pct)
            val_str = _fmt_macro_value(item)
            chg_str = layout.fmt_pct(item.change_pct) if item.change_pct is not None else "—"
            percentile = _macro_percentile(item, history)
            status, note = _kr_macro_signal(code, item, percentile)
            cells.append(f"""<div class="macro-cell">
  <div class="macro-card-head">
    <div class="sym">{escape(code)}</div>
    <span class="macro-status status-{_status_class(status)}">{escape(status)}</span>
  </div>
  <div class="name" title="{escape(display_name)}">{escape(display_name)}</div>
  <div class="macro-value-row">
    <span class="metric-value">{escape(val_str)}</span>
    <span class="chg {chg_class}">{escape(chg_str)}</span>
  </div>
  <div class="macro-context">{escape(_pctile_text(percentile))}</div>
  <div class="macro-note">{escape(note)}</div>
</div>""")
        if cells:
            groups_html.append(
                f'<div class="sector-group">'
                f'<div class="gname">{escape(group_label)}</div>'
                f'<div class="macro-grid">{"".join(cells)}</div>'
                f'</div>'
            )

    if not groups_html:
        return ""
    return f"""
<section class="block">
  <h2>KR 매크로 환경</h2>
  <div class="sub">환율·국내금리·글로벌금리·위험심리·원자재를 한국 시장 관점으로 해석합니다.</div>
  {summary_html}
  <div class="kr-macro-group-grid">{''.join(groups_html)}</div>
</section>"""


def _kr_macro_overview_chips(
    by_code: dict[str, DailyMacroItem],
    history: dict[str, list[float]],
) -> str:
    specs = [
        ("환율 압력", ["USDKRW", "DXY"]),
        ("국내 금리", ["KR_10Y", "KR_INTERBANK_3M", "KR_CALL_RATE"]),
        ("글로벌 금리", ["US_10Y"]),
        ("위험 심리", ["VIX"]),
        ("원자재 부담", ["WTI"]),
    ]
    chips: list[str] = []
    for label, codes in specs:
        item = next((by_code[code] for code in codes if code in by_code), None)
        if item is None:
            continue
        percentile = _macro_percentile(item, history)
        status, note = _kr_macro_signal(item.indicator_code, item, percentile)
        chips.append(f"""<div class="macro-chip status-{_status_class(status)}">
  <div class="chip-label">{escape(label)}</div>
  <div class="chip-main">{escape(status)}</div>
  <div class="chip-note">{escape(note)}</div>
</div>""")
    if not chips:
        return ""
    return f'<div class="macro-summary">{"".join(chips)}</div>'


def _kr_macro_signal(
    code: str,
    item: DailyMacroItem,
    percentile: int | None,
) -> tuple[str, str]:
    value = item.value

    if code == "USDKRW":
        if value >= 1450:
            return "위험", "원화 약세 압력이 큰 구간입니다."
        if value >= 1400:
            return "주의", "환율 부담이 한국 증시에 부담입니다."
        if value <= 1300:
            return "안정", "원화 약세 부담은 제한적입니다."
        return "중립", "환율 흐름을 확인해야 합니다."

    if code == "DXY":
        if value >= 105:
            return "위험", "강달러가 외국인 수급에 부담입니다."
        if value >= 102:
            return "주의", "달러 강세 압력을 점검해야 합니다."
        return "중립", "달러 압력은 중립권입니다."

    if code in {"KR_10Y", "KR_INTERBANK_3M", "KR_CALL_RATE", "KR_DISCOUNT_RATE"}:
        if value >= 4:
            return "위험", "국내 금리 부담이 높은 구간입니다."
        if value >= 3.25:
            return "주의", "국내 금리 부담을 확인해야 합니다."
        if percentile is not None and percentile >= 80:
            return "주의", "최근 1년 기준 높은 금리 구간입니다."
        return "안정", "국내 금리 부담은 비교적 제한적입니다."

    if code == "US_10Y":
        if value >= 4.5:
            return "위험", "미국 장기금리 부담이 큰 구간입니다."
        if value >= 4:
            return "주의", "미국 금리 상승 부담을 확인해야 합니다."
        return "안정", "미국 금리 부담은 비교적 제한적입니다."

    if code == "VIX":
        if value >= 30:
            return "위험", "글로벌 위험회피가 강한 구간입니다."
        if value >= 20:
            return "주의", "변동성 확대를 주의해야 합니다."
        return "안정", "글로벌 변동성은 안정권입니다."

    if code == "WTI":
        if value >= 100:
            return "위험", "유가 부담이 큰 구간입니다."
        if value >= 90:
            return "주의", "유가 상승이 비용 부담으로 이어질 수 있습니다."
        return "중립", "유가 부담은 제한적입니다."

    if code == "GOLD":
        if percentile is not None and percentile >= 80:
            return "주의", "안전자산 선호가 강한 구간입니다."
        return "중립", "안전자산 선호를 확인하는 보조 지표입니다."

    if percentile is not None:
        if percentile >= 80:
            return "주의", "최근 1년 기준 높은 구간입니다."
        if percentile <= 20:
            return "주의", "최근 1년 기준 낮은 구간입니다."
    return "중립", "추세 확인이 필요한 보조 지표입니다."


def _overview_macro_section(data: OverviewPageData) -> str:
    if data.nav_key == "us-all":
        return _macro_interpretation_section(data.daily_macro_items, data.macro_history, "미국 매크로 해석")
    if data.nav_key == "kr-all":
        return _kr_macro_environment_section(data.daily_macro_items, data.macro_history)
    return ""


def render(data: OverviewPageData) -> str:
    sector_leadership = "" if data.nav_key == "kr-all" else _sector_leadership_section(data.sector_cells)
    body = "".join(
        section for section in (
            _score_hero_section(data.market_cards),
            _overview_macro_section(data),
            _sector_etf_section(data.sector_etf_quotes, data.sector_etf_price_series),
            _sector_heatmap_section(data.sector_cells),
            sector_leadership,
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
        main_class="main-wide",
    )
