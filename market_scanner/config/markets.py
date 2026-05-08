from __future__ import annotations

import io
import json
import re
from contextlib import redirect_stdout
from functools import lru_cache
from html import unescape
from pathlib import Path
from urllib.parse import quote_plus, urljoin, urlparse, urlunparse

import requests

from market_scanner.models import MarketDefinition, StaticTickerMeta, UniverseLoader


ASSET_DIR = Path(__file__).resolve().parent.parent / "assets"
_INSTRUMENTS_PATH = ASSET_DIR / "instruments.json"
_INVESTING_BASE_URL = "https://www.investing.com"
_INVESTING_KR_BASE_URL = "https://kr.investing.com"
_INVESTING_SEARCH_URL = f"{_INVESTING_BASE_URL}/search"
_INVESTING_CACHE_PATH = ASSET_DIR / "investing_url_cache.json"
_SP500_SOURCE_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
_NASDAQ100_SOURCE_URL = "https://en.wikipedia.org/wiki/Nasdaq-100"
_NAVER_MARKET_SUM_URL = "https://finance.naver.com/sise/sise_market_sum.naver"
_NAVER_MARKET_SUM_MAX_PAGES = 90
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
    "000300.SS": "CSI 300",
    "^KQ11": "KOSDAQ Composite",
    "^RUT": "Russell 2000",
    "^BVSP": "Bovespa",
    "^NSEI": "Nifty 50",
    "^STI": "Straits Times Index",
    "^NDX": "NASDAQ 100",
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
    "global-indices": "global_indices_meta.json",
    "commodities": "commodities_meta.json",
}

_THEME_PROXY_SYMBOLS: frozenset[str] = frozenset({
    "SOXX", "BOTZ", "IBB", "XLK", "XLE", "XLF", "ICLN",
    "ARKK", "ITA", "HACK", "MCHI", "GLD", "TLT",
})

def _database_url() -> str:
    from market_scanner.storage.connection import database_url
    return database_url()


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


def has_hangul(value: object) -> bool:
    return any("\uac00" <= char <= "\ud7a3" for char in str(value or ""))


def _default_display_symbol(symbol: str, market_key: str) -> str:
    if market_key in {"kospi", "kosdaq"}:
        return display_strip_kr(symbol)
    if market_key == "global-indices":
        if symbol == "000001.SS":
            return "SSE"
        if symbol == "000300.SS":
            return "CSI300"
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


_DB_INSTRUMENT_META_CACHE: dict[str, dict[str, StaticTickerMeta]] = {}


def _db_instrument_meta(market_key: str) -> dict[str, StaticTickerMeta]:
    cached = _DB_INSTRUMENT_META_CACHE.get(market_key)
    if cached is not None:
        return cached

    try:
        import psycopg
    except Exception:
        return {}

    try:
        with psycopg.connect(_database_url(), connect_timeout=3) as conn:
            rows = conn.execute(
                """
                SELECT symbol, name_en, name_local, sector, description
                FROM instruments
                WHERE market_key = %s
                  AND is_active = TRUE
                """,
                (market_key,),
            ).fetchall()
    except Exception:
        return {}

    metadata: dict[str, StaticTickerMeta] = {}
    for symbol, name_en, name_local, sector, description in rows:
        symbol_text = _clean_instrument_value(symbol)
        if not symbol_text:
            continue
        metadata[symbol_text] = StaticTickerMeta(
            name_en=_clean_instrument_value(name_en) or symbol_text,
            name_local=_clean_instrument_value(name_local) or _clean_instrument_value(name_en) or symbol_text,
            sector=_clean_instrument_value(sector) or "Unknown",
            description=_clean_instrument_value(description) or "No description",
        )

    if metadata:
        _DB_INSTRUMENT_META_CACHE[market_key] = metadata
    return metadata


def clear_db_instrument_meta_cache() -> None:
    _DB_INSTRUMENT_META_CACHE.clear()


def _instrument_meta_db_first(market_key: str, legacy_filename: str) -> dict[str, StaticTickerMeta]:
    db_meta = _db_instrument_meta(market_key)
    if db_meta:
        return db_meta
    return _instrument_meta(market_key, legacy_filename)


@lru_cache(maxsize=None)
def _global_index_meta() -> dict[str, StaticTickerMeta]:
    return _instrument_meta_db_first("global-indices", _STATIC_META_ASSETS["global-indices"])


