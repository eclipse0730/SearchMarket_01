from __future__ import annotations

import io
import json
import re
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote_plus, urljoin

import requests

from market_scanner.models import MarketDefinition, StaticTickerMeta


ASSET_DIR = Path(__file__).with_name("assets")
_INVESTING_BASE_URL = "https://www.investing.com"
_INVESTING_SEARCH_URL = f"{_INVESTING_BASE_URL}/search"
_INVESTING_CACHE_PATH = ASSET_DIR / "investing_url_cache.json"
_SP500_CACHE_PATH = ASSET_DIR / "sp500_members_cache.json"
_INVESTING_SEARCH_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; stock-scanner/1.0)",
    "Accept-Language": "en-US,en;q=0.9",
}
_INVESTING_SPECIAL_QUERIES: dict[str, str] = {
    "^GSPC": "S&P 500",
    "^IXIC": "NASDAQ Composite",
    "^DJI": "Dow Jones Industrial Average",
    "^KS11": "KOSPI",
    "^N225": "Nikkei 225",
    "^HSI": "Hang Seng Index",
    "^FTSE": "FTSE 100",
    "^GDAXI": "DAX Index",
    "^FCHI": "CAC 40",
    "000001.SS": "SSE Composite Index",
    "GC=F": "Gold Futures",
    "SI=F": "Silver Futures",
    "CL=F": "Crude Oil Futures",
    "NG=F": "Natural Gas Futures",
    "HG=F": "Copper Futures",
    "ZC=F": "Corn Futures",
    "ZW=F": "Wheat Futures",
    "SB=F": "Sugar Futures",
}

_SECTOR_KO: dict[str, str] = {
    "Financial Services":     "금융 서비스",
    "Healthcare":             "헬스케어",
    "Technology":             "기술",
    "Consumer Cyclical":      "경기 소비재",
    "Consumer Defensive":     "필수 소비재",
    "Industrials":            "산업재",
    "Communication Services": "커뮤니케이션 서비스",
    "Real Estate":            "부동산·리츠",
    "Utilities":              "유틸리티",
    "Energy":                 "에너지",
    "Basic Materials":        "원자재",
}


def _load_meta_asset(filename: str) -> dict[str, StaticTickerMeta]:
    payload = json.loads((ASSET_DIR / filename).read_text(encoding="utf-8"))
    return {
        symbol: StaticTickerMeta(
            name_en=values["name_en"],
            name_local=values["name_local"],
            sector=values["sector"],
            description=values["description"],
        )
        for symbol, values in payload.items()
    }


@lru_cache(maxsize=None)
def _us_static_meta() -> dict[str, StaticTickerMeta]:
    return _load_meta_asset("us_static_meta.json")


@lru_cache(maxsize=None)
def _kospi_static_meta() -> dict[str, StaticTickerMeta]:
    return _load_meta_asset("kospi_static_meta.json")


@lru_cache(maxsize=None)
def _kosdaq_static_meta() -> dict[str, StaticTickerMeta]:
    return _load_meta_asset("kosdaq_static_meta.json")


@lru_cache(maxsize=None)
def _global_index_meta() -> dict[str, StaticTickerMeta]:
    return _load_meta_asset("global_indices_meta.json")


@lru_cache(maxsize=None)
def _theme_proxy_meta() -> dict[str, StaticTickerMeta]:
    return _load_meta_asset("theme_proxies_meta.json")


@lru_cache(maxsize=None)
def _commodity_meta() -> dict[str, StaticTickerMeta]:
    return _load_meta_asset("commodities_meta.json")


def _fetch_sp500_tickers() -> list[str]:
    try:
        import pandas as pd
        url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
        headers = {"User-Agent": "Mozilla/5.0 (compatible; stock-scanner/1.0)"}
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        table = pd.read_html(io.StringIO(resp.text))[0]
        tickers = table["Symbol"].str.replace(".", "-", regex=False).tolist()
        _save_sp500_members_cache(tickers)
        print(f"  S&P 500: loaded {len(tickers)} tickers")
        return tickers
    except Exception as exc:
        print(f"  S&P 500 load failed: {exc}")
        return _load_sp500_members_cache()


def _fetch_fdr_market(market: str, suffix: str, top_n: int, label: str) -> list[str]:
    try:
        import FinanceDataReader as fdr
        import pandas as pd
        df = fdr.StockListing(market)
        df["Marcap"] = pd.to_numeric(df["Marcap"], errors="coerce")
        top = df.nlargest(top_n, "Marcap")
        tickers = [f"{code}{suffix}" for code in top["Code"].tolist()]
        print(f"  {label} (FDR): loaded {len(tickers)} tickers")
        return tickers
    except Exception as exc:
        print(f"  {label} FDR load failed ({type(exc).__name__}) - using static list only")
        return []


def _fetch_krx_kospi200() -> list[str]:
    return _fetch_fdr_market("KOSPI", ".KS", 200, "KOSPI200")


