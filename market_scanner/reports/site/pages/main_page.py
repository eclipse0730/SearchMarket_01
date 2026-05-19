"""메인 페이지 렌더링.

매크로 지표 해석과 글로벌 지수·원자재 틱커를 표시한다.
시장/종목 섹션은 overview_page 로 분리됐다.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from html import escape
from typing import Any

from market_scanner.reports.site import layout
from market_scanner.reports.site.data import DailyMacroItem, MacroPriceSeries, MacroQuote, MainPageData


# display_symbol → 범례/툴팁 표시명
_SERIES_NAMES: dict[str, str] = {
    # 섹터 ETF
    "XLRE": "리츠",       "VNQ":  "리츠(VNQ)",
    "XLB":  "소재",       "XLE":  "에너지",
    "XLF":  "금융",       "XLK":  "기술",
    "XLV":  "헬스케어",   "XLY":  "경기소비재",
    "XLP":  "필수소비재", "XLI":  "산업재",
    "XLU":  "유틸리티",   "XLC":  "통신",
    # 글로벌 지수
    "DJI":      "다우",       "GSPC":     "S&P500",
    "IXIC":     "나스닥",     "NDX":      "나스닥100",
    "RUT":      "러셀2000",   "VIX":      "VIX",
    "FTSE":     "영국",       "GDAXI":    "독일DAX",
    "FCHI":     "프랑스",     "STOXX50E": "유럽50",
    "N225":     "닛케이",     "KS11":     "코스피",
    "KQ11":     "코스닥",     "HSI":      "항셍",
    "SSE":      "상해",       "CSI300":   "CSI300",
    "TWII":     "대만",       "BSESN":    "인도BSE",
    "NSEI":     "인도50",     "AXJO":     "호주",
    "BVSP":     "브라질",     "STI":      "싱가포르",
    # 원자재
    "GC":  "금",    "SI":  "은",    "PL":  "백금",  "PA":  "팔라듐",
    "CL":  "WTI",  "BZ":  "브렌트","NG":  "천연가스","HG":  "구리",
    "ALI": "알루미늄","ZC": "옥수수","ZS":  "대두",  "ZW":  "밀",
    "KC":  "커피",  "SB":  "설탕",
    "RB":  "가솔린", "HO":  "난방유", "CC":  "코코아", "CT":  "면화",
    "OJ":  "오렌지주스", "LE": "생우", "GF": "비육우", "HE": "돈육",
    "LBS": "목재", "ZO": "귀리", "ZR": "쌀", "ZL": "대두유", "ZM": "대두박",
    "GSPTSE": "캐나다", "MXX": "멕시코", "JKSE": "인도네시아",
    "KLSE": "말레이시아", "SET.BK": "태국",
    "IBEX": "스페인", "FTSEMIB.MI": "이탈리아", "AEX": "네덜란드",
    "SSMI": "스위스", "BFX": "벨기에", "ATX": "오스트리아",
    "OMXSPI": "스웨덴", "NZ50": "뉴질랜드",
    "DXY": "달러인덱스", "KRW": "원화", "EUR": "유로", "JPY": "엔", "CNH": "위안",
    "GBP": "파운드", "AUD": "호주달러", "NZD": "뉴질랜드달러",
    "CAD": "캐나다달러", "CHF": "스위스프랑", "SGD": "싱가포르달러",
    "SEK": "스웨덴크로나", "NOK": "노르웨이크로네", "MXN": "멕시코페소",
}

# display_symbol → CSS border-color (차트 라인 색상)
_SERIES_COLORS: dict[str, str] = {
    # 글로벌 지수 — 미국 파랑, 유럽 초록, 아시아 노랑/오렌지/빨강
    "DJI":      "#4f9dde",
    "GSPC":     "#62c7ff",
    "IXIC":     "#00bfff",
    "NDX":      "#1fa8f0",
    "RUT":      "#87ceeb",
    "VIX":      "#ff69b4",
    "FTSE":     "#32cd32",
    "GDAXI":    "#00e676",
    "FCHI":     "#66bb6a",
    "STOXX50E": "#26a69a",
    "N225":     "#ffd740",
    "KS11":     "#ff8f00",
    "KQ11":     "#ffab40",
    "HSI":      "#ef5350",
    "SSE":      "#e53935",
    "CSI300":   "#ff7043",
    "TWII":     "#ab47bc",
    "BSESN":    "#ec407a",
    "NSEI":     "#ba68c8",
    "AXJO":     "#26c6da",
    "BVSP":     "#a1887f",
    "STI":      "#78909c",
    # 원자재 — 귀금속 금/은, 에너지 빨강, 농산물 초록/갈색
    "GC":       "#ffd700",
    "SI":       "#c0c0c0",
    "PL":       "#e0dcc8",
    "PA":       "#a4b8c4",
    "CL":       "#c62828",
    "BZ":       "#b71c1c",
    "NG":       "#ff6d00",
    "HG":       "#b87333",
    "ALI":      "#90a4ae",
    "ZC":       "#c8e6c9",
    "ZS":       "#8bc34a",
    "ZW":       "#f4a460",
    "KC":       "#8d6e63",
    "SB":       "#ffe0b2",
    "RB":       "#d84315",
    "HO":       "#ff8a65",
    "CC":       "#6d4c41",
    "CT":       "#f8bbd0",
    "OJ":       "#ffb74d",
    "LE":       "#a1887f",
    "GF":       "#8d6e63",
    "HE":       "#bcaaa4",
    "LBS":      "#7cb342",
    "ZO":       "#dce775",
    "ZR":       "#fff59d",
    "ZL":       "#c5e1a5",
    "ZM":       "#9ccc65",
    "GSPTSE":   "#42a5f5",
    "MXX":      "#26a69a",
    "JKSE":     "#ef5350",
    "KLSE":     "#7e57c2",
    "SET.BK":   "#ffca28",
    "IBEX":     "#f06292",
    "FTSEMIB.MI": "#00bcd4",
    "AEX":      "#29b6f6",
    "SSMI":     "#ef5350",
    "BFX":      "#8bc34a",
    "ATX":      "#ff7043",
    "OMXSPI":   "#5c6bc0",
    "NZ50":     "#26a69a",
    "DXY":      "#d7b56d",
    "KRW":      "#ff0000",
    "EUR":      "#32cd32",
    "JPY":      "#ff8f00",
    "CNH":      "#ef5350",
    "GBP":      "#ba68c8",
    "AUD":      "#26c6da",
    "NZD":      "#66bb6a",
    "CAD":      "#42a5f5",
    "CHF":      "#db5c5a",
    "SGD":      "#78909c",
    "SEK":      "#5c6bc0",
    "NOK":      "#00bcd4",
    "MXN":      "#26a69a",
    # 섹터 ETF — 사용자 요청 색상 참고
    "XLK":      "#1986df",  # 기술 — 파랑
    "XLC":      "#2adaf1",  # 통신 — 청록
    "XLE":      "#b6b6b6",  # 에너지 — 진빨강
    "XLV":      "#32cd32",  # 헬스케어 — 초록
    "XLF":      "#ffd740",  # 금융 — 금색
    "XLB":      "#ff8f00",  # 소재 — 주황
    "XLY":      "#ff6d00",  # 경기소비재 — 주황
    "XLP":      "#66bb6a",  # 필수소비재 — 연초록
    "XLI":      "#87ceeb",  # 산업재 — 하늘색
    "XLU":      "#9370db",  # 유틸리티 — 보라
    "XLRE":     "#ef5350",  # 리츠 — 빨강
    "VNQ":      "#e53935",  # 리츠 보조 — 진빨강
}


_MARKET_ORDER = ["global-indices", "commodities"]

_SERIES_PRIORITY: dict[str, list[str]] = {
    "global-indices": [
        "GSPC", "NDX", "IXIC", "DJI", "RUT", "VIX",
        "KS11", "KQ11", "N225", "HSI", "SSE", "CSI300", "TWII",
        "BSESN", "NSEI", "FTSE", "GDAXI", "FCHI", "STOXX50E",
        "IBEX", "FTSEMIB.MI", "AEX", "SSMI", "GSPTSE", "AXJO",
        "BVSP", "MXX", "STI", "JKSE", "KLSE", "SET.BK",
        "BFX", "ATX", "OMXSPI", "NZ50",
    ],
    "commodities": [
        "GC", "CL", "BZ", "NG", "HG", "SI", "PL", "PA", "ALI",
        "ZC", "ZS", "ZW", "KC", "SB", "RB", "HO", "CT", "CC",
        "OJ", "LE", "GF", "HE", "LBS", "ZO", "ZR", "ZL", "ZM",
    ],
    "sector-etfs": [
        "XLK", "XLF", "XLE", "XLV", "XLY", "XLI",
        "XLP", "XLU", "XLC", "XLB", "XLRE", "VNQ",
    ],
    "fx-strength": [
        "DXY", "KRW", "EUR", "JPY", "CNH", "GBP", "AUD",
        "CAD", "CHF", "NZD", "SGD", "SEK", "NOK", "MXN",
    ],
}

_SERIES_PRIORITY_INDEX: dict[str, dict[str, int]] = {
    market_key: {symbol: index for index, symbol in enumerate(symbols)}
    for market_key, symbols in _SERIES_PRIORITY.items()
}

_GLOBAL_INDEX_GROUPS: list[tuple[str, set[str]]] = [
    ("핵심", {"GSPC", "NDX", "IXIC", "DJI", "RUT", "VIX"}),
    ("아시아", {
        "KS11", "KQ11", "N225", "HSI", "SSE", "CSI300", "TWII",
        "BSESN", "NSEI", "STI", "JKSE", "KLSE", "SET.BK",
    }),
    ("유럽", {
        "FTSE", "GDAXI", "FCHI", "STOXX50E", "IBEX", "FTSEMIB.MI",
        "AEX", "SSMI", "BFX", "ATX", "OMXSPI",
    }),
    ("기타", {"GSPTSE", "AXJO", "BVSP", "MXX", "NZ50"}),
]

_GLOBAL_INDEX_VIEW_EXCLUDE = {
    "BFX",
    "ATX",
    "OMXSPI",
    "NZ50",
    "KLSE",
    "SET.BK",
    "JKSE",
}

_COMMODITY_VIEW_EXCLUDE = {
    "OJ",
    "ZO",
    "ZR",
    "ZL",
    "ZM",
    "GF",
    "HE",
}

_FX_STRENGTH_VIEW_EXCLUDE = {
    "NZD",
    "SGD",
    "SEK",
    "NOK",
}


def _series_sort_key(market_key: str, display_symbol: str) -> tuple[int, str]:
    priority = _SERIES_PRIORITY_INDEX.get(market_key, {})
    return (priority.get(display_symbol, 10_000), display_symbol)


def _is_macro_view_visible(market_key: str, display_symbol: str) -> bool:
    if market_key == "global-indices":
        return display_symbol not in _GLOBAL_INDEX_VIEW_EXCLUDE
    if market_key == "commodities":
        return display_symbol not in _COMMODITY_VIEW_EXCLUDE
    if market_key == "fx-strength":
        return display_symbol not in _FX_STRENGTH_VIEW_EXCLUDE
    return True


# indicator_code → (표시명, 소수점 자리수, 단위 suffix)
_MACRO_META: dict[str, tuple[str, int, str]] = {
    # 금리
    "SP500":              ("S&P500",        2, ""),
    "NASDAQ100":          ("Nasdaq100",     2, ""),
    "KOSPI":              ("KOSPI",         2, ""),
    "KOSDAQ":             ("KOSDAQ",        2, ""),
    "SOFR":               ("SOFR",          2, "%"),
    "US_FFR":             ("Fed Fund Rate",  2, "%"),
    "US_2Y":              ("미국 2년금리",   2, "%"),
    "US_10Y":             ("미국 10년금리",  2, "%"),
    "US_30Y":             ("미국 30년금리",  2, "%"),
    "US_SPREAD_2S10S":    ("2s10s 스프레드", 2, "%"),
    "US_SPREAD_3M10Y":    ("3M10Y 스프레드", 2, "%"),
    "KR_10Y":             ("한국 장기국채",  2, "%"),
    "KR_INTERBANK_3M":    ("은행간 3개월",   2, "%"),
    "KR_CALL_RATE":       ("콜금리",         2, "%"),
    "KR_DISCOUNT_RATE":   ("한국 할인율",    2, "%"),
    "KR_KOSPI_FOREIGN_NET_BUY_VALUE":      ("KOSPI 외국인", 0, "원"),
    "KR_KOSPI_INSTITUTION_NET_BUY_VALUE":  ("KOSPI 기관",   0, "원"),
    "KR_KOSDAQ_FOREIGN_NET_BUY_VALUE":     ("KOSDAQ 외국인",0, "원"),
    "KR_KOSDAQ_INSTITUTION_NET_BUY_VALUE": ("KOSDAQ 기관",  0, "원"),
    "KR_KOSPI_SHORT_SELL_VALUE":           ("KOSPI 공매도", 0, "원"),
    "KR_KOSPI_SHORT_BALANCE_VALUE":        ("KOSPI 공매도잔고", 0, "원"),
    "KR_KOSDAQ_SHORT_SELL_VALUE":          ("KOSDAQ 공매도",0, "원"),
    "KR_KOSDAQ_SHORT_BALANCE_VALUE":       ("KOSDAQ 공매도잔고", 0, "원"),
    "KR_CUSTOMER_DEPOSIT_VALUE":           ("고객예탁금", 0, "백만원"),
    "KR_CREDIT_BALANCE_VALUE":             ("신용융자",   0, "백만원"),
    # 신용 스프레드
    "HY_OAS":             ("HY OAS",        2, "%"),
    "IG_OAS":             ("IG OAS",        2, "%"),
    # 유동성
    "FED_RRP":            ("Fed RRP",       0, "B$"),
    "FED_BS":             ("Fed B/S",       0, "M$"),
    # 환율
    "USDKRW":             ("USD/KRW",       2, ""),
    "USDKRW_FRED":        ("USD/KRW (FRED)",2, ""),
    "EURUSD":             ("EUR/USD",       4, ""),
    "USDJPY":             ("USD/JPY",       2, ""),
    "USDCNY":             ("USD/CNY",       4, ""),
    "GBPUSD":             ("GBP/USD",       4, ""),
    "AUDUSD":             ("AUD/USD",       4, ""),
    "NZDUSD":             ("NZD/USD",       4, ""),
    "USDCAD":             ("USD/CAD",       4, ""),
    "USDCHF":             ("USD/CHF",       4, ""),
    "USDSGD":             ("USD/SGD",       4, ""),
    "USDSEK":             ("USD/SEK",       4, ""),
    "USDNOK":             ("USD/NOK",       4, ""),
    "USDMXN":             ("USD/MXN",       4, ""),
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
    ("경기·신용 신호", ["US_SPREAD_2S10S", "US_SPREAD_3M10Y", "HY_OAS", "IG_OAS"]),
    ("유동성", ["FED_RRP", "FED_BS"]),
    ("변동성·심리", ["VIX", "VVIX", "CRYPTO_FNG"]),
]

_TOP_INDICATORS: list[dict[str, Any]] = [
    {"kind": "quote", "codes": ("GSPC", "^GSPC"), "macro_code": "SP500", "label": "S&P500", "group": "US 주식", "decimals": 2},
    {"kind": "quote", "codes": ("NDX", "^NDX"), "macro_code": "NASDAQ100", "label": "Nasdaq100", "group": "US 주식", "decimals": 2},
    {"kind": "quote", "codes": ("KS11", "^KS11"), "macro_code": "KOSPI", "label": "KOSPI", "group": "KR 주식", "decimals": 2},
    {"kind": "quote", "codes": ("KQ11", "^KQ11"), "macro_code": "KOSDAQ", "label": "KOSDAQ", "group": "KR 주식", "decimals": 2},
    {"kind": "quote", "codes": ("VIX", "^VIX"), "macro_code": "VIX", "label": "VIX", "group": "리스크", "decimals": 2},
    {"kind": "macro", "code": "US_10Y", "label": "미국10년물", "group": "금리", "decimals": 2, "suffix": "%"},
    {"kind": "macro", "code": "DXY", "label": "DXY", "group": "달러", "decimals": 2},
    {"kind": "macro", "code": "USDKRW", "label": "USDKRW", "group": "환율", "decimals": 2},
    {"kind": "macro", "code": "WTI", "label": "WTI", "group": "원자재", "decimals": 2, "prefix": "$"},
    {"kind": "macro", "code": "GOLD", "label": "Gold", "group": "원자재", "decimals": 2, "prefix": "$"},
    {"kind": "macro", "code": "BTC_USD", "label": "BTC", "group": "크립토", "decimals": 0, "prefix": "$"},
    {"kind": "macro", "code": "ETH_USD", "label": "ETH", "group": "크립토", "decimals": 0, "prefix": "$"},
]


def _fmt_macro_value(item: DailyMacroItem) -> str:
    meta = _MACRO_META.get(item.indicator_code)
    if meta is None:
        return f"{item.value:,.2f}"
    _, decimals, suffix = meta
    val_str = f"{item.value:,.{decimals}f}"
    return f"{val_str} {suffix}".strip() if suffix else val_str


def _macro_percentile(item: DailyMacroItem, history: dict[str, list[float]]) -> int | None:
    values = history.get(item.indicator_code, [])
    if len(values) < 20:
        return None
    below_or_equal = sum(1 for value in values if value <= item.value)
    return round((below_or_equal / len(values)) * 100)


def _pctile_text(percentile: int | None) -> str:
    return f"1년 위치 {percentile}%" if percentile is not None else "1년 위치 —"


def _macro_signal(code: str, item: DailyMacroItem, percentile: int | None) -> tuple[str, str]:
    value = item.value
    change_pct = item.change_pct

    if code in {"SOFR", "US_FFR"}:
        if value >= 5:
            return "위험", "단기금리가 높은 구간입니다."
        if value >= 4:
            return "주의", "높은 단기금리가 위험자산에 부담입니다."
        return "안정", "단기금리 부담이 완화된 구간입니다."

    if code in {"US_2Y", "US_10Y", "US_30Y"}:
        if value >= 4.5:
            return "위험", "국채금리 부담이 큰 구간입니다."
        if value >= 4:
            return "주의", "금리 상승 부담을 확인해야 합니다."
        return "안정", "금리 부담은 비교적 제한적입니다."

    if code in {"US_SPREAD_2S10S", "US_SPREAD_3M10Y"}:
        if value < 0:
            return "위험", "역전 상태로 경기 둔화 신호입니다."
        if value < 0.5:
            return "주의", "장단기 스프레드가 낮은 편입니다."
        return "안정", "수익률곡선은 정상 구간입니다."

    if code == "HY_OAS":
        if value >= 5:
            return "위험", "하이일드 신용위험이 확대된 구간입니다."
        if value >= 4:
            return "주의", "신용 스프레드 확대를 주의해야 합니다."
        return "안정", "하이일드 신용위험은 안정권입니다."

    if code == "IG_OAS":
        if value >= 2:
            return "위험", "투자등급 신용위험이 높아졌습니다."
        if value >= 1.5:
            return "주의", "투자등급 스프레드 확대를 확인해야 합니다."
        return "안정", "투자등급 신용위험은 안정권입니다."

    if code == "FED_RRP":
        if change_pct is not None and change_pct < -5:
            return "주의", "역레포 잔액 감소 속도가 빠릅니다."
        return "중립", "단기 유동성 완충 정도를 보는 지표입니다."

    if code == "FED_BS":
        if change_pct is not None and change_pct < 0:
            return "주의", "연준 자산 축소 흐름입니다."
        if change_pct is not None and change_pct > 0:
            return "중립", "연준 자산이 증가했습니다."
        return "중립", "연준 자산 규모 변화는 제한적입니다."

    if code == "VIX":
        if value >= 30:
            return "위험", "주식시장 변동성 스트레스 구간입니다."
        if value >= 20:
            return "주의", "변동성 확대를 주의해야 합니다."
        return "안정", "주식시장 변동성은 안정권입니다."

    if code == "VVIX":
        if value >= 110:
            return "위험", "VIX 자체의 변동성도 높습니다."
        if value >= 85:
            return "주의", "변동성 급등 위험을 점검해야 합니다."
        return "안정", "변동성 급등 위험은 제한적입니다."

    if code == "CRYPTO_FNG":
        if value <= 25:
            return "주의", "크립토 심리가 공포 구간입니다."
        if value >= 75:
            return "주의", "크립토 심리가 과열 구간입니다."
        return "중립", "크립토 심리는 중립권입니다."

    if percentile is not None:
        if percentile >= 80:
            return "주의", "최근 1년 기준 높은 구간입니다."
        if percentile <= 20:
            return "주의", "최근 1년 기준 낮은 구간입니다."
    return "중립", "추세 확인이 필요한 보조 지표입니다."


def _status_class(status: str) -> str:
    return {
        "안정": "ok",
        "중립": "neutral",
        "주의": "warn",
        "위험": "risk",
    }.get(status, "neutral")


def _macro_overview_chips(by_code: dict[str, DailyMacroItem], history: dict[str, list[float]]) -> str:
    specs = [
        ("금리 압력", "US_10Y"),
        ("장단기 경기신호", "US_SPREAD_2S10S"),
        ("신용위험", "HY_OAS"),
        ("유동성", "FED_RRP"),
        ("변동성", "VIX"),
    ]
    chips: list[str] = []
    for label, code in specs:
        item = by_code.get(code)
        if item is None:
            continue
        percentile = _macro_percentile(item, history)
        status, note = _macro_signal(code, item, percentile)
        chips.append(f"""<div class="macro-chip status-{_status_class(status)}">
  <div class="chip-label">{escape(label)}</div>
  <div class="chip-main">{escape(status)}</div>
  <div class="chip-note">{escape(note)}</div>