@lru_cache(maxsize=None)
def _commodity_meta() -> dict[str, StaticTickerMeta]:
    return _instrument_meta_db_first("commodities", _STATIC_META_ASSETS["commodities"])


def _global_index_universe() -> list[str]:
    return _static_symbols(_instrument_meta("global-indices", _STATIC_META_ASSETS["global-indices"]))


def _commodity_universe() -> list[str]:
    return _static_symbols(_instrument_meta("commodities", _STATIC_META_ASSETS["commodities"]))


def _fetch_sp500_tickers() -> list[str]:
    try:
        import pandas as pd
        headers = {"User-Agent": "Mozilla/5.0 (compatible; stock-scanner/1.0)"}
        resp = requests.get(_SP500_SOURCE_URL, headers=headers, timeout=15)
        resp.raise_for_status()
        table = pd.read_html(io.StringIO(resp.text))[0]
        tickers = table["Symbol"].str.replace(".", "-", regex=False).tolist()
        print(f"  S&P 500: loaded {len(tickers)} tickers")
        return tickers
    except Exception as exc:
        print(f"  S&P 500 load failed: {exc}")
        return []


def _fetch_nasdaq100_tickers() -> list[str]:
    try:
        import pandas as pd
        headers = {"User-Agent": "Mozilla/5.0 (compatible; stock-scanner/1.0)"}
        resp = requests.get(_NASDAQ100_SOURCE_URL, headers=headers, timeout=15)
        resp.raise_for_status()
        tables = pd.read_html(io.StringIO(resp.text))
        for table in tables:
            col = next((c for c in ("Ticker", "Symbol", "Code") if c in table.columns), None)
            if col and len(table) >= 90:
                tickers = table[col].str.replace(".", "-", regex=False).tolist()
                print(f"  NASDAQ 100 (Wikipedia): loaded {len(tickers)} tickers")
                return tickers
        print("  NASDAQ 100 load failed: no suitable table found")
        return []
    except Exception as exc:
        print(f"  NASDAQ 100 load failed: {exc}")
        return []


@lru_cache(maxsize=None)
def _fetch_fdr_listing(market: str):
    import FinanceDataReader as fdr

    with redirect_stdout(io.StringIO()):
        return fdr.StockListing(market)


def _is_us_preferred_symbol(symbol: str) -> bool:
    parts = symbol.upper().replace(".", " ").replace("-", " ").split()
    return len(parts) >= 2 and (parts[-1] == "PR" or parts[-2] == "PR")


def _is_us_special_right_or_unit_symbol(symbol: str) -> bool:
    parts = symbol.upper().replace(".", " ").replace("-", " ").split()
    if not parts:
        return False
    return (
        parts[-1] in {"RT", "WI"}
        or parts[-2:] == ["RT", "WI"]
        or symbol.upper().endswith("-U")
    )


def _is_excluded_us_listing_symbol(symbol: str) -> bool:
    return _is_us_preferred_symbol(symbol) or _is_us_special_right_or_unit_symbol(symbol)


def _is_excluded_us_listing_name(name: object) -> bool:
    text = str(name or "").strip().upper()
    return bool(text) and (
        " RIGHTS" in f" {text}"
        or " RIGHT" in f" {text}"
        or "UNITS" in text
        or "WHEN ISSUED" in text
        or "PREFERRED" in text
        or " PREF SH" in text
    )


def _fetch_fdr_us_symbols(exchange: str, label: str) -> list[str]:
    """Fetch symbols from a US exchange or index via FDR (NASDAQ/NYSE/AMEX/NASDAQ100/SP500)."""
    try:
        df = _fetch_fdr_listing(exchange)
        sym_col = next((c for c in ("Symbol", "Code") if c in df.columns), None)
        if sym_col is None:
            print(f"  {label} FDR load failed: no Symbol/Code column (columns={list(df.columns)})")
            return []
        symbols: list[str] = []
        for _, row in df.iterrows():
            sym = str(row.get(sym_col) or "").strip().upper().replace(".", "-")
            if not sym or sym in {"N/A", "NA", "NAN"}:
                continue
            if _is_excluded_us_listing_symbol(sym):
                continue
            if _is_excluded_us_listing_name(row.get("Name")):
                continue
            symbols.append(sym)
        print(f"  {label} (FDR): loaded {len(symbols)} symbols")
        return symbols
    except Exception as exc:
        print(f"  {label} FDR load failed ({type(exc).__name__})")
        return []