def _fetch_krx_kosdaq150() -> list[str]:
    return _fetch_fdr_market("KOSDAQ", ".KQ", 150, "KOSDAQ150")


def _load_sp500_members_cache() -> list[str]:
    if not _SP500_CACHE_PATH.exists():
        return []
    try:
        payload = json.loads(_SP500_CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(payload, list):
        return []
    return [str(item) for item in payload if item]


def _save_sp500_members_cache(tickers: list[str]) -> None:
    if not tickers:
        return
    unique = sorted({str(ticker) for ticker in tickers if ticker})
    _SP500_CACHE_PATH.write_text(
        json.dumps(unique, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _us_universe() -> list[str]:
    static = list(_us_static_meta().keys())
    sp500 = _fetch_sp500_tickers()
    seen = set(static)
    for t in sp500:
        if t not in seen:
            static.append(t)
            seen.add(t)
    return static


def _kospi_universe() -> list[str]:
    static = list(_kospi_static_meta().keys())
    krx = _fetch_krx_kospi200()
    seen = set(static)
    for t in krx:
        if t not in seen:
            static.append(t)
            seen.add(t)
    return static


def _kosdaq_universe() -> list[str]:
    static = list(_kosdaq_static_meta().keys())
    krx = _fetch_krx_kosdaq150()
    seen = set(static)
    for t in krx:
        if t not in seen:
            static.append(t)
            seen.add(t)
    return static


def _static_symbols(meta: dict[str, StaticTickerMeta]) -> list[str]:
    return list(meta.keys())


@lru_cache(maxsize=1)
def _load_investing_url_cache() -> dict[str, str]:
    if not _INVESTING_CACHE_PATH.exists():
        return {}
    try:
        payload = json.loads(_INVESTING_CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return {str(key): str(value) for key, value in payload.items()}


def _save_investing_url_cache(cache: dict[str, str]) -> None:
    _INVESTING_CACHE_PATH.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _normalized_investing_symbol(symbol: str) -> str:
    return symbol.replace(".KS", "").replace(".KQ", "")


def _investing_query_for_symbol(symbol: str) -> str:
    if symbol in _INVESTING_SPECIAL_QUERIES:
        return _INVESTING_SPECIAL_QUERIES[symbol]
    return _normalized_investing_symbol(symbol)


def _investing_pair_type_for_symbol(symbol: str) -> str:
    if symbol.endswith("=F"):
        return "commodity"
    if symbol in _theme_proxy_meta():
        return "etf"
    if symbol.startswith("^") or symbol.endswith(".SS"):
        return "indice"
    return "Equities"


def _investing_market_preferences(symbol: str) -> tuple[set[str], set[str]]:
    if symbol.endswith(".KS") or symbol.endswith(".KQ"):
        return {"South_Korea"}, {"Seoul", "KOSDAQ"}
    if symbol in _theme_proxy_meta():
        return {"USA"}, {"NASDAQ", "NYSE", "AMEX", "CBOE"}
    if symbol.endswith("=F"):
        return set(), {"ICE", "CME", "COMEX", "NYMEX"}
    if symbol.startswith("^") or symbol.endswith(".SS"):
        return set(), set()
    return {"USA"}, {"NASDAQ", "NYSE", "AMEX"}


def _investing_result_score(item: dict[str, object], symbol: str) -> int:
    expected_type = _investing_pair_type_for_symbol(symbol).casefold()
    preferred_flags, preferred_exchanges = _investing_market_preferences(symbol)
    normalized_symbol = _normalized_investing_symbol(symbol).upper()
    query = _investing_query_for_symbol(symbol).casefold()
    candidate_symbol = str(item.get("symbol") or "").upper()
    candidate_name = str(item.get("name") or "")
    candidate_name_folded = candidate_name.casefold()
    candidate_type = str(item.get("pair_type_raw") or "").casefold()
    candidate_flag = str(item.get("flag") or "")
    candidate_exchange = str(item.get("exchange") or "")
    link = str(item.get("link") or "")

    score = 0
    if candidate_type == expected_type:
        score += 120

    if candidate_symbol == normalized_symbol:
        score += 100
    elif expected_type == "commodity" and candidate_symbol == normalized_symbol.split("=")[0]:
        score += 90
    elif candidate_symbol.startswith(normalized_symbol):
        score += 20

    if preferred_flags and candidate_flag in preferred_flags:
        score += 60
    if preferred_exchanges and candidate_exchange in preferred_exchanges:
        score += 50

    if query == candidate_name_folded:
        score += 80
    elif query in candidate_name_folded:
        score += 50
    elif candidate_name_folded and candidate_name_folded in query:
        score += 25

    if link.startswith("/equities/") and expected_type == "equities":
        score += 20
    if link.startswith("/etfs/") and expected_type == "etf":
        score += 20
    if link.startswith("/commodities/") and expected_type == "commodity":
        score += 20
    if link.startswith("/indices/") and expected_type == "indice":
        score += 20
    if "?cid=" not in link:
        score += 10

    return score


def _extract_investing_quote_results(html: str) -> list[dict[str, object]]:
    match = re.search(r"window\.allResultsQuotesDataArray\s*=\s*(\[[\s\S]*?\]);", html)
    if not match:
        return []
    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError:
        return []
    return [item for item in data if isinstance(item, dict)]


@lru_cache(maxsize=2048)
def _resolve_investing_detail_url(symbol: str) -> str | None:
    cache = _load_investing_url_cache()
    cached_url = cache.get(symbol)
    if cached_url:
        return cached_url

    query = _investing_query_for_symbol(symbol)
    try:
        response = requests.get(
            _INVESTING_SEARCH_URL,
            params={"q": query},
            headers=_INVESTING_SEARCH_HEADERS,
            timeout=12,
        )
        response.raise_for_status()
    except Exception:
        return None

    results = _extract_investing_quote_results(response.text)
    if not results:
        return None

    best = max(results, key=lambda item: _investing_result_score(item, symbol), default=None)
    if not best:
        return None

    link = str(best.get("link") or "").strip()
    if not link.startswith("/"):
        return None

    resolved_url = urljoin(_INVESTING_BASE_URL, link)
    cache[symbol] = resolved_url
    _save_investing_url_cache(cache)
    return resolved_url


def _quote_url_investing_search(symbol: str) -> str:
    query = _investing_query_for_symbol(symbol)
    return f"https://www.investing.com/search?q={quote_plus(query)}"


def _quote_url_investing_detail(symbol: str) -> str:
    return _resolve_investing_detail_url(symbol) or _quote_url_investing_search(symbol)


def _quote_url_naver(symbol: str) -> str:
    code = symbol.replace(".KS", "").replace(".KQ", "")
    return f"https://finance.naver.com/item/main.naver?code={code}"


def _display_strip_kr(symbol: str) -> str:
    return symbol.replace(".KS", "").replace(".KQ", "")


def _display_index(symbol: str) -> str:
    if symbol == "000001.SS":
        return "SSE"
    return symbol.lstrip("^")


def _display_commodity(symbol: str) -> str:
    return symbol.replace("=F", "")


MARKETS: dict[str, MarketDefinition] = {
    "us": MarketDefinition(
        key="us",
        label="US Stocks",
        output_prefix="us",
        currency_symbol="$",
        price_decimals=2,
        universe_loader=_us_universe,
        metadata_loader=_us_static_meta,
        quote_url_builder=_quote_url_investing_detail,
        sector_aliases=_SECTOR_KO,
        notes="NASDAQ 100 (static JSON) + S&P 500 (Wikipedia, live).",
    ),
    "kospi": MarketDefinition(
        key="kospi",
        label="KOSPI Stocks",
        output_prefix="kospi",
        currency_symbol="KRW ",
        price_decimals=0,
        universe_loader=_kospi_universe,
        metadata_loader=_kospi_static_meta,
        quote_url_builder=_quote_url_investing_detail,
        display_symbol_builder=_display_strip_kr,
        sector_aliases=_SECTOR_KO,
        notes="Static JSON + KOSPI200 (KRX API, live).",
    ),
    "kosdaq": MarketDefinition(
        key="kosdaq",
        label="KOSDAQ Stocks",
        output_prefix="kosdaq",
        currency_symbol="KRW ",
        price_decimals=0,
        universe_loader=_kosdaq_universe,
        metadata_loader=_kosdaq_static_meta,
        quote_url_builder=_quote_url_investing_detail,
        display_symbol_builder=_display_strip_kr,
        sector_aliases=_SECTOR_KO,
        notes="Static JSON + KOSDAQ150 (KRX API, live).",
    ),
    "global-indices": MarketDefinition(
        key="global-indices",
        label="Global Indices",
        output_prefix="global-indices",
        currency_symbol="",
        price_decimals=2,
        universe_loader=lambda: _static_symbols(_global_index_meta()),
        metadata_loader=_global_index_meta,
        quote_url_builder=_quote_url_investing_detail,
        display_symbol_builder=_display_index,
        notes="Curated benchmark watchlist backed by asset files.",
    ),
    "theme-proxies": MarketDefinition(
        key="theme-proxies",
        label="Theme Proxies",
        output_prefix="theme-proxies",
        currency_symbol="$",
        price_decimals=2,
        universe_loader=lambda: _static_symbols(_theme_proxy_meta()),
        metadata_loader=_theme_proxy_meta,
        quote_url_builder=_quote_url_investing_detail,
        notes="ETF proxies for theme-level trend tracking.",
    ),
    "commodities": MarketDefinition(
        key="commodities",
        label="Commodities",
        output_prefix="commodities",
        currency_symbol="$",
        price_decimals=2,
        universe_loader=lambda: _static_symbols(_commodity_meta()),
        metadata_loader=_commodity_meta,
        quote_url_builder=_quote_url_investing_detail,
        display_symbol_builder=_display_commodity,
        notes="Commodity futures watchlist backed by asset files.",
    ),
}
