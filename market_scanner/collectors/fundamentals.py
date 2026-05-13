from __future__ import annotations

import argparse
import io
import re
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from contextlib import redirect_stdout
from datetime import date, datetime
from typing import Any

import pandas as pd

from market_scanner.config.markets import MARKETS
from market_scanner.domain.market_policy import home_market_key
from market_scanner.progress import progress_line
from market_scanner.storage.connection import connect
from market_scanner.storage.fundamentals import (
    instruments_for_market,
    instruments_stale_fundamentals,
    upsert_fundamentals,
)
from market_scanner.storage.runs import create_collection_run, finish_run

_YF_RETRY = 2
_REQUEST_TIMEOUT = 5
_DEFAULT_WORKERS = 2
_MAX_YAHOO_WORKERS = 4
_MAX_NAVER_WORKERS = 8
_SOURCE_CHOICES = ("auto", "yahoo", "naver", "fdr")
_KOREA_MARKETS = {"kospi", "kosdaq"}

_YAHOO_HEADERS = {"user-agent": "Mozilla/5.0 AppleWebKit/537.36"}
_QUOTE_SUMMARY_URL = "https://query2.finance.yahoo.com/v10/finance/quoteSummary/{symbol}"
_QUOTE_URL = "https://query1.finance.yahoo.com/v7/finance/quote"
_QUOTE_MODULES = "financialData,quoteType,defaultKeyStatistics,assetProfile,summaryDetail"

_NAVER_ITEM_URL = "https://finance.naver.com/item/main.naver"
_NAVER_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; stock-scanner/1.0)"}

_FDR_LISTING_CACHE: dict[str, pd.DataFrame | None] = {}

_FUNDAMENTAL_SOURCE_KEYS = {
    "trailingPE",
    "priceToBook",
    "returnOnEquity",
    "returnOnEquityPct",
    "revenueGrowth",
    "revenueGrowthPct",
    "marketCap",
    "targetMeanPrice",
    "sharesOutstanding",
}


def _is_korea_market(market_key: str) -> bool:
    return home_market_key(market_key) in _KOREA_MARKETS


def _korea_code(symbol: str) -> str:
    code = symbol.replace(".KS", "").replace(".KQ", "")
    return re.sub(r"\D", "", code).zfill(6)


def _source_plan(market_key: str, source: str) -> list[str]:
    source = source.lower()
    if source != "auto":
        return [source]
    if _is_korea_market(market_key):
        return ["naver", "fdr", "yahoo"]
    return ["yahoo"]


def _max_workers_for_sources(sources: list[str]) -> int:
    if sources and sources[0] in {"naver", "fdr"}:
        return _MAX_NAVER_WORKERS
    return _MAX_YAHOO_WORKERS


def _has_fundamental_payload(info: dict[str, Any]) -> bool:
    return any(info.get(key) is not None for key in _FUNDAMENTAL_SOURCE_KEYS)


def _normalize_yahoo_value(value: Any) -> Any:
    if isinstance(value, dict):
        if "raw" in value:
            return value.get("raw")
        return {key: _normalize_yahoo_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize_yahoo_value(item) for item in value]
    return value


def _flatten_yahoo_info(payload: dict[str, Any]) -> dict[str, Any]:
    flattened: dict[str, Any] = {}
    for key, value in payload.items():
        normalized = _normalize_yahoo_value(value)
        if isinstance(normalized, dict):
            flattened.update(normalized)
        else:
            flattened[key] = normalized
    return flattened