def _fetch_fdr_us_all() -> list[str]:
    """Fetch all US common stocks from NASDAQ + NYSE via FDR."""
    seen: set[str] = set()
    result: list[str] = []
    for exchange, label in (("NASDAQ", "NASDAQ"), ("NYSE", "NYSE")):
        for sym in _fetch_fdr_us_symbols(exchange, label):
            if sym not in seen:
                seen.add(sym)
                result.append(sym)
    return result


def _fdr_us_meta(exchange: str, label: str) -> dict[str, StaticTickerMeta]:
    """Build metadata dict from FDR US exchange or index listing."""
    try:
        df = _fetch_fdr_listing(exchange)
    except Exception as exc:
        print(f"  {label} FDR metadata load failed ({type(exc).__name__})")
        return {}
    sym_col = next((c for c in ("Symbol", "Code") if c in df.columns), None)
    if sym_col is None:
        return {}
    metadata: dict[str, StaticTickerMeta] = {}
    for _, row in df.iterrows():
        sym = str(row.get(sym_col) or "").strip().upper().replace(".", "-")
        if not sym or sym in {"N/A", "NA", "NAN"}:
            continue
        if _is_excluded_us_listing_symbol(sym):
            continue
        name = str(row.get("Name") or "").strip()
        if _is_excluded_us_listing_name(name):
            continue
        if not name or name.lower() == "nan":
            name = sym
        raw_sector = row.get("Industry") or row.get("Sector") or row.get("SectorName") or "Unknown"
        sector = str(raw_sector).strip() if str(raw_sector).strip() and str(raw_sector).lower() != "nan" else "Unknown"
        metadata[sym] = StaticTickerMeta(
            name_en=name,
            name_local=name,
            sector=sector,
            description=f"{name} ({label})",
        )
    return metadata


def _clean_html_text(value: str) -> str:
    return re.sub(r"\s+", " ", unescape(value)).strip()


def _naver_market_label(sosok: str) -> str:
    return "KOSPI" if sosok == "0" else "KOSDAQ" if sosok == "1" else f"Naver market {sosok}"


@lru_cache(maxsize=None)
def _fetch_naver_market_sum_rows(sosok: str) -> tuple[tuple[str, str], ...]:
    label = _naver_market_label(sosok)
    headers = {"User-Agent": "Mozilla/5.0 (compatible; stock-scanner/1.0)"}
    rows: list[tuple[str, str]] = []
    seen: set[str] = set()
    for page in range(1, _NAVER_MARKET_SUM_MAX_PAGES + 1):
        try:
            response = requests.get(
                _NAVER_MARKET_SUM_URL,
                params={"sosok": sosok, "page": page},
                headers=headers,
                timeout=12,
            )
            response.raise_for_status()
        except Exception as exc:
            if page == 1:
                print(f"  {label} Naver listing load failed: {exc}")
            break
        html = response.content.decode(response.encoding or "euc-kr", errors="ignore")
        matches = re.findall(
            r'href="/item/main\.naver\?code=(\d{6})"[^>]*>(.*?)</a>',
            html,
            flags=re.IGNORECASE | re.DOTALL,
        )
        added = 0
        for code, raw_name in matches:
            if code in seen:
                continue
            name = _clean_html_text(raw_name)
            if not name:
                continue
            rows.append((code, name))
            seen.add(code)
            added += 1
        if added == 0:
            break
    if rows:
        print(f"  {label} (Naver): loaded {len(rows)} tickers")
    return tuple(rows)


def _naver_market_symbols(sosok: str, suffix: str, label: str) -> list[str]:
    rows = _fetch_naver_market_sum_rows(sosok)
    if rows:
        print(f"  {label} (Naver fallback): using {len(rows)} tickers")
    return [f"{code}{suffix}" for code, _ in rows]


def _naver_market_meta(sosok: str, suffix: str, label: str) -> dict[str, StaticTickerMeta]:
    metadata: dict[str, StaticTickerMeta] = {}
    for code, name in _fetch_naver_market_sum_rows(sosok):
        symbol = f"{code}{suffix}"
        metadata[symbol] = StaticTickerMeta(
            name_en=name,
            name_local=name,
            sector="Unknown",
            description=f"{name} ({label})",
        )
    return metadata


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


