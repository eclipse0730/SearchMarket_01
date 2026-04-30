from __future__ import annotations

import io
import json
import re
from contextlib import redirect_stdout
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote_plus, urljoin, urlparse, urlunparse

import requests

from market_scanner.models import MarketDefinition, StaticTickerMeta


ASSET_DIR = Path(__file__).with_name("assets")
_INSTRUMENTS_PATH = ASSET_DIR / "instruments.json"
_INVESTING_BASE_URL = "https://www.investing.com"
_INVESTING_KR_BASE_URL = "https://kr.investing.com"
_INVESTING_SEARCH_URL = f"{_INVESTING_BASE_URL}/search"
_INVESTING_CACHE_PATH = ASSET_DIR / "investing_url_cache.json"
_SP500_CACHE_PATH = ASSET_DIR / "sp500_members_cache.json"
_SP500_MANUAL_PATH = ASSET_DIR / "sp500_members_manual.json"
_SP500_SOURCE_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
_SP500_STALE_DAYS = 45
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
    "^STOXX50E": "Euro STOXX 50",
    "^BSESN": "BSE SENSEX",
    "^AXJO": "S&P ASX 200",
    "^TWII": "Taiwan Weighted Index",
    "000001.SS": "SSE Composite Index",
    "GC=F": "Gold Futures",
    "SI=F": "Silver Futures",
    "PL=F": "Platinum Futures",
    "CL=F": "Crude Oil Futures",
    "BZ=F": "Brent Crude Oil Futures",
    "NG=F": "Natural Gas Futures",
    "HG=F": "Copper Futures",
    "ZC=F": "Corn Futures",
    "ZW=F": "Wheat Futures",
    "SB=F": "Sugar Futures",
    "KC=F": "Coffee Futures",
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

_STATIC_META_ASSETS: dict[str, str] = {
    "us": "nasdaq100_static_meta.json",
    "nasdaq100": "nasdaq100_static_meta.json",
    "kospi": "kospi_static_meta.json",
    "kosdaq": "kosdaq_static_meta.json",
    "global-indices": "global_indices_meta.json",
    "theme-proxies": "theme_proxies_meta.json",
    "commodities": "commodities_meta.json",
}

_PROTECTED_INSTRUMENT_SOURCES = {"manual", "static"}
_INSTRUMENT_META_FIELDS = ("name_en", "name_local", "sector", "description")


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