def _fetch_yahoo_info(symbol: str) -> dict[str, Any]:
    try:
        import requests
    except ImportError:
        return {}

    for attempt in range(_YF_RETRY):
        if attempt:
            time.sleep(attempt * 2)
        try:
            info: dict[str, Any] = {}
            summary_response = requests.get(
                _QUOTE_SUMMARY_URL.format(symbol=symbol),
                params={
                    "modules": _QUOTE_MODULES,
                    "corsDomain": "finance.yahoo.com",
                    "formatted": "false",
                    "symbol": symbol,
                },
                headers=_YAHOO_HEADERS,
                timeout=_REQUEST_TIMEOUT,
            )
            if summary_response.status_code == 200:
                payload = summary_response.json()
                results = payload.get("quoteSummary", {}).get("result") or []
                if results:
                    info.update(_flatten_yahoo_info(results[0]))

            quote_response = requests.get(
                _QUOTE_URL,
                params={"symbols": symbol, "formatted": "false"},
                headers=_YAHOO_HEADERS,
                timeout=_REQUEST_TIMEOUT,
            )
            if quote_response.status_code == 200:
                payload = quote_response.json()
                results = payload.get("quoteResponse", {}).get("result") or []
                if results:
                    info.update(_normalize_yahoo_value(results[0]))

            if _has_fundamental_payload(info):
                return info
        except Exception:
            continue
    return {}


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = re.sub(r"<[^>]+>", " ", str(value))
    text = text.replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def _parse_number(value: Any) -> float | None:
    text = _clean_text(value)
    if not text or text.lower() in {"nan", "none", "n/a", "na", "-", "--"}:
        return None
    text = text.replace(",", "").replace("%", "")
    text = text.replace("배", "").replace("원", "").replace("주", "")
    text = re.sub(r"[^\d.\-]", "", text)
    if not text or text in {"-", ".", "-."}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _parse_korean_amount(value: Any) -> float | None:
    text = _clean_text(value).replace(",", "")
    if not text or text.lower() in {"nan", "none", "n/a", "na", "-", "--"}:
        return None

    total = 0.0
    matched_unit = False
    jo_match = re.search(r"(-?\d+(?:\.\d+)?)\s*조", text)
    if jo_match:
        total += float(jo_match.group(1)) * 1_000_000_000_000
        matched_unit = True
    eok_match = re.search(r"(-?\d+(?:\.\d+)?)\s*억", text)
    if eok_match:
        total += float(eok_match.group(1)) * 100_000_000
        matched_unit = True
    if matched_unit:
        return total
    return _parse_number(text)


def _last_number(values: list[Any]) -> float | None:
    for value in reversed(values):
        number = _parse_number(value)
        if number is not None:
            return number
    return None


def _last_two_numbers(values: list[Any]) -> tuple[float | None, float | None]:
    found: list[float] = []
    for value in reversed(values):
        number = _parse_number(value)
        if number is not None:
            found.append(number)
            if len(found) == 2:
                break
    latest = found[0] if found else None
    previous = found[1] if len(found) > 1 else None
    return latest, previous


def _put_if_missing(info: dict[str, Any], key: str, value: Any) -> None:
    if value is not None and info.get(key) is None:
        info[key] = value


def _parse_naver_label_value(info: dict[str, Any], label: str, value: Any) -> None:
    normalized = _clean_text(label)
    if not normalized:
        return

    if normalized in {"PER", "PER(배)", "주가수익비율"}:
        _put_if_missing(info, "trailingPE", _parse_number(value))
    elif normalized in {"PBR", "PBR(배)", "주가순자산비율"}:
        _put_if_missing(info, "priceToBook", _parse_number(value))
    elif normalized.startswith("ROE"):
        _put_if_missing(info, "returnOnEquityPct", _parse_number(value))
    elif normalized.startswith("시가총액"):
        _put_if_missing(info, "marketCap", _parse_korean_amount(value))
    elif normalized.startswith("상장주식수"):
        _put_if_missing(info, "sharesOutstanding", _parse_number(value))
    elif "목표주가" in normalized:
        _put_if_missing(info, "targetMeanPrice", _parse_number(value))


def _parse_naver_regex_fields(html: str) -> dict[str, Any]:
    info: dict[str, Any] = {}
    id_fields = {
        "trailingPE": "_per",
        "priceToBook": "_pbr",
    }
    for key, element_id in id_fields.items():
        match = re.search(
            rf'id=["\']{re.escape(element_id)}["\'][^>]*>\s*([^<]+)',
            html,
            re.IGNORECASE,
        )
        if match:
            _put_if_missing(info, key, _parse_number(match.group(1)))

    label_fields = {
        "marketCap": "시가총액",
        "sharesOutstanding": "상장주식수",
        "targetMeanPrice": "목표주가",
    }
    for key, label in label_fields.items():
        match = re.search(
            rf"{label}.*?<td[^>]*>(.*?)</td>",
            html,
            re.DOTALL | re.IGNORECASE,
        )
        if not match:
            continue
        parser = _parse_korean_amount if key == "marketCap" else _parse_number
        _put_if_missing(info, key, parser(match.group(1)))
    return info