_NAVER_ITEM_URL = "https://finance.naver.com/item/main.naver"
_NAVER_ITEM_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; stock-scanner/1.0)"}


def fetch_naver_item_meta(code: str) -> tuple[str | None, str | None]:
    """Naver Finance 개별 종목 페이지에서 (name_local, sector) 반환.

    code: 6자리 숫자 문자열 (예: "005930", "003545")
    반환: (name_local, sector) — 취득 실패 시 None
    """
    try:
        resp = requests.get(
            _NAVER_ITEM_URL,
            params={"code": code},
            headers=_NAVER_ITEM_HEADERS,
            timeout=12,
        )
        resp.raise_for_status()
    except Exception:
        return None, None

    html = resp.content.decode(resp.encoding or "euc-kr", errors="ignore")

    # 회사명: <title>삼성전자 : 네이버 금융</title>
    name: str | None = None
    m = re.search(r"<title>\s*(.+?)\s*[:：]", html)
    if m:
        candidate = _clean_html_text(m.group(1))
        if candidate and len(candidate) > 1 and candidate.lower() not in ("nan", "-"):
            name = candidate

    # 업종: 여러 HTML 패턴 시도 (Naver 구조 변경에 대비)
    sector: str | None = None
    sector_patterns = [
        # 동종업종비교 섹션: (업종명 : <a ...>반도체와반도체장비</a>)
        r"업종명\s*:\s*<a[^>]*>([^<]{2,60})</a>",
        # <dl class="blind"><dt>업종</dt><dd>전기·전자</dd>
        r"<dt>\s*업종\s*</dt>\s*<dd>\s*([^<\n]{2,40})\s*</dd>",
        # <em class="industry_img"><a ...>전기·전자</a>
        r'class="industry_img"[^>]*>.*?<a[^>]*>([^<]{2,40})</a>',
        # <th>업종</th><td><a ...>전기·전자</a>
        r"업종\s*</th>\s*<td[^>]*>(?:<a[^>]*>)?\s*([^<\n]{2,40})",
    ]
    for pat in sector_patterns:
        m = re.search(pat, html, re.DOTALL | re.IGNORECASE)
        if m:
            candidate = _clean_html_text(m.group(1))
            if (
                candidate
                and len(candidate) > 1
                and candidate.lower() not in ("nan", "unknown", "-", "n/a")
            ):
                sector = candidate
                break

    return name, sector


@lru_cache(maxsize=None)
def _kospi_metadata() -> dict[str, StaticTickerMeta]:
    db_meta = _db_instrument_meta("kospi")
    if db_meta:
        return db_meta
    return _merge_metadata(
        _naver_market_meta("0", ".KS", "KOSPI"),
        _fdr_market_meta("KOSPI", ".KS", "KOSPI"),
    )


@lru_cache(maxsize=None)
def _kosdaq_metadata() -> dict[str, StaticTickerMeta]:
    db_meta = _db_instrument_meta("kosdaq")
    if db_meta:
        return db_meta
    return _merge_metadata(
        _naver_market_meta("1", ".KQ", "KOSDAQ"),
        _fdr_market_meta("KOSDAQ", ".KQ", "KOSDAQ"),
    )


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
        print(f"  {label} FDR load failed ({type(exc).__name__}) - using fallback list")
        return []


def _fetch_krx_kospi200() -> list[str]:
    return _fetch_fdr_market("KOSPI", ".KS", 200, "KOSPI200")


def _fetch_krx_kospi100() -> list[str]:
    return _fetch_fdr_market("KOSPI", ".KS", 100, "KOSPI100")


def _fetch_krx_kosdaq150() -> list[str]:
    return _fetch_fdr_market("KOSDAQ", ".KQ", 150, "KOSDAQ150")


def _fetch_krx_kospi_all() -> list[str]:
    return _fetch_fdr_market("KOSPI", ".KS", None, "KOSPI all") or _naver_market_symbols("0", ".KS", "KOSPI all")


def _fetch_krx_kosdaq_all() -> list[str]:
    return _fetch_fdr_market("KOSDAQ", ".KQ", None, "KOSDAQ all") or _naver_market_symbols("1", ".KQ", "KOSDAQ all")


def _nasdaq100_universe() -> list[str]:
    return _fetch_nasdaq100_tickers()


def _sp500_universe() -> list[str]:
    return _fetch_sp500_tickers()