</div>""")
    if not chips:
        return ""
    return f'<div class="macro-summary">{"".join(chips)}</div>'


def _fmt_top_value(value: float | None, decimals: int, prefix: str = "", suffix: str = "") -> str:
    if value is None:
        return "—"
    return f"{prefix}{value:,.{decimals}f}{suffix}"


def _quote_display_name(quote: MacroQuote) -> str:
    return _SERIES_NAMES.get(quote.display_symbol) or quote.name_local or quote.symbol


def _asof_text(trade_date, collected_at=None) -> str:
    date_text = trade_date.strftime("%Y-%m-%d") if trade_date else "—"
    if collected_at:
        return f"{date_text} · 갱신 {collected_at.strftime('%m-%d %H:%M')}"
    return date_text


def _top_indicator_rows(
    quotes: list[MacroQuote],
    daily_items: list[DailyMacroItem],
) -> list[dict[str, str]]:
    quote_by_code: dict[str, MacroQuote] = {}
    for quote in quotes:
        quote_by_code[quote.symbol] = quote
        quote_by_code[quote.display_symbol] = quote
    macro_by_code = {item.indicator_code: item for item in daily_items}

    rows: list[dict[str, str]] = []
    for spec in _TOP_INDICATORS:
        value: float | None = None
        change_pct: float | None = None
        trade_date = None
        collected_at = None

        if spec["kind"] == "quote":
            quote = next((quote_by_code.get(code) for code in spec["codes"] if quote_by_code.get(code)), None)
            if quote:
                value = quote.close_price
                change_pct = quote.change_pct
                trade_date = quote.trade_date
                collected_at = quote.collected_at
            elif spec.get("macro_code"):
                item = macro_by_code.get(spec["macro_code"])
                if item:
                    value = item.value
                    change_pct = item.change_pct
                    trade_date = item.trade_date
                    collected_at = item.collected_at
        else:
            item = macro_by_code.get(spec["code"])
            if item:
                value = item.value
                change_pct = item.change_pct
                trade_date = item.trade_date
                collected_at = item.collected_at

        rows.append({
            "label": spec["label"],
            "group": spec["group"],
            "value": _fmt_top_value(
                value,
                int(spec.get("decimals", 2)),
                str(spec.get("prefix", "")),
                str(spec.get("suffix", "")),
            ),
            "change": layout.fmt_pct(change_pct) if change_pct is not None else "—",
            "change_class": layout.change_class(change_pct),
            "asof": _asof_text(trade_date, collected_at),
        })
    return rows


def _top_indicators_section(
    quotes: list[MacroQuote],
    daily_items: list[DailyMacroItem],
) -> str:
    rows = _top_indicator_rows(quotes, daily_items)
    if not rows or all(row["value"] == "—" for row in rows):
        return ""
    cards = "\n".join(
        f"""<div class="top-indicator-card">
  <div class="tic-head">
    <span class="tic-label">{escape(row["label"])}</span>
    <span class="tic-group">{escape(row["group"])}</span>
  </div>
  <div class="tic-main">
    <span class="tic-value">{escape(row["value"])}</span>
    <span class="tic-change {escape(row["change_class"])}">{escape(row["change"])}</span>
  </div>
  <div class="tic-asof">{escape(row["asof"])}</div>