def _parse_naver_tables(html: str) -> dict[str, Any]:
    try:
        tables = pd.read_html(io.StringIO(html))
    except Exception:
        return {}

    info: dict[str, Any] = {}
    for table in tables:
        frame = table.copy()
        if isinstance(frame.columns, pd.MultiIndex):
            frame.columns = [" ".join(_clean_text(part) for part in col if _clean_text(part)) for col in frame.columns]
        frame = frame.astype(str).replace({"nan": ""})

        for _, row in frame.iterrows():
            cells = [_clean_text(value) for value in row.tolist()]
            if not any(cells):
                continue

            label = cells[0]
            values = cells[1:]
            if label.startswith("ROE"):
                roe = _last_number(values)
                if roe is not None:
                    info["returnOnEquityPct"] = roe
            elif label.startswith("매출액"):
                latest, previous = _last_two_numbers(values)
                if latest is not None and previous not in (None, 0):
                    growth = (latest - previous) / abs(previous) * 100
                    info["revenueGrowthPct"] = round(growth, 1)
            elif label in {"PER", "PER(배)"}:
                _put_if_missing(info, "trailingPE", _last_number(values))
            elif label in {"PBR", "PBR(배)"}:
                _put_if_missing(info, "priceToBook", _last_number(values))

            for idx in range(0, len(cells) - 1):
                _parse_naver_label_value(info, cells[idx], cells[idx + 1])

    return info


def _fetch_naver_info(symbol: str) -> dict[str, Any]:
    try:
        import requests
    except ImportError:
        return {}

    code = _korea_code(symbol)
    if not code:
        return {}

    try:
        response = requests.get(
            _NAVER_ITEM_URL,
            params={"code": code},
            headers=_NAVER_HEADERS,
            timeout=_REQUEST_TIMEOUT,
        )
        response.raise_for_status()
    except Exception:
        return {}

    encoding = response.encoding or response.apparent_encoding or "euc-kr"
    html = response.content.decode(encoding, errors="ignore")
    info = _parse_naver_regex_fields(html)
    table_info = _parse_naver_tables(html)
    for key, value in table_info.items():
        _put_if_missing(info, key, value)
    return info if _has_fundamental_payload(info) else {}


def _fdr_market_name(market_key: str) -> str | None:
    base_market = home_market_key(market_key)
    if base_market == "kospi":
        return "KOSPI"
    if base_market == "kosdaq":
        return "KOSDAQ"
    return None


def _fdr_listing(market_key: str) -> pd.DataFrame | None:
    market_name = _fdr_market_name(market_key)
    if not market_name:
        return None
    if market_name in _FDR_LISTING_CACHE:
        return _FDR_LISTING_CACHE[market_name]

    try:
        import FinanceDataReader as fdr
    except ImportError:
        _FDR_LISTING_CACHE[market_name] = None
        return None

    try:
        with redirect_stdout(io.StringIO()):
            frame = fdr.StockListing(market_name)
    except Exception:
        _FDR_LISTING_CACHE[market_name] = None
        return None

    if not isinstance(frame, pd.DataFrame) or frame.empty:
        _FDR_LISTING_CACHE[market_name] = None
        return None
    _FDR_LISTING_CACHE[market_name] = frame
    return frame


def _row_value(row: pd.Series, candidates: list[str]) -> Any:
    lower_map = {str(col).lower(): col for col in row.index}
    for candidate in candidates:
        col = lower_map.get(candidate.lower())
        if col is not None:
            return row.get(col)
    return None


def _fetch_fdr_info(symbol: str, market_key: str) -> dict[str, Any]:
    frame = _fdr_listing(market_key)
    if frame is None or frame.empty:
        return {}

    code = _korea_code(symbol)
    code_col = next((col for col in frame.columns if str(col).lower() in {"code", "symbol"}), None)
    if code_col is None:
        return {}

    candidates = frame[frame[code_col].astype(str).str.zfill(6) == code]
    if candidates.empty:
        return {}

    row = candidates.iloc[0]
    info: dict[str, Any] = {}
    _put_if_missing(info, "marketCap", _parse_number(_row_value(row, ["Marcap", "MarketCap", "Amount"])))
    _put_if_missing(info, "sharesOutstanding", _parse_number(_row_value(row, ["Stocks", "Shares", "SharesOutstanding"])))
    return info if _has_fundamental_payload(info) else {}


def _fetch_source_info(symbol: str, market_key: str, source: str) -> dict[str, Any]:
    if source == "yahoo":
        return _fetch_yahoo_info(symbol)
    if source == "naver":
        return _fetch_naver_info(symbol) if _is_korea_market(market_key) else {}
    if source == "fdr":
        return _fetch_fdr_info(symbol, market_key)
    return {}