def _nasdaq_universe() -> list[str]:
    return _fetch_fdr_us_symbols("NASDAQ", "NASDAQ")


def _nyse_universe() -> list[str]:
    return _fetch_fdr_us_symbols("NYSE", "NYSE")


def _amex_universe() -> list[str]:
    return _fetch_fdr_us_symbols("AMEX", "AMEX")


def _us_all_universe() -> list[str]:
    return _fetch_fdr_us_all()


@lru_cache(maxsize=None)
def _us_metadata() -> dict[str, StaticTickerMeta]:
    db_meta = _db_instrument_meta("us")
    if db_meta:
        return db_meta
    return _merge_metadata(
        _fdr_us_meta("NASDAQ", "NASDAQ"),
        _fdr_us_meta("NYSE", "NYSE"),
    )


def _kospi200_universe() -> list[str]:
    return _fetch_krx_kospi200()


def _kospi100_universe() -> list[str]:
    return _fetch_krx_kospi100()


def _kosdaq150_universe() -> list[str]:
    return _fetch_krx_kosdaq150()


def _kospi_universe() -> list[str]:
    return _fetch_krx_kospi_all()


def _kosdaq_universe() -> list[str]:
    return _fetch_krx_kosdaq_all()


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
    if symbol in _THEME_PROXY_SYMBOLS:
        return "etf"
    if symbol.startswith("^") or symbol.endswith(".SS"):
        return "indice"
    return "Equities"


def _investing_market_preferences(symbol: str) -> tuple[set[str], set[str]]:
    if symbol.endswith(".KS") or symbol.endswith(".KQ"):
        return {"South_Korea"}, {"Seoul", "KOSDAQ"}
    if symbol in _THEME_PROXY_SYMBOLS:
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


def display_strip_kr(symbol: str) -> str:
    code = symbol.replace(".KS", "").replace(".KQ", "")
    return code.zfill(6) if code.isdigit() else code


def _display_index(symbol: str) -> str:
    if symbol == "000001.SS":
        return "SSE"
    if symbol == "000300.SS":
        return "CSI300"
    return symbol.lstrip("^")


def _display_commodity(symbol: str) -> str:
    return symbol.replace("=F", "")


REPRESENTATIVE_UNIVERSE_LOADERS: dict[str, UniverseLoader] = {
    "nasdaq": _nasdaq_universe,
    "nyse": _nyse_universe,
    "amex": _amex_universe,
    "nasdaq100": _nasdaq100_universe,
    "sp500": _sp500_universe,
    "kospi100": _kospi100_universe,
    "kospi200": _kospi200_universe,
    "kosdaq150": _kosdaq150_universe,
}


MARKETS: dict[str, MarketDefinition] = {
    "us": MarketDefinition(
        key="us",
        label="US Stocks",
        output_prefix="us",
        currency_symbol="$",
        price_decimals=2,
        universe_loader=_us_all_universe,
        metadata_loader=_us_metadata,
        quote_url_builder=_quote_url_investing_detail,
        sector_aliases=_SECTOR_KO,
        notes="Full US listed-stock universe from FDR (NASDAQ+NYSE) with NASDAQ Trader fallback.",
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
        display_symbol_builder=display_strip_kr,
        sector_aliases=_SECTOR_KO,
        notes="Full KOSPI universe from FDR/KRX when available, with static metadata fallback.",
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
        display_symbol_builder=display_strip_kr,
        sector_aliases=_SECTOR_KO,
        notes="Full KOSDAQ universe from FDR/KRX when available, with static metadata fallback.",
    ),
    "global-indices": MarketDefinition(
        key="global-indices",
        label="Global Indices",
        output_prefix="global-indices",
        currency_symbol="",
        price_decimals=2,
        universe_loader=_global_index_universe,
        metadata_loader=_global_index_meta,
        quote_url_builder=_quote_url_investing_detail,
        display_symbol_builder=_display_index,
        notes="Curated benchmark watchlist backed by asset files.",
    ),
    "commodities": MarketDefinition(
        key="commodities",
        label="Commodities",
        output_prefix="commodities",
        currency_symbol="$",
        price_decimals=2,
        universe_loader=_commodity_universe,
        metadata_loader=_commodity_meta,
        quote_url_builder=_quote_url_investing_detail,
        display_symbol_builder=_display_commodity,
        notes="Commodity futures watchlist backed by asset files.",
    ),
}