</div>"""
        for row in rows
    )
    return f"""
<section class="market-pulse">
  <div class="pulse-head">
    <div>
      <div class="eyebrow">MAIN INDICATORS</div>
      <h1>시장 핵심 지표</h1>
    </div>
    <div class="pulse-note">미국10년물은 수익률(%) 기준입니다. 자산별 거래 시간이 달라 각 카드에 기준일과 수집 시각을 함께 표시합니다.</div>
  </div>
  <div class="top-indicator-grid">{cards}</div>
</section>"""


def _macro_interpretation_section(
    items: list[DailyMacroItem],
    history: dict[str, list[float]],
    title: str = "매크로 해석",
) -> str:
    if not items:
        return ""
    by_code = {it.indicator_code: it for it in items}
    summary_html = _macro_overview_chips(by_code, history)

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
            percentile = _macro_percentile(item, history)
            status, note = _macro_signal(code, item, percentile)
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
  <h2>{escape(title)}</h2>
  <div class="sub">금리·경기신호·신용위험·유동성·변동성을 최근 1년 위치와 함께 해석합니다.</div>
  {summary_html}
  {''.join(groups_html)}
</section>"""


def _macro_chart_html(
    series_list: list[MacroPriceSeries],
    quote_groups_by_market: dict[str, list[dict[str, Any]]] | None = None,
    chart_id: str = "macro",
) -> str:
    """글로벌 지수 · 원자재 · 섹터 ETF 시계열 Chart.js 라인 차트."""
    if not series_list:
        return ""

    _TAB_LABELS = {
        "global-indices": "글로벌 지수",
        "commodities": "원자재",
        "sector-etfs": "섹터 ETF",
        "fx-strength": "통화 강약",
    }
    _TAB_ORDER = ["global-indices", "commodities", "sector-etfs", "fx-strength"]

    by_market: dict[str, list[MacroPriceSeries]] = defaultdict(list)
    for s in series_list:
        by_market[s.market_key].append(s)

    groups_data: dict[str, dict] = {}
    for market_key, group in by_market.items():
        all_dates = sorted({d for s in group for d in s.dates})
        datasets = []
        sorted_group = sorted(group, key=lambda s: _series_sort_key(market_key, s.display_symbol))
        for s in sorted_group:
            date_to_val = dict(zip(s.dates, s.values))
            color = _SERIES_COLORS.get(s.display_symbol, "#62c7ff")
            name = _SERIES_NAMES.get(s.display_symbol, s.display_symbol)
            datasets.append({
                "label": name,
                "displaySymbol": s.display_symbol,
                "rawData": [date_to_val.get(d) for d in all_dates],  # raw close — JS가 정규화
                "borderColor": color,
                "backgroundColor": color + "1a",
                "pointRadius": 0,
                "borderWidth": 1.5,
                "tension": 0.2,
                "spanGaps": True,
            })
        groups_data[market_key] = {"dates": all_dates, "datasets": datasets}

    tab_order = [k for k in _TAB_ORDER if k in groups_data]
    if not tab_order:
        return ""

    first_tab = tab_order[0]
    tabs_html = "".join(
        f'<button class="ct-tab{" ct-tab-active" if k == first_tab else ""}" data-group="{escape(k)}">'
        f'{escape(_TAB_LABELS.get(k, k))}</button>'
        for k in tab_order
    )
    groups_json = json.dumps(groups_data, ensure_ascii=False)
    quote_groups_json = json.dumps(quote_groups_by_market or {}, ensure_ascii=False)
    first_tab_js = json.dumps(first_tab)
    root_id = f"{chart_id}-chart-root"
    from_id = f"{chart_id}-chart-from"
    to_id = f"{chart_id}-chart-to"
    canvas_id = f"{chart_id}-line-chart"
    groups_id = f"{chart_id}-chart-groups"
    legend_id = f"{chart_id}-chart-legend"
    root_id_js = json.dumps(root_id)

    return f"""<div class="macro-chart-wrap" id="{escape(root_id)}">
  <div class="chart-controls">
    <div class="chart-tabs">{tabs_html}</div>
    <div class="chart-daterange">
      <span class="cdr-label">From</span>
      <input type="date" id="{escape(from_id)}" class="ct-date-input">
      <span class="cdr-sep">~</span>
      <span class="cdr-label">To</span>
      <input type="date" id="{escape(to_id)}" class="ct-date-input">
    </div>
  </div>
  <div class="chart-body">
    <div class="chart-main">
      <div class="chart-canvas-wrap">
        <canvas id="{escape(canvas_id)}"></canvas>
      </div>
      <div class="chart-toggle-panel">
        <div class="chart-group-tabs" id="{escape(groups_id)}"></div>
        <div class="chart-legend chart-card-grid" id="{escape(legend_id)}"></div>
      </div>
    </div>
  </div>
</div>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js"></script>
<script>
(function(){{
  const GROUPS={groups_json};
  const CARD_GROUPS={quote_groups_json};
  const root=document.getElementById({root_id_js});
  const DPR=window.devicePixelRatio||1;
  const REC_DAYS=90;
  let chart=null;
  let cur={first_tab_js};
  let hiddenIdx=new Set();
  let scrollFrame=null;

  function remToPx(value){{
    const base=parseFloat(getComputedStyle(document.documentElement).fontSize)||16;
    return value*base;
  }}

  function chartHeight(){{
    return Math.round(Math.max(remToPx(20),Math.min(remToPx(32.5),window.innerHeight*0.5)));
  }}

  // 날짜 입력 초기값 설정 (최초 1회)
  (function(){{
    let maxD='';
    Object.values(GROUPS).forEach(function(g){{
      const last=g.dates[g.dates.length-1];
      if(last>maxD) maxD=last;
    }});
    if(!maxD) return;
    const toD=new Date(maxD+'T00:00:00');
    const fromD=new Date(toD);
    fromD.setDate(fromD.getDate()-REC_DAYS);
    document.getElementById('{escape(to_id)}').value=maxD;
    document.getElementById('{escape(from_id)}').value=fromD.toISOString().slice(0,10);
  }})();

  function normFromBase(vals){{
    const base=vals.find(function(v){{return v!=null&&v!==0;}});
    if(base==null) return vals;
    return vals.map(function(v){{return v!=null?Math.round((v/base-1)*10000)/100:null;}});
  }}

  const stickyYAxisPlugin={{
    id:'stickyYAxis',
    afterDraw:function(chart){{
      const wrap=chart.canvas.parentElement;
      const y=chart.scales.y;
      if(!wrap||!y) return;
      const xOffset=wrap.scrollLeft||0;
      const axisW=Math.max(42,y.right+8);
      const ctx=chart.ctx;
      ctx.save();
      ctx.fillStyle='rgba(7,16,28,.96)';
      ctx.fillRect(xOffset,0,axisW,chart.height);
      ctx.strokeStyle='rgba(148,163,184,.18)';
      ctx.beginPath();
      ctx.moveTo(xOffset+y.right+.5,y.top);
      ctx.lineTo(xOffset+y.right+.5,y.bottom);
      ctx.stroke();
      ctx.fillStyle='#8fa3ba';
      const fontSize=Math.round(Math.max(11,Math.min(13,remToPx(0.75))));
      ctx.font=fontSize+'px -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans KR", Roboto, sans-serif';
      ctx.textAlign='right';
      ctx.textBaseline='middle';
      y.ticks.forEach(function(tick){{
        const py=y.getPixelForValue(tick.value);
        if(py<y.top-1||py>y.bottom+1) return;
        const value=Number(tick.value);
        const label=(value>=0?'+':'')+value.toFixed(1)+'%';
        ctx.fillText(label,xOffset+y.right-8,py);
      }});
      ctx.restore();
    }}
  }};

  function build(gk,resetHidden){{
    const g=GROUPS[gk]; if(!g) return;
    cur=gk;
    if(resetHidden){{
      hiddenIdx=new Set();
    }}
    const fromV=document.getElementById('{escape(from_id)}').value;
    const toV=document.getElementById('{escape(to_id)}').value;

    // from~to 범위 필터
    const filtDates=g.dates.filter(function(d){{
      return(!fromV||d>=fromV)&&(!toV||d<=toV);
    }});
    if(!filtDates.length) return;

    // from 날짜 기준 0% 재정규화
    const filtDS=g.datasets.map(function(ds){{
      const dtv={{}};
      g.dates.forEach(function(d,i){{dtv[d]=ds.rawData[i];}});
      const raw=filtDates.map(function(d){{return dtv[d]!=null?dtv[d]:null;}});
      return Object.assign({{}},ds,{{
        data:normFromBase(raw),
        pointRadius:filtDates.length<2?3:0,
        pointHoverRadius:5
      }});
    }});

    // 캔버스 크기 (날짜 수에 따른 스크롤)
    const canvas=document.getElementById('{escape(canvas_id)}');
    if(chart){{chart.destroy();chart=null;}}
    const wrapWidth=Math.max(0,canvas.parentElement.clientWidth||0);
    const pw=Math.max(remToPx(0.55),Math.min(remToPx(1.125),(wrapWidth*1.15)/filtDates.length));
    const w=Math.max(wrapWidth,filtDates.length*pw);
    const h=chartHeight();
    canvas.style.width=w+'px';
    canvas.style.height=h+'px';
    canvas.width=Math.round(w*DPR);
    canvas.height=Math.round(h*DPR);

    chart=new Chart(canvas,{{
      type:'line',
      data:{{labels:filtDates,datasets:filtDS}},
      plugins:[stickyYAxisPlugin],
      options:{{
        responsive:false,maintainAspectRatio:false,
        interaction:{{mode:'index',intersect:false}},
        plugins:{{
          legend:{{display:false}},
          tooltip:{{
            backgroundColor:'rgba(8,19,33,.95)',
            borderColor:'rgba(148,163,184,.18)',borderWidth:1,
            titleColor:'#e6edf3',bodyColor:'#8fa3ba',padding:10,
            itemSort:function(a,b){{
              const av=a.parsed.y;
              const bv=b.parsed.y;
              if(av==null&&bv==null) return 0;
              if(av==null) return 1;
              if(bv==null) return -1;
              return bv-av;
            }},
            callbacks:{{label:function(c){{
              const v=c.parsed.y;
              if(v==null) return ' '+c.dataset.label+': —';
              return ' '+c.dataset.label+': '+(v>=0?'+':'')+v.toFixed(1)+'%';
            }}}}
          }}
        }},
        scales:{{
          x:{{ticks:{{color:'#8fa3ba',maxTicksLimit:14,maxRotation:0}},grid:{{color:'rgba(148,163,184,.08)'}}}},
          y:{{ticks:{{color:'rgba(143,163,186,0)',callback:function(v){{return(v>=0?'+':'')+v.toFixed(1)+'%';}}}},grid:{{color:'rgba(148,163,184,.08)'}}}}
        }}
      }}
    }});
    canvas.parentElement.onscroll=function(){{
      if(scrollFrame) cancelAnimationFrame(scrollFrame);
      scrollFrame=requestAnimationFrame(function(){{
        if(chart) chart.draw();
      }});
    }};

    // 숨김 상태 복원
    hiddenIdx.forEach(function(i){{chart.getDatasetMeta(i).hidden=true;}});
    chart.update();

    // 범례 토글
    const leg=document.getElementById('{escape(legend_id)}');
    const groupTabs=document.getElementById('{escape(groups_id)}');
    const symbolToIdx={{}};
    filtDS.forEach(function(ds,i){{symbolToIdx[ds.displaySymbol]=i;}});
    let currentToggleGroups=[];

    function groupIndexes(scope){{
      if(scope==='all') return filtDS.map(function(_,i){{return i;}});
      const group=currentToggleGroups.find(function(item){{return item.key===scope;}});
      if(!group) return [];
      return group.cards.map(function(card){{return symbolToIdx[card.symbol];}})
        .filter(function(i){{return i!=null;}});
    }}

    function syncGroupButtons(){{
      groupTabs.querySelectorAll('.cg-tab').forEach(function(btn){{
        const indexes=groupIndexes(btn.dataset.scope||'all');
        const anyHidden=indexes.some(function(i){{return hiddenIdx.has(i);}});
        const allHidden=indexes.length>0 && indexes.every(function(i){{return hiddenIdx.has(i);}});
        btn.classList.toggle('cl-hidden', allHidden);
        btn.classList.toggle('cl-partial', anyHidden && !allHidden);
      }});
    }}

    function setHidden(i, hidden){{
      const m=chart.getDatasetMeta(i);
      m.hidden=hidden;
      if(hidden) hiddenIdx.add(i); else hiddenIdx.delete(i);
      chart.update();
      root.querySelectorAll('[data-chart-idx="'+i+'"]').forEach(function(el){{
        el.classList.toggle('cl-hidden', hidden);
      }});
      syncGroupButtons();
    }}

    function setAllHidden(hidden){{
      filtDS.forEach(function(_,i){{
        chart.getDatasetMeta(i).hidden=hidden;
        if(hidden) hiddenIdx.add(i); else hiddenIdx.delete(i);
        root.querySelectorAll('[data-chart-idx="'+i+'"]').forEach(function(el){{
          el.classList.toggle('cl-hidden', hidden);
        }});
      }});
      chart.update();
      syncGroupButtons();
    }}

    function setGroupHidden(scope, hidden){{
      groupIndexes(scope).forEach(function(i){{
        chart.getDatasetMeta(i).hidden=hidden;
        if(hidden) hiddenIdx.add(i); else hiddenIdx.delete(i);
        root.querySelectorAll('[data-chart-idx="'+i+'"]').forEach(function(el){{
          el.classList.toggle('cl-hidden', hidden);
        }});
      }});
      chart.update();
      syncGroupButtons();
    }}

    function escapeHtml(v){{
      return String(v==null?'':v).replace(/[&<>"']/g,function(ch){{
        return {{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[ch];
      }});
    }}

    function uniqueCards(groups){{
      const seen=new Set();
      const cards=[];
      groups.forEach(function(group){{
        group.cards.forEach(function(card){{
          if(seen.has(card.symbol)) return;
          seen.add(card.symbol);
          cards.push(card);
        }});
      }});
      return cards;
    }}

    function fallbackCards(){{
      return filtDS.map(function(ds){{
        return {{
          symbol:ds.displaySymbol,label:ds.label,price:'',change:'',
          changeClass:'flat',color:ds.borderColor
        }};
      }});
    }}

    function renderToggles(){{
      const groups=CARD_GROUPS[cur]||[];
      currentToggleGroups=groups;
      const allCards=groups.length?uniqueCards(groups):fallbackCards();
      const groupButtons=[{{key:'all',label:'전체'}}].concat(groups);

      groupTabs.innerHTML=groupButtons.map(function(group){{
        return '<button class="cg-tab" type="button" data-scope="'+
          escapeHtml(group.key)+'">'+escapeHtml(group.label)+'</button>';
      }}).join('');

      groupTabs.querySelectorAll('.cg-tab').forEach(function(btn){{
        btn.addEventListener('click',function(){{
          const scope=btn.dataset.scope||'all';
          if(scope==='all'){{
            const anyHidden=filtDS.some(function(_,i){{return hiddenIdx.has(i);}});
            setAllHidden(!anyHidden);
            return;
          }}
          const indexes=groupIndexes(scope);
          const anyHidden=indexes.some(function(i){{return hiddenIdx.has(i);}});
          setGroupHidden(scope,!anyHidden);
        }});
      }});

      leg.innerHTML=allCards.map(function(card){{
        const i=symbolToIdx[card.symbol];
        const hidden=i!=null && hiddenIdx.has(i);
        return '<button class="macro-cell chart-toggle-card'+(hidden?' cl-hidden':'')+
          '" type="button" data-idx="'+escapeHtml(i==null?'':i)+
          '" style="--series-color:'+escapeHtml(card.color||'#62c7ff')+'">'+
          '<div class="macro-card-head"><div class="name" title="'+escapeHtml(card.label)+'">'+
          escapeHtml(card.label)+'</div><div class="sym">'+escapeHtml(card.symbol)+'</div></div>'+
          '<div class="macro-value-row"><span class="metric-value">'+escapeHtml(card.price)+'</span>'+
          '<span class="chg '+escapeHtml(card.changeClass)+'">'+escapeHtml(card.change)+'</span></div>'+
          '</button>';
      }}).join('');

      leg.querySelectorAll('.chart-toggle-card').forEach(function(el){{
        if(el.dataset.idx==='') return;
        el.dataset.chartIdx=el.dataset.idx;
        el.addEventListener('click',function(){{
          const i=+el.dataset.idx;
          const m=chart.getDatasetMeta(i);
          setHidden(i,!m.hidden);
        }});
      }});
      syncGroupButtons();
    }}

    renderToggles();
    syncGroupButtons();
  }}

  root.querySelectorAll('.ct-tab').forEach(function(btn){{
    btn.addEventListener('click',function(){{
      root.querySelectorAll('.ct-tab').forEach(function(b){{b.classList.remove('ct-tab-active');}});
      btn.classList.add('ct-tab-active');
      build(btn.dataset.group,true);
    }});
  }});
  document.getElementById('{escape(from_id)}').addEventListener('change',function(){{build(cur,false);}});
  document.getElementById('{escape(to_id)}').addEventListener('change',function(){{build(cur,false);}});
  build({first_tab_js},true);
}})();
</script>"""