def _merge_info(primary: dict[str, Any], supplemental: dict[str, Any]) -> None:
    for key, value in supplemental.items():
        _put_if_missing(primary, key, value)


def _fetch_task(instr: dict[str, Any], market_key: str, sources: list[str]) -> dict[str, Any]:
    symbol = instr["symbol"]
    merged: dict[str, Any] = {}
    used_sources: list[str] = []

    for source in sources:
        info = _fetch_source_info(symbol, market_key, source)
        if not info:
            continue
        used_sources.append(source)
        _merge_info(merged, info)
        if set(merged).issuperset({"trailingPE", "priceToBook", "returnOnEquityPct", "revenueGrowthPct", "marketCap"}):
            break

    return {
        "instrument": instr,
        "source_provider": used_sources[0] if used_sources else None,
        "used_sources": used_sources,
        "info": merged,
    }


def extract_fundamentals(info: dict[str, Any]) -> dict[str, Any]:
    def safe_float(*keys: str) -> float | None:
        for key in keys:
            val = info.get(key)
            if val is None:
                continue
            try:
                f = float(val)
                return None if pd.isna(f) else f
            except (TypeError, ValueError):
                continue
        return None

    roe_pct = safe_float("returnOnEquityPct")
    if roe_pct is None:
        roe_raw = safe_float("returnOnEquity")
        roe_pct = round(roe_raw * 100, 1) if roe_raw is not None else None

    growth_pct = safe_float("revenueGrowthPct")
    if growth_pct is None:
        growth_raw = safe_float("revenueGrowth")
        growth_pct = round(growth_raw * 100, 1) if growth_raw is not None else None

    return {
        "trailing_pe": safe_float("trailingPE"),
        "price_to_book": safe_float("priceToBook"),
        "return_on_equity": roe_pct,
        "revenue_growth": growth_pct,
        "market_cap": safe_float("marketCap"),
        "target_price": safe_float("targetMeanPrice"),
        "shares_outstanding": safe_float("sharesOutstanding"),
    }



