"""메인 페이지 렌더링.

매크로 지표(금리·환율·변동성·크립토)와 글로벌 지수·원자재 틱커를 표시한다.
시장/종목 섹션은 overview_page 로 분리됐다.
"""
from __future__ import annotations

from datetime import datetime
from html import escape

from market_scanner.reports.site import layout
from market_scanner.reports.site.data import DailyMacroItem, MacroQuote, MainPageData


# indicator_code → (표시명, 소수점 자리수, 단위 suffix)
_MACRO_META: dict[str, tuple[str, int, str]] = {
    # 금리
    "SOFR":               ("SOFR",          2, "%"),
    "US_FFR":             ("Fed Fund Rate",  2, "%"),
    "US_2Y":              ("미국 2년금리",   2, "%"),
    "US_10Y":             ("미국 10년금리",  2, "%"),
    "US_30Y":             ("미국 30년금리",  2, "%"),
    "US_SPREAD_2S10S":    ("2s10s 스프레드", 2, "%"),
    "US_SPREAD_3M10Y":    ("3M10Y 스프레드", 2, "%"),
    # 신용 스프레드
    "HY_OAS":             ("HY OAS",        2, "bp"),
    "IG_OAS":             ("IG OAS",        2, "bp"),
    # 유동성
    "FED_RRP":            ("Fed RRP",       0, "B$"),
    "FED_BS":             ("Fed B/S",       0, "M$"),
    # 환율
    "USDKRW":             ("USD/KRW",       2, ""),
    "USDKRW_FRED":        ("USD/KRW (FRED)",2, ""),
    "EURUSD":             ("EUR/USD",       4, ""),
    "USDJPY":             ("USD/JPY",       2, ""),
    "USDCNY":             ("USD/CNY",       4, ""),
    "DXY":                ("달러인덱스",    2, ""),
    # 변동성·심리
    "VIX":                ("VIX",           2, ""),
    "VVIX":               ("VVIX",          2, ""),
    # 크립토
    "BTC_USD":            ("BTC",           0, "$"),
    "ETH_USD":            ("ETH",           0, "$"),
    "CRYPTO_TOTAL_MCAP":  ("크립토 총 시총",0, "$"),
    "CRYPTO_FNG":         ("공포·탐욕",     0, ""),
}

# 표시 그룹 순서
_GROUPS: list[tuple[str, list[str]]] = [
    ("금리", ["SOFR", "US_FFR", "US_2Y", "US_10Y", "US_30Y"]),
    ("스프레드", ["US_SPREAD_2S10S", "US_SPREAD_3M10Y", "HY_OAS", "IG_OAS"]),
    ("유동성", ["FED_RRP", "FED_BS"]),
    ("환율", ["USDKRW", "EURUSD", "USDJPY", "USDCNY", "DXY"]),
    ("변동성·심리", ["VIX", "VVIX"]),
    ("크립토", ["BTC_USD", "ETH_USD", "CRYPTO_TOTAL_MCAP", "CRYPTO_FNG"]),
]


def _fmt_macro_value(item: DailyMacroItem) -> str:
    meta = _MACRO_META.get(item.indicator_code)
    if meta is None:
        return f"{item.value:,.2f}"
    _, decimals, suffix = meta
    val_str = f"{item.value:,.{decimals}f}"
    return f"{val_str} {suffix}".strip() if suffix else val_str


def _daily_macro_section(items: list[DailyMacroItem]) -> str:
    if not items:
        return ""
    by_code = {it.indicator_code: it for it in items}

    groups_html: list[str] = []
    for group_label, codes in _GROUPS:
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
            cells.append(f"""<div class="macro-cell">
  <div class="sym">{escape(code)}</div>
  <div class="name" title="{escape(display_name)}">{escape(display_name)}</div>
  <div class="px">{escape(val_str)}</div>
  <div class="chg {chg_class}">{escape(chg_str)}</div>
</div>""")
        if not cells:
            continue
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
  <h2>매크로 지표</h2>
  <div class="sub">금리·환율·변동성·크립토 등 최신 거래일 값. 전일 대비 등락률.</div>
  {''.join(groups_html)}
</section>"""


def _macro_panel_section(quotes: list[MacroQuote]) -> str:
    if not quotes:
        return ""
    by_market: dict[str, list[MacroQuote]] = {}
    for q in quotes:
        by_market.setdefault(q.market_key, []).append(q)

    market_labels = {
        "global-indices": "글로벌 지수",
        "sector-etfs": "섹터 ETF",
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
  <h2>글로벌 지수 · 원자재</h2>
  <div class="sub">주요 지수와 원자재 최신 종가. 전일 대비 등락률.</div>
  {''.join(groups_html)}
</section>"""


def render(data: MainPageData) -> str:
    body = "".join(
        section for section in (
            _daily_macro_section(data.daily_macro_items),
            _macro_panel_section(data.macro_quotes),
        ) if section
    )
    if not body:
        body = (
            '<section class="block"><h2>데이터 없음</h2>'
            '<div class="sub">daily_macro / daily_prices 가 비어 있습니다. '
            '<code>Search.py macro</code> 와 <code>Search.py price global-indices</code> 를 먼저 실행하세요.</div></section>'
        )
    return layout.render_page(
        title="메인",
        depth=0,
        body_html=body,
        nav_active="home",
        generated_at=datetime.combine(data.generated_at, datetime.min.time()),
    )