def _quote_card_data(quote: MacroQuote) -> dict[str, str]:
    return {
        "symbol": quote.display_symbol,
        "label": _quote_display_name(quote),
        "price": layout.fmt_price(quote.close_price),
        "change": layout.fmt_pct(quote.change_pct),
        "changeClass": layout.change_class(quote.change_pct),
        "color": _SERIES_COLORS.get(quote.display_symbol, "#62c7ff"),
    }


def _quote_groups_for_chart(by_market: dict[str, list[MacroQuote]]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    market_labels = {
        "commodities": "원자재",
        "sector-etfs": "섹터 ETF",
    }

    for market_key, items in by_market.items():
        sorted_items = sorted(items, key=lambda q: _series_sort_key(market_key, q.display_symbol))
        sections: list[dict[str, Any]] = []
        if market_key == "global-indices":
            remaining = {q.display_symbol: q for q in sorted_items}
            for label, symbols in _GLOBAL_INDEX_GROUPS:
                group_items = [q for q in sorted_items if q.display_symbol in symbols]
                if group_items:
                    sections.append({
                        "key": f"{market_key}:{label}",
                        "label": f"글로벌 지수 · {label}",
                        "cards": [_quote_card_data(q) for q in group_items],
                    })
                    for q in group_items:
                        remaining.pop(q.display_symbol, None)
            if remaining:
                sections.append({
                    "key": f"{market_key}:기타",
                    "label": "글로벌 지수 · 기타",
                    "cards": [_quote_card_data(q) for q in remaining.values()],
                })
        elif sorted_items:
            sections.append({
                "key": market_key,
                "label": market_labels.get(market_key, market_key),
                "cards": [_quote_card_data(q) for q in sorted_items],
            })
        if sections:
            result[market_key] = sections
    return result


def _series_groups_for_chart(
    market_key: str,
    label: str,
    series_list: list[MacroPriceSeries],
) -> dict[str, list[dict[str, Any]]]:
    if not series_list:
        return {}
    cards = []
    for series in sorted(series_list, key=lambda s: _series_sort_key(market_key, s.display_symbol)):
        cards.append({
            "symbol": series.display_symbol,
            "label": series.name_en or series.display_symbol,
            "price": "",
            "change": "",
            "changeClass": "flat",
            "color": _SERIES_COLORS.get(series.display_symbol, "#62c7ff"),
        })
    return {
        market_key: [{
            "key": market_key,
            "label": label,
            "cards": cards,
        }]
    }


def _macro_panel_section(
    quotes: list[MacroQuote],
    series_list: list[MacroPriceSeries],
    fx_strength_series: list[MacroPriceSeries],
) -> str:
    if not quotes:
        return ""
    by_market: dict[str, list[MacroQuote]] = {}
    for q in quotes:
        if not _is_macro_view_visible(q.market_key, q.display_symbol):
            continue
        by_market.setdefault(q.market_key, []).append(q)

    chart_quotes_by_market: dict[str, list[MacroQuote]] = {}
    for market_key in _MARKET_ORDER:
        items = by_market.get(market_key)
        if not items:
            continue
        chart_quotes_by_market[market_key] = sorted(
            items,
            key=lambda q: _series_sort_key(market_key, q.display_symbol),
        )

    chart_series = [
        s for s in series_list
        if s.market_key in _MARKET_ORDER
        and _is_macro_view_visible(s.market_key, s.display_symbol)
    ]
    fx_visible_series = [
        s for s in fx_strength_series
        if _is_macro_view_visible(s.market_key, s.display_symbol)
    ]
    chart_series.extend(fx_visible_series)
    quote_groups = _quote_groups_for_chart(chart_quotes_by_market)
    quote_groups.update(_series_groups_for_chart("fx-strength", "통화 전체", fx_visible_series))
    chart_row = _macro_chart_html(chart_series, quote_groups)
    return f"""
<section class="block">
  <h2>글로벌 지수 · 원자재 · 환율</h2>
  <div class="sub">시계열 차트: 기간 내 첫 거래일 종가 기준 상대 수익률. 범례 클릭으로 개별 라인 토글.</div>
  {chart_row}
</section>"""


def render(data: MainPageData) -> str:
    body = "".join(
        section for section in (
            _top_indicators_section(data.macro_quotes, data.daily_macro_items),
            _macro_panel_section(data.macro_quotes, data.macro_price_series, data.fx_strength_series),
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
        main_class="main-wide",
    )