def run_fetch(
    market_key: str,
    date_str: str | None = None,
    stale_only: bool = True,
    stale_days: int = 7,
    database_url: str | None = None,
    limit: int | None = None,
    workers: int = _DEFAULT_WORKERS,
    source: str = "auto",
) -> None:
    trade_date = date.today() if not date_str else datetime.strptime(date_str, "%Y%m%d").date()
    source = source.lower()
    sources = _source_plan(market_key, source)
    max_workers = _max_workers_for_sources(sources)

    with connect(database_url) as conn:
        if stale_only:
            instruments = instruments_stale_fundamentals(conn, market_key, stale_days)
        else:
            instruments = instruments_for_market(conn, market_key)

        if limit:
            instruments = instruments[:limit]

        if not instruments:
            print(f"  fundamentals fetch [{market_key}]: no target instruments")
            return

        if "fdr" in sources:
            _fdr_listing(market_key)

        worker_count = max(1, min(workers, max_workers, len(instruments)))
        run_id = create_collection_run(
            conn, "fundamentals", market_key, trade_date, source, len(instruments),
            params={
                "mode": "fundamentals",
                "stale_only": stale_only,
                "stale_days": stale_days,
                "workers": worker_count,
                "source": source,
                "source_plan": sources,
            },
        )

        print(
            f"  fundamentals fetch [{market_key}] {len(instruments)} symbols  "
            f"source={source} plan={','.join(sources)}  workers={worker_count}  run_id={run_id}"
        )

        success, failed, skipped = 0, 0, 0
        submitted = 0
        source_counts: dict[str, int] = {}
        error_samples: list[Any] = []
        interrupted = False

        def print_progress(force: bool = False) -> None:
            processed = success + failed + skipped
            if not force and processed < len(instruments):
                return
            print(
                progress_line(
                    processed,
                    len(instruments),
                    queued=submitted,
                    active=submitted - processed,
                    success=success,
                    failed=failed,
                    skipped=skipped,
                ),
                end="",
                flush=True,
            )

        def handle_result(result: dict[str, Any]) -> None:
            nonlocal success, failed, skipped
            instr = result["instrument"]
            instrument_id = instr["instrument_id"]
            symbol = instr["symbol"]
            info = result["info"]
            source_provider = result["source_provider"]

            if not info or not source_provider:
                failed += 1
                if len(error_samples) < 30:
                    error_samples.append({"symbol": symbol, "reason": "fetch_failed"})
                print_progress(force=True)
                return

            fundamentals = extract_fundamentals(info)
            if all(v is None for v in fundamentals.values()):
                skipped += 1
                print_progress(force=True)
                return

            row = pd.Series(fundamentals)
            row["raw_sources"] = result.get("used_sources", [])
            upsert_fundamentals(conn, instrument_id, trade_date, source_provider, row, run_id)
            source_counts[source_provider] = source_counts.get(source_provider, 0) + 1
            success += 1
            print_progress(force=True)

        print_progress(force=True)

        try:
            if worker_count == 1:
                for instr in instruments:
                    submitted += 1
                    print_progress(force=True)
                    handle_result(_fetch_task(instr, market_key, sources))
            else:
                instrument_iter = iter(instruments)
                executor = ThreadPoolExecutor(max_workers=worker_count)
                pending: dict[Any, dict[str, Any]] = {}
                try:

                    def submit_next() -> bool:
                        nonlocal submitted
                        try:
                            instr = next(instrument_iter)
                        except StopIteration:
                            return False
                        future = executor.submit(_fetch_task, instr, market_key, sources)
                        pending[future] = instr
                        submitted += 1
                        return True

                    for _ in range(worker_count):
                        if not submit_next():
                            break
                    print_progress(force=True)

                    while pending:
                        try:
                            done, _ = wait(pending, timeout=1, return_when=FIRST_COMPLETED)
                        except KeyboardInterrupt:
                            interrupted = True
                            print("\n  fundamentals fetch: interrupted by user")
                            break
                        if not done:
                            print_progress(force=True)
                            continue
                        for future in done:
                            instr = pending.pop(future)
                            try:
                                handle_result(future.result())
                            except Exception as exc:
                                symbol = instr["symbol"]
                                failed += 1
                                if len(error_samples) < 30:
                                    error_samples.append({"symbol": symbol, "reason": type(exc).__name__})
                                print_progress(force=True)
                            submit_next()
                            print_progress(force=True)
                finally:
                    for future in pending:
                        future.cancel()
                    executor.shutdown(wait=False, cancel_futures=True)
        except KeyboardInterrupt:
            interrupted = True
            print("\n  fundamentals fetch: interrupted by user")

        print_progress(force=True)
        print()
        status = "cancelled" if interrupted else "success" if not failed else ("partial" if success else "failed")
        finish_run(conn, run_id, status=status, success_count=success, failed_count=failed, skipped_count=skipped, error_samples=error_samples)
        source_summary = ", ".join(f"{key}={value}" for key, value in sorted(source_counts.items()))
        print(
            f"  fundamentals fetch [{market_key}] done: "
            f"success={success} failed={failed} skipped={skipped} status={status}"
            + (f" sources={source_summary}" if source_summary else "")
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Fundamentals collector.")
    parser.add_argument("--database-url", default=None)
    sub = parser.add_subparsers(dest="command", required=True)

    fetch_p = sub.add_parser("fetch", help="Fetch fundamentals for stale/missing instruments.")
    fetch_p.add_argument("--market", required=True, choices=sorted(MARKETS))
    fetch_p.add_argument("--date", default=None, help="as_of_date YYYYMMDD (default: today).")
    fetch_p.add_argument(
        "--all",
        action="store_true",
        dest="fetch_all",
        help="Fetch every active instrument for the market (default: stale/missing only).",
    )
    fetch_p.add_argument("--stale-days", type=int, default=7)
    fetch_p.add_argument("--limit", type=int, default=None)
    fetch_p.add_argument(
        "--workers",
        type=int,
        default=_DEFAULT_WORKERS,
        help=(
            f"Parallel request workers. Yahoo/US capped at {_MAX_YAHOO_WORKERS}, "
            f"Korea Naver/FDR capped at {_MAX_NAVER_WORKERS} (default: {_DEFAULT_WORKERS})."
        ),
    )
    fetch_p.add_argument(
        "--source",
        choices=_SOURCE_CHOICES,
        default="auto",
        help="Fundamentals source. auto uses Naver/FDR/Yahoo for Korea and Yahoo for US.",
    )

    args = parser.parse_args()
    if args.command == "fetch":
        run_fetch(
            args.market,
            args.date,
            stale_only=not args.fetch_all,
            stale_days=args.stale_days,
            database_url=args.database_url,
            limit=args.limit,
            workers=args.workers,
            source=args.source,
        )


if __name__ == "__main__":
    main()
