from __future__ import annotations

import argparse
import io
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import redirect_stderr, redirect_stdout
from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd
import psycopg
from psycopg.types.json import Jsonb

from market_scanner.storage.db import (
    connect,
    country_currency_for_market,
    home_market_key,
    upsert_daily_price,
)
from market_scanner.config.markets import MARKETS

_DEFAULT_HISTORY_YEARS = 1
_DEFAULT_FETCH_WORKERS = 8
_FDR_RETRY = 2
_YF_RETRY = 1


# ── OHLCV 정규화 ──────────────────────────────────────────────────────────────

def _normalize_ohlcv(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()
    lower_to_cap = {"open": "Open", "high": "High", "low": "Low", "close": "Close", "volume": "Volume"}
    rename_map = {c: lower_to_cap[c.lower()] for c in frame.columns if c.lower() in lower_to_cap}
    frame = frame.rename(columns=rename_map)
    required = ["Open", "High", "Low", "Close"]
    if any(c not in frame.columns for c in required):
        return pd.DataFrame()
    keep = required + (["Volume"] if "Volume" in frame.columns else [])
    frame = frame[keep].apply(pd.to_numeric, errors="coerce").dropna(subset=["Close"])
    if hasattr(frame.index, "tz") and frame.index.tz is not None:
        frame.index = frame.index.tz_localize(None)
    return frame.sort_index()


# ── fdr fetch ─────────────────────────────────────────────────────────────────

def _korea_code(symbol: str) -> str:
    return symbol.replace(".KS", "").replace(".KQ", "").zfill(6)


def _fdr_symbol(symbol: str, market_key: str) -> str:
    if _is_korea(market_key):
        return _korea_code(symbol)
    return symbol


def _fetch_fdr(symbol: str, market_key: str, start: str, end: str) -> pd.DataFrame:
    try:
        import FinanceDataReader as fdr
    except ImportError:
        return pd.DataFrame()

    code = _fdr_symbol(symbol, market_key)
    retry_count = _FDR_RETRY if _is_korea(market_key) else 1
    for attempt in range(retry_count):
        if attempt:
            time.sleep(1)
        try:
            with redirect_stdout(io.StringIO()):
                hist = fdr.DataReader(code, start, end)
            normalized = _normalize_ohlcv(hist)
            if not normalized.empty:
                return normalized
        except Exception:
            continue
    return pd.DataFrame()


# ── yfinance fetch ────────────────────────────────────────────────────────────

def _fetch_yfinance(symbol: str, start: str, end: str) -> pd.DataFrame:
    try:
        import yfinance as yf
    except ImportError:
        return pd.DataFrame()

    for attempt in range(_YF_RETRY):
        if attempt:
            time.sleep(attempt * 2)
        try:
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                hist = yf.Ticker(symbol).history(start=start, end=end, auto_adjust=True)
            normalized = _normalize_ohlcv(hist)
            if not normalized.empty:
                return normalized
        except Exception:
            continue
    return pd.DataFrame()


# ── 통합 fetch ────────────────────────────────────────────────────────────────

def _is_korea(market_key: str) -> bool:
    return home_market_key(market_key) in {"kospi", "kosdaq"}


def _uses_fdr_primary(market_key: str) -> bool:
    return home_market_key(market_key) in {"kospi", "kosdaq", "us"}


def fetch_ohlcv(symbol: str, market_key: str, start: str, end: str) -> tuple[pd.DataFrame, str]:
    """fdr → yfinance 순서로 OHLCV를 fetch. (DataFrame, source_provider) 반환."""
    if _uses_fdr_primary(market_key):
        hist = _fetch_fdr(symbol, market_key, start, end)
        if not hist.empty:
            return hist, "fdr"
    hist = _fetch_yfinance(symbol, start, end)
    if not hist.empty:
        return hist, "yfinance"
    return pd.DataFrame(), "none"


# ── DB 조회 헬퍼 ──────────────────────────────────────────────────────────────

def _last_price_date(conn: psycopg.Connection, instrument_id: int, source_provider: str) -> date | None:
    row = conn.execute(
        "SELECT MAX(trade_date) FROM daily_prices WHERE instrument_id = %s AND source_provider = %s",
        (instrument_id, source_provider),
    ).fetchone()
    return row[0] if row and row[0] else None


def _last_price_date_any_source(conn: psycopg.Connection, instrument_id: int) -> date | None:
    row = conn.execute(
        "SELECT MAX(trade_date) FROM daily_prices WHERE instrument_id = %s",
        (instrument_id,),
    ).fetchone()
    return row[0] if row and row[0] else None


def _instruments_for_market(conn: psycopg.Connection, market_key: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT instrument_id, symbol, currency_code
        FROM instruments
        WHERE market_key = %s AND is_active = TRUE
        ORDER BY symbol
        """,
        (home_market_key(market_key),),
    ).fetchall()
    return [{"instrument_id": row[0], "symbol": str(row[1]), "currency_code": row[2]} for row in rows]


def _active_instrument_count(conn: psycopg.Connection, market_key: str) -> int:
    row = conn.execute(
        """
        SELECT COUNT(*)
        FROM instruments
        WHERE market_key = %s AND is_active = TRUE
        """,
        (home_market_key(market_key),),
    ).fetchone()
    return int(row[0] or 0)


def _instruments_needing_prices(
    conn: psycopg.Connection,
    market_key: str,
    target_date: date,
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT i.instrument_id, i.symbol, i.currency_code, MAX(dp.trade_date) AS last_price_date
        FROM instruments i
        LEFT JOIN daily_prices dp
          ON dp.instrument_id = i.instrument_id
        WHERE i.market_key = %s AND i.is_active = TRUE
        GROUP BY i.instrument_id, i.symbol, i.currency_code
        HAVING MAX(dp.trade_date) IS NULL OR MAX(dp.trade_date) < %s
        ORDER BY i.symbol
        """,
        (home_market_key(market_key), target_date),
    ).fetchall()
    return [
        {
            "instrument_id": row[0],
            "symbol": str(row[1]),
            "currency_code": row[2],
            "last_price_date": row[3],
        }
        for row in rows
    ]


def _instruments_without_prices(conn: psycopg.Connection, market_key: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT i.instrument_id, i.symbol, i.currency_code
        FROM instruments i
        LEFT JOIN daily_prices dp ON dp.instrument_id = i.instrument_id
        WHERE i.market_key = %s AND i.is_active = TRUE AND dp.instrument_id IS NULL
        ORDER BY i.symbol
        """,
        (home_market_key(market_key),),
    ).fetchall()
    return [{"instrument_id": row[0], "symbol": str(row[1]), "currency_code": row[2]} for row in rows]


def _instruments_by_symbols(
    conn: psycopg.Connection, market_key: str, symbols: list[str]
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT instrument_id, symbol, currency_code
        FROM instruments
        WHERE market_key = %s AND is_active = TRUE AND symbol = ANY(%s)
        ORDER BY symbol
        """,
        (home_market_key(market_key), symbols),
    ).fetchall()
    return [{"instrument_id": row[0], "symbol": str(row[1]), "currency_code": row[2]} for row in rows]


# ── collection_runs 헬퍼 ──────────────────────────────────────────────────────

def _create_prices_run(
    conn: psycopg.Connection,
    market_key: str,
    run_type: str,
    trade_date: date,
    requested_count: int,
    source_provider: str,
    params: dict[str, Any] | None = None,
) -> str:
    result = conn.execute(
        """
        INSERT INTO collection_runs (
            run_type, market_key, trade_date, source_provider, status, requested_count, params
        )
        VALUES (%s, %s, %s, %s, 'running', %s, %s)
        RETURNING run_id
        """,
        (
            run_type,
            home_market_key(market_key),
            trade_date,
            source_provider,
            requested_count,
            Jsonb(params or {}),
        ),
    ).fetchone()
    return str(result[0])


def _finish_prices_run(
    conn: psycopg.Connection,
    run_id: str,
    status: str,
    success_count: int,
    failed_count: int = 0,
    skipped_count: int = 0,
    error_samples: list[Any] | None = None,
) -> None:
    conn.execute(
        """
        UPDATE collection_runs
        SET status = %s, finished_at = now(),
            success_count = %s, failed_count = %s, skipped_count = %s,
            error_samples = %s
        WHERE run_id = %s
        """,
        (status, success_count, failed_count, skipped_count, Jsonb(error_samples or []), run_id),
    )


# ── 날짜 헬퍼 ─────────────────────────────────────────────────────────────────

def _start_for_years(years: int) -> str:
    return (date.today() - timedelta(days=years * 365 + 30)).isoformat()


def _next_day(d: date) -> date:
    return d + timedelta(days=1)


def _default_target_date(market_key: str) -> date:
    today = date.today()
    if _is_korea(market_key):
        return today
    return today - timedelta(days=1)


# ── DataFrame → daily_prices upsert ──────────────────────────────────────────

def _upsert_ohlcv_frame(
    conn: psycopg.Connection,
    instrument_id: int,
    frame: pd.DataFrame,
    source_provider: str,
    run_id: str,
    currency_code: str | None,
) -> int:
    count = 0
    for ts, row in frame.iterrows():
        trade_date = ts.date() if hasattr(ts, "date") else ts
        price_row = pd.Series({
            "open": row.get("Open"),
            "high": row.get("High"),
            "low": row.get("Low"),
            "close": row.get("Close"),
            "volume": row.get("Volume"),
        })
        upsert_daily_price(conn, instrument_id, trade_date, source_provider, price_row, run_id, currency_code)
        count += 1
    return count


def _fetch_task(instr: dict[str, Any], market_key: str, start: str, end: str) -> dict[str, Any]:
    frame, source = fetch_ohlcv(instr["symbol"], market_key, start, end)
    return {
        "instrument": instr,
        "start": start,
        "frame": frame,
        "source": source,
    }


# ── fetch (증분) ──────────────────────────────────────────────────────────────

def run_fetch(
    market_key: str,
    date_str: str | None = None,
    explicit_url: str | None = None,
    limit: int | None = None,
    workers: int = _DEFAULT_FETCH_WORKERS,
) -> None:
    target_date = _default_target_date(market_key) if not date_str else datetime.strptime(date_str, "%Y%m%d").date()
    end = _next_day(target_date).isoformat()
    _, currency_code, _ = country_currency_for_market(market_key)
    primary_source = "fdr" if _uses_fdr_primary(market_key) else "yfinance"

    with connect(explicit_url) as conn:
        active_count = _active_instrument_count(conn, market_key)
        instruments = _instruments_needing_prices(conn, market_key, target_date)
        skipped = max(0, active_count - len(instruments))
        if limit:
            instruments = instruments[:limit]
        if not instruments:
            print(f"  prices fetch [{market_key}]: all active instruments already have prices through {target_date.isoformat()}")
            return

        run_id = _create_prices_run(
            conn, market_key, "prices", target_date, len(instruments), primary_source,
            params={"mode": "incremental", "target_date": target_date.isoformat(), "fetch_end": end},
        )
        worker_count = max(1, min(workers, len(instruments)))
        print(
            f"  prices fetch [{market_key}] {len(instruments)} symbols → {target_date.isoformat()}  "
            f"workers={worker_count}  run_id={run_id}"
        )

        success, failed = 0, 0
        error_samples: list[Any] = []

        tasks: list[tuple[dict[str, Any], str]] = []
        for instr in instruments:
            instrument_id = instr["instrument_id"]
            last = instr.get("last_price_date") or _last_price_date_any_source(conn, instrument_id)
            start = _next_day(last).isoformat() if last else _start_for_years(_DEFAULT_HISTORY_YEARS)
            tasks.append((instr, start))

        def handle_result(result: dict[str, Any]) -> None:
            nonlocal success, failed
            instr = result["instrument"]
            instrument_id = instr["instrument_id"]
            symbol = instr["symbol"]
            instr_currency = instr["currency_code"] or currency_code
            start = result["start"]
            frame = result["frame"]
            source = result["source"]
            if frame.empty:
                failed += 1
                print(f"    failed {symbol}: no price data ({start} -> {end})")
                if len(error_samples) < 30:
                    error_samples.append({"symbol": symbol, "reason": "fetch_failed", "start": start})
                return

            _upsert_ohlcv_frame(conn, instrument_id, frame, source, run_id, instr_currency)
            success += 1
            if success % 100 == 0:
                print(f"    {success}/{len(instruments)} ...")

        if worker_count == 1:
            for instr, start in tasks:
                handle_result(_fetch_task(instr, market_key, start, end))
        else:
            with ThreadPoolExecutor(max_workers=worker_count) as executor:
                futures = {
                    executor.submit(_fetch_task, instr, market_key, start, end): (instr, start)
                    for instr, start in tasks
                }
                for future in as_completed(futures):
                    try:
                        handle_result(future.result())
                    except Exception as exc:
                        instr, start = futures[future]
                        symbol = instr["symbol"]
                        failed += 1
                        print(f"    failed {symbol}: {type(exc).__name__} ({start} -> {end})")
                        if len(error_samples) < 30:
                            error_samples.append({"symbol": symbol, "reason": type(exc).__name__, "start": start})

        status = "success" if not failed else ("partial" if success else "failed")
        _finish_prices_run(conn, run_id, status, success, failed, skipped, error_samples)
        print(
            f"  prices fetch [{market_key}] done: "
            f"success={success} failed={failed} skipped={skipped} status={status}"
        )


# ── backfill ──────────────────────────────────────────────────────────────────

def run_backfill(
    market_key: str,
    years: int = _DEFAULT_HISTORY_YEARS,
    new_only: bool = False,
    symbols: list[str] | None = None,
    explicit_url: str | None = None,
    limit: int | None = None,
) -> None:
    start = _start_for_years(years)
    end = date.today().isoformat()
    _, currency_code, _ = country_currency_for_market(market_key)
    primary_source = "fdr" if _uses_fdr_primary(market_key) else "yfinance"

    with connect(explicit_url) as conn:
        if symbols:
            instruments = _instruments_by_symbols(conn, market_key, symbols)
        elif new_only:
            instruments = _instruments_without_prices(conn, market_key)
        else:
            instruments = _instruments_for_market(conn, market_key)

        if limit:
            instruments = instruments[:limit]

        if not instruments:
            print(f"  prices backfill [{market_key}]: no target instruments")
            return

        mode = "backfill_new" if new_only else "backfill_all"
        run_id = _create_prices_run(
            conn, market_key, "backfill", date.today(), len(instruments), primary_source,
            params={"mode": mode, "years": years, "start": start, "end": end},
        )
        print(
            f"  prices backfill [{market_key}] {len(instruments)} symbols  "
            f"{start} ~ {end}  run_id={run_id}"
        )

        success, failed = 0, 0
        error_samples: list[Any] = []

        for instr in instruments:
            instrument_id = instr["instrument_id"]
            symbol = instr["symbol"]
            instr_currency = instr["currency_code"] or currency_code

            frame, source = fetch_ohlcv(symbol, market_key, start, end)
            if frame.empty:
                failed += 1
                if len(error_samples) < 30:
                    error_samples.append({"symbol": symbol, "reason": "fetch_failed"})
                continue

            _upsert_ohlcv_frame(conn, instrument_id, frame, source, run_id, instr_currency)
            success += 1
            if success % 50 == 0:
                print(f"    {success}/{len(instruments)} backfilled ...")

        status = "success" if not failed else ("partial" if success else "failed")
        _finish_prices_run(conn, run_id, status, success, failed, 0, error_samples)
        print(
            f"  prices backfill [{market_key}] done: "
            f"success={success} failed={failed} status={status}"
        )


# ── retry ─────────────────────────────────────────────────────────────────────

def run_retry(
    market_key: str,
    run_id: str | None = None,
    explicit_url: str | None = None,
) -> None:
    with connect(explicit_url) as conn:
        if run_id:
            row = conn.execute(
                "SELECT error_samples FROM collection_runs WHERE run_id = %s",
                (run_id,),
            ).fetchone()
        else:
            row = conn.execute(
                """
                SELECT error_samples FROM collection_runs
                WHERE market_key = %s AND run_type IN ('prices', 'backfill')
                  AND status IN ('failed', 'partial')
                ORDER BY started_at DESC
                LIMIT 1
                """,
                (home_market_key(market_key),),
            ).fetchone()

    if not row or not row[0]:
        print(f"  prices retry [{market_key}]: no failed run found")
        return

    symbols = [s["symbol"] for s in row[0] if isinstance(s, dict) and "symbol" in s]
    if not symbols:
        print(f"  prices retry [{market_key}]: no symbols in error_samples")
        return

    print(f"  prices retry [{market_key}]: retrying {len(symbols)} symbols")
    run_backfill(market_key, years=_DEFAULT_HISTORY_YEARS, symbols=symbols, explicit_url=explicit_url)


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Daily OHLCV price collector.")
    parser.add_argument("--database-url", default=None)
    sub = parser.add_subparsers(dest="command", required=True)

    fetch_p = sub.add_parser("fetch", help="Incremental daily price fetch.")
    fetch_p.add_argument("--market", required=True, choices=sorted(MARKETS))
    fetch_p.add_argument("--date", default=None, help="Target date YYYYMMDD (default: today).")
    fetch_p.add_argument("--limit", type=int, default=None)
    fetch_p.add_argument("--workers", type=int, default=_DEFAULT_FETCH_WORKERS)

    backfill_p = sub.add_parser("backfill", help="Bulk historical price backfill.")
    backfill_p.add_argument("--market", required=True, choices=sorted(MARKETS))
    backfill_p.add_argument("--years", type=int, default=_DEFAULT_HISTORY_YEARS)
    backfill_p.add_argument(
        "--new-only", action="store_true",
        help="daily_prices가 없는 신규 종목만 대상으로 합니다.",
    )
    backfill_p.add_argument("--limit", type=int, default=None)

    retry_p = sub.add_parser("retry", help="Retry failed symbols from the last prices/backfill run.")
    retry_p.add_argument("--market", required=True, choices=sorted(MARKETS))
    retry_p.add_argument("--run-id", default=None, help="Specific run_id to retry.")

    args = parser.parse_args()

    if args.command == "fetch":
        run_fetch(args.market, args.date, args.database_url, args.limit, args.workers)
    elif args.command == "backfill":
        run_backfill(args.market, args.years, args.new_only, explicit_url=args.database_url, limit=args.limit)
    elif args.command == "retry":
        run_retry(args.market, args.run_id, args.database_url)


if __name__ == "__main__":
    main()