def _clean_instrument_value(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _is_placeholder_instrument_value(value: object) -> bool:
    text = _clean_instrument_value(value)
    return text.lower() in {"", "-", "nan", "none", "unknown", "no description", "n/a"}


def _has_hangul(value: object) -> bool:
    return any("\uac00" <= char <= "\ud7a3" for char in _clean_instrument_value(value))


def _default_display_symbol(symbol: str, market_key: str) -> str:
    if market_key in {"kospi", "kosdaq"}:
        code = symbol.replace(".KS", "").replace(".KQ", "")
        return code.zfill(6) if code.isdigit() else code
    if market_key == "global-indices":
        if symbol == "000001.SS":
            return "SSE"
        return symbol.lstrip("^")
    if market_key == "commodities":
        return symbol.replace("=F", "")
    return symbol


def _normalized_instrument_record(symbol: str, values: dict[str, object]) -> dict[str, str]:
    market_key = _clean_instrument_value(values.get("market_key"))
    display_symbol = _clean_instrument_value(values.get("display_symbol")) or _default_display_symbol(symbol, market_key)
    if market_key in {"kospi", "kosdaq"} and display_symbol.isdigit():
        display_symbol = display_symbol.zfill(6)
    record = {
        "market_key": market_key,
        "display_symbol": display_symbol,
        "name_en": _clean_instrument_value(values.get("name_en")) or symbol,
        "name_local": _clean_instrument_value(values.get("name_local")) or _clean_instrument_value(values.get("name_en")) or symbol,
        "sector": _clean_instrument_value(values.get("sector")) or "Unknown",
        "description": _clean_instrument_value(values.get("description")) or "No description",
        "source": _clean_instrument_value(values.get("source")) or "static",
        "updated_at": _clean_instrument_value(values.get("updated_at")),
    }
    return record


@lru_cache(maxsize=1)
def _load_instruments_payload() -> dict[str, dict[str, str]]:
    if not _INSTRUMENTS_PATH.exists():
        return {}
    try:
        payload = json.loads(_INSTRUMENTS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    records: dict[str, dict[str, str]] = {}
    for symbol, values in payload.items():
        if not isinstance(values, dict):
            continue
        symbol_text = str(symbol).strip()
        if not symbol_text:
            continue
        records[symbol_text] = _normalized_instrument_record(symbol_text, values)
    return records


def _instrument_meta(market_key: str, legacy_filename: str) -> dict[str, StaticTickerMeta]:
    legacy = _load_meta_asset(legacy_filename)
    records = _load_instruments_payload()
    instrument_meta = {
        symbol: StaticTickerMeta(
            name_en=values["name_en"],
            name_local=values["name_local"],
            sector=values["sector"],
            description=values["description"],
        )
        for symbol, values in records.items()
        if values.get("market_key") == market_key
    }
    merged = dict(legacy)
    merged.update(instrument_meta)
    return merged


def _write_instruments_payload(payload: dict[str, dict[str, str]]) -> None:
    _INSTRUMENTS_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _load_instruments_payload.cache_clear()


def upsert_instruments_from_frame(frame, market_key: str) -> bool:
    if frame is None or getattr(frame, "empty", True) or "symbol" not in getattr(frame, "columns", []):
        return False

    payload = dict(_load_instruments_payload())
    today = datetime.now(timezone.utc).date().isoformat()
    changed = False

    for _, row in frame.iterrows():
        symbol = _clean_instrument_value(row.get("symbol"))
        if not symbol:
            continue

        current = dict(payload.get(symbol, {}))
        source = _clean_instrument_value(current.get("source")) or "csv"
        protected = source in _PROTECTED_INSTRUMENT_SOURCES
        record = _normalized_instrument_record(
            symbol,
            {
                **current,
                "market_key": current.get("market_key") or market_key,
                "display_symbol": current.get("display_symbol") or row.get("display_symbol") or _default_display_symbol(symbol, market_key),
                "source": source,
            },
        )

        for field in _INSTRUMENT_META_FIELDS:
            value = row.get(field)
            if field == "name_local" and market_key in {"kospi", "kosdaq"} and not _has_hangul(value):
                value = row.get("display_symbol") or _default_display_symbol(symbol, market_key)
            if _is_placeholder_instrument_value(value):
                continue
            if protected and not _is_placeholder_instrument_value(record.get(field)):
                continue
            cleaned = _clean_instrument_value(value)
            if record.get(field) != cleaned:
                record[field] = cleaned
                changed = True

        if not protected and record.get("source") != "csv":
            record["source"] = "csv"
            changed = True
        if not protected and record.get("updated_at") != today:
            record["updated_at"] = today
            changed = True
        if symbol not in payload:
            changed = True
        payload[symbol] = record

    if changed:
        _write_instruments_payload(payload)
    return changed


@lru_cache(maxsize=None)
def _nasdaq100_static_meta() -> dict[str, StaticTickerMeta]:
    return _load_meta_asset(_STATIC_META_ASSETS["nasdaq100"])


@lru_cache(maxsize=None)
def _us_static_meta() -> dict[str, StaticTickerMeta]:
    return _instrument_meta("us", _STATIC_META_ASSETS["us"])


@lru_cache(maxsize=None)
def _kospi_static_meta() -> dict[str, StaticTickerMeta]:
    return _instrument_meta("kospi", _STATIC_META_ASSETS["kospi"])


@lru_cache(maxsize=None)
def _kosdaq_static_meta() -> dict[str, StaticTickerMeta]:
    return _instrument_meta("kosdaq", _STATIC_META_ASSETS["kosdaq"])


@lru_cache(maxsize=None)
def _global_index_meta() -> dict[str, StaticTickerMeta]:
    return _instrument_meta("global-indices", _STATIC_META_ASSETS["global-indices"])


@lru_cache(maxsize=None)
def _theme_proxy_meta() -> dict[str, StaticTickerMeta]:
    return _instrument_meta("theme-proxies", _STATIC_META_ASSETS["theme-proxies"])


@lru_cache(maxsize=None)
def _commodity_meta() -> dict[str, StaticTickerMeta]:
    return _instrument_meta("commodities", _STATIC_META_ASSETS["commodities"])


def _fetch_sp500_tickers() -> list[str]:
    try:
        import pandas as pd
        headers = {"User-Agent": "Mozilla/5.0 (compatible; stock-scanner/1.0)"}
        resp = requests.get(_SP500_SOURCE_URL, headers=headers, timeout=15)
        resp.raise_for_status()
        table = pd.read_html(io.StringIO(resp.text))[0]
        tickers = table["Symbol"].str.replace(".", "-", regex=False).tolist()
        tickers = _apply_sp500_manual_overrides(tickers)
        _save_sp500_members_cache(tickers, _SP500_SOURCE_URL)
        print(f"  S&P 500: loaded {len(tickers)} tickers")
        return tickers
    except Exception as exc:
        print(f"  S&P 500 load failed: {exc}")
        return _apply_sp500_manual_overrides(_load_sp500_members_cache())


@lru_cache(maxsize=None)
def _fetch_fdr_listing(market: str):
    import FinanceDataReader as fdr

    with redirect_stdout(io.StringIO()):
        return fdr.StockListing(market)


def _fdr_market_meta(market: str, suffix: str, label: str) -> dict[str, StaticTickerMeta]:
    try:
        df = _fetch_fdr_listing(market)
    except Exception as exc:
        print(f"  {label} FDR metadata load failed ({type(exc).__name__}) - using static metadata only")
        return {}

    metadata: dict[str, StaticTickerMeta] = {}
    for _, row in df.iterrows():
        code = str(row.get("Code") or "").strip()
        name = str(row.get("Name") or "").strip()
        if not code or not name or name.lower() == "nan":
            continue
        code = code.zfill(6) if code.isdigit() else code
        symbol = f"{code}{suffix}"
        raw_sector = row.get("Sector") or row.get("Industry") or row.get("SectorName") or "Unknown"
        sector = str(raw_sector).strip() if str(raw_sector).strip() and str(raw_sector).lower() != "nan" else "Unknown"
        metadata[symbol] = StaticTickerMeta(
            name_en=name,
            name_local=name,
            sector=sector,
            description=f"{name} ({label})",
        )
    return metadata


def _merge_metadata(*sources: dict[str, StaticTickerMeta]) -> dict[str, StaticTickerMeta]:
    merged: dict[str, StaticTickerMeta] = {}
    for source in sources:
        merged.update(source)
    return merged


@lru_cache(maxsize=None)
def _kospi_metadata() -> dict[str, StaticTickerMeta]:
    return _merge_metadata(_fdr_market_meta("KOSPI", ".KS", "KOSPI"), _kospi_static_meta())


@lru_cache(maxsize=None)
def _kosdaq_metadata() -> dict[str, StaticTickerMeta]:
    return _merge_metadata(_fdr_market_meta("KOSDAQ", ".KQ", "KOSDAQ"), _kosdaq_static_meta())


def _fetch_fdr_market(market: str, suffix: str, top_n: int | None, label: str) -> list[str]:
    try:
        import pandas as pd
        df = _fetch_fdr_listing(market)
        df["Marcap"] = pd.to_numeric(df["Marcap"], errors="coerce")
        top = df.sort_values("Marcap", ascending=False) if top_n is None else df.nlargest(top_n, "Marcap")
        tickers = [
            f"{str(code).strip().zfill(6) if str(code).strip().isdigit() else str(code).strip()}{suffix}"
            for code in top["Code"].tolist()
        ]
        print(f"  {label} (FDR): loaded {len(tickers)} tickers")
        return tickers
    except Exception as exc:
        print(f"  {label} FDR load failed ({type(exc).__name__}) - using static list only")
        return []


def _fetch_krx_kospi200() -> list[str]:
    return _fetch_fdr_market("KOSPI", ".KS", 200, "KOSPI200")


def _fetch_krx_kosdaq150() -> list[str]:
    return _fetch_fdr_market("KOSDAQ", ".KQ", 150, "KOSDAQ150")


def _fetch_krx_kospi_all() -> list[str]:
    return _fetch_fdr_market("KOSPI", ".KS", None, "KOSPI all")


def _fetch_krx_kosdaq_all() -> list[str]:
    return _fetch_fdr_market("KOSDAQ", ".KQ", None, "KOSDAQ all")


def _load_sp500_members_cache() -> list[str]:
    if not _SP500_CACHE_PATH.exists():
        return []
    try:
        payload = json.loads(_SP500_CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []
    if isinstance(payload, list):
        return [str(item) for item in payload if item]
    if not isinstance(payload, dict):
        return []

    updated_at = str(payload.get("updated_at") or "")
    if updated_at and _is_sp500_cache_stale(updated_at):
        print(f"  S&P 500 cache is older than {_SP500_STALE_DAYS} days: {updated_at}")

    tickers = payload.get("tickers")
    if not isinstance(tickers, list):
        return []
    return [str(item) for item in tickers if item]


def _is_sp500_cache_stale(updated_at: str) -> bool:
    try:
        cached_at = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
    except ValueError:
        return True
    if cached_at.tzinfo is None:
        cached_at = cached_at.replace(tzinfo=timezone.utc)
    age = datetime.now(timezone.utc) - cached_at
    return age.days > _SP500_STALE_DAYS


def _save_sp500_members_cache(tickers: list[str], source_url: str) -> None:
    if not tickers:
        return
    unique = sorted({str(ticker) for ticker in tickers if ticker})
    payload = {
        "source": source_url,
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "count": len(unique),
        "tickers": unique,
    }
    _SP500_CACHE_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _load_sp500_manual_overrides() -> tuple[set[str], set[str]]:
    if not _SP500_MANUAL_PATH.exists():
        return set(), set()
    try:
        payload = json.loads(_SP500_MANUAL_PATH.read_text(encoding="utf-8"))
    except Exception:
        return set(), set()
    if isinstance(payload, list):
        return {str(item) for item in payload if item}, set()
    if not isinstance(payload, dict):
        return set(), set()
    add = payload.get("add", [])
    remove = payload.get("remove", [])
    add_set = {str(item) for item in add if item} if isinstance(add, list) else set()
    remove_set = {str(item) for item in remove if item} if isinstance(remove, list) else set()
    return add_set, remove_set


def _apply_sp500_manual_overrides(tickers: list[str]) -> list[str]:
    add, remove = _load_sp500_manual_overrides()
    if not add and not remove:
        return tickers
    merged = {str(ticker) for ticker in tickers if ticker}
    merged.difference_update(remove)
    merged.update(add)
    print(f"  S&P 500 manual overrides: +{len(add)} / -{len(remove)}")
    return sorted(merged)


def _us_universe() -> list[str]:
    static = list(_nasdaq100_static_meta().keys())
    sp500 = _fetch_sp500_tickers()
    seen = set(static)
    for t in sp500:
        if t not in seen:
            static.append(t)
            seen.add(t)
    return static


def _nasdaq100_universe() -> list[str]:
    return list(_nasdaq100_static_meta().keys())


def _sp500_universe() -> list[str]:
    return _fetch_sp500_tickers()


def _kospi_universe() -> list[str]:
    static = list(_kospi_static_meta().keys())
    if len(static) >= 200:
        return static
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


def _merge_static_with_live(static: list[str], live: list[str]) -> list[str]:
    merged = list(static)
    seen = set(merged)
    for ticker in live:
        if ticker not in seen:
            merged.append(ticker)
            seen.add(ticker)
    return merged


def _kospi_all_universe() -> list[str]:
    return _merge_static_with_live(list(_kospi_static_meta().keys()), _fetch_krx_kospi_all())


def _kosdaq_all_universe() -> list[str]:
    return _merge_static_with_live(list(_kosdaq_static_meta().keys()), _fetch_krx_kosdaq_all())


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
    return f"{_INVESTING_KR_BASE_URL}/search?q={quote_plus(query)}"


def _localize_investing_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.netloc.endswith("investing.com"):
        return urlunparse(parsed._replace(scheme="https", netloc="kr.investing.com"))
    return url


def _quote_url_investing_detail(symbol: str) -> str:
    resolved_url = _resolve_investing_detail_url(symbol)
    if resolved_url:
        return _localize_investing_url(resolved_url)
    return _quote_url_investing_search(symbol)


def _quote_url_naver(symbol: str) -> str:
    code = symbol.replace(".KS", "").replace(".KQ", "")
    return f"https://finance.naver.com/item/main.naver?code={code}"


def _display_strip_kr(symbol: str) -> str:
    code = symbol.replace(".KS", "").replace(".KQ", "")
    return code.zfill(6) if code.isdigit() else code


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
        notes="Legacy combined US scan: NASDAQ 100 (static JSON) + S&P 500 (Wikipedia, live).",
    ),
    "nasdaq100": MarketDefinition(
        key="nasdaq100",
        label="NASDAQ 100",
        output_prefix="nasdaq100",
        currency_symbol="$",
        price_decimals=2,
        universe_loader=_nasdaq100_universe,
        metadata_loader=_us_static_meta,
        quote_url_builder=_quote_url_investing_detail,
        sector_aliases=_SECTOR_KO,
        notes="Standalone NASDAQ 100 scan based on the curated static universe.",
    ),
    "sp500": MarketDefinition(
        key="sp500",
        label="S&P 500",
        output_prefix="sp500",
        currency_symbol="$",
        price_decimals=2,
        universe_loader=_sp500_universe,
        metadata_loader=_us_static_meta,
        quote_url_builder=_quote_url_investing_detail,
        sector_aliases=_SECTOR_KO,
        notes="Standalone S&P 500 scan based on Wikipedia live members with cache fallback.",
    ),
    "kospi": MarketDefinition(
        key="kospi",
        label="KOSPI Stocks",
        output_prefix="kospi",
        currency_symbol="KRW ",
        price_decimals=0,
        universe_loader=_kospi_universe,
        metadata_loader=_kospi_metadata,
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
        metadata_loader=_kosdaq_metadata,
        quote_url_builder=_quote_url_investing_detail,
        display_symbol_builder=_display_strip_kr,
        sector_aliases=_SECTOR_KO,
        notes="Static JSON + KOSDAQ150 (KRX API, live).",
    ),
    "kospi-all": MarketDefinition(
        key="kospi-all",
        label="KOSPI All Stocks",
        output_prefix="kospi-all",
        currency_symbol="KRW ",
        price_decimals=0,
        universe_loader=_kospi_all_universe,
        metadata_loader=_kospi_metadata,
        quote_url_builder=_quote_url_investing_detail,
        display_symbol_builder=_display_strip_kr,
        sector_aliases=_SECTOR_KO,
        notes="Full KOSPI universe from FDR/KRX when available, with static metadata fallback.",
    ),
    "kosdaq-all": MarketDefinition(
        key="kosdaq-all",
        label="KOSDAQ All Stocks",
        output_prefix="kosdaq-all",
        currency_symbol="KRW ",
        price_decimals=0,
        universe_loader=_kosdaq_all_universe,
        metadata_loader=_kosdaq_metadata,
        quote_url_builder=_quote_url_investing_detail,
        display_symbol_builder=_display_strip_kr,
        sector_aliases=_SECTOR_KO,
        notes="Full KOSDAQ universe from FDR/KRX when available, with static metadata fallback.",
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
