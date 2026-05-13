from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd
import psycopg

from market_scanner.domain.market_policy import country_currency_for_market
from market_scanner.progress import progress_line
from market_scanner.storage.connection import connect
from market_scanner.storage.prices import (
    active_instrument_count,
    instruments_by_symbols,
    instruments_for_market,
    instruments_needing_prices,
    upsert_daily_price,
)
from market_scanner.storage.runs import (
    create_collection_run,
    finish_run,
    last_failed_run_error_samples,
    run_error_samples,
)


_SOURCE_PROVIDER = "fdr"
_MAX_ERROR_SAMPLES = 30


def _normalize_ohlcv(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()
    lower_to_cap = {
        "open": "Open",
        "high": "High",
        "low": "Low",
        "close": "Close",
        "volume": "Volume",
    }
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


def _fdr_symbol(symbol: str) -> str:
    return symbol.replace(".KS", "").replace(".KQ", "").zfill(6)


def fetch_ohlcv(symbol: str, start: str, end: str) -> tuple[pd.DataFrame, str]:
    try:
        import FinanceDataReader as fdr
    except ImportError:
        return pd.DataFrame(), "none"

    try:
        hist = fdr.DataReader(_fdr_symbol(symbol), start, end)
    except Exception:
        return pd.DataFrame(), "none"

    normalized = _normalize_ohlcv(hist)
    if normalized.empty:
        return pd.DataFrame(), "none"
    return normalized.loc[start:end], _SOURCE_PROVIDER


def _parse_date_arg(value: str | None) -> date | None:
    return datetime.strptime(value, "%Y%m%d").date() if value else None


def _resolve_date_range(date_str: str | None, date_from: str | None, date_to: str | None) -> tuple[date, date]:
    if date_str:
        if date_from or date_to:
            raise ValueError("--date cannot be used with --from/--to")
        date_from = date_str
        date_to = date_str
    end_date = _parse_date_arg(date_to) or date.today()
    start_date = _parse_date_arg(date_from) or end_date
    if start_date > end_date:
        raise ValueError("--from must be earlier than or equal to --to")
    return start_date, end_date


def _next_day(d: date) -> date:
    return d + timedelta(days=1)


def _load_instruments(
    conn: psycopg.Connection,
    market_key: str,
    end_date: date,
    *,
    limit: int | None,
    force: bool,
    symbols: list[str] | None,
) -> tuple[list[dict[str, Any]], int, int]:
    active_count = active_instrument_count(conn, market_key)
    if symbols:
        instruments = instruments_by_symbols(conn, market_key, symbols)
        skipped = 0
    elif force:
        instruments = instruments_for_market(conn, market_key)
        skipped = 0
    else:
        instruments = instruments_needing_prices(conn, market_key, end_date)
        skipped = max(0, active_count - len(instruments))
    return (instruments[:limit] if limit else instruments), active_count, skipped


def _upsert_ohlcv_frame(
    conn: psycopg.Connection,
    instrument_id: int,
    frame: pd.DataFrame,
    source_provider: str,
    run_id: str,
    currency_code: str | None,
) -> int:
    stored = 0
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
        stored += 1
    return stored


def run_fetch(
    market_key: str,
    date_str: str | None = None,
    database_url: str | None = None,
    limit: int | None = None,
    workers: int = 1,
    date_from: str | None = None,
    date_to: str | None = None,
    force: bool = False,
    symbols: list[str] | None = None,
) -> None:
    del workers
    start_date, end_date = _resolve_date_range(date_str, date_from, date_to)
    _, currency_code, _ = country_currency_for_market(market_key)

    with connect(database_url) as conn:
        instruments, active_count, skipped = _load_instruments(
            conn,
            market_key,
            end_date,
            limit=limit,
            force=force,
            symbols=symbols,
        )
        if not instruments:
            if active_count == 0:
                print(f"  prices fetch [{market_key}]: no active instruments found. Run refresh-master first.")
                return
            print(f"  prices fetch [{market_key}]: all active instruments already have prices through {end_date.isoformat()}")
            return

        run_id = create_collection_run(
            conn,
            "prices",
            market_key,
            end_date,
            _SOURCE_PROVIDER,
            len(instruments),
            params={
                "mode": "fetch",
                "from": start_date.isoformat(),
                "to": end_date.isoformat(),
                "force": force,
                "source": _SOURCE_PROVIDER,
            },
        )
        print(
            f"  prices fetch [{market_key}] {len(instruments)} symbols  "
            f"{start_date.isoformat()} ~ {end_date.isoformat()}  source={_SOURCE_PROVIDER}  run_id={run_id}"
        )

        success = 0
        failed = 0
        processed = 0
        stored_rows = 0
        error_samples: list[dict[str, Any]] = []

        def print_progress() -> None:
            print(
                progress_line(
                    processed,
                    len(instruments),
                    success=success,
                    failed=failed,
                    skipped=skipped,
                    stored_rows=stored_rows,
                ),
                end="",
                flush=True,
            )

        print_progress()
        for instr in instruments:
            last = instr.get("last_price_date")
            task_from = start_date if force or not last else max(_next_day(last), start_date)
            if task_from > end_date:
                skipped += 1
                processed += 1
                print_progress()
                continue

            symbol = instr["symbol"]
            frame, source = fetch_ohlcv(symbol, task_from.isoformat(), end_date.isoformat())
            if frame.empty:
                failed += 1
                if len(error_samples) < _MAX_ERROR_SAMPLES:
                    error_samples.append({
                        "symbol": symbol,
                        "reason": "fetch_failed",
                        "from": task_from.isoformat(),
                        "to": end_date.isoformat(),
                    })
                processed += 1
                print_progress()
                continue

            instr_currency = instr["currency_code"] or currency_code
            stored = _upsert_ohlcv_frame(conn, instr["instrument_id"], frame, source, run_id, instr_currency)
            stored_rows += stored
            success += 1
            processed += 1
            print_progress()

        print()

        status = "success" if not failed else ("partial" if success else "failed")
        finish_run(
            conn,
            run_id,
            status=status,
            success_count=success,
            failed_count=failed,
            skipped_count=skipped,
            params={"stored_rows": stored_rows},
            error_samples=error_samples,
        )
        print(
            f"  prices fetch [{market_key}] done: "
            f"success={success} failed={failed} skipped={skipped} stored_rows={stored_rows} status={status}"
        )


def run_retry(
    market_key: str,
    run_id: str | None = None,
    database_url: str | None = None,
) -> None:
    with connect(database_url) as conn:
        samples = run_error_samples(conn, run_id) if run_id else last_failed_run_error_samples(conn, market_key, ["prices"])

    symbols: set[str] = set()
    date_from: date | None = None
    date_to: date | None = None
    for sample in samples or []:
        if not isinstance(sample, dict) or "symbol" not in sample:
            continue
        symbols.add(str(sample["symbol"]))
        try:
            sample_from = date.fromisoformat(str(sample.get("from") or sample.get("start")))
            sample_to = date.fromisoformat(str(sample.get("to")))
        except (TypeError, ValueError):
            continue
        date_from = sample_from if date_from is None else min(date_from, sample_from)
        date_to = sample_to if date_to is None else max(date_to, sample_to)

    if not symbols:
        print(f"  prices retry [{market_key}]: no symbols in error_samples")
        return

    run_fetch(
        market_key,
        database_url=database_url,
        date_from=(date_from or date.today()).strftime("%Y%m%d"),
        date_to=(date_to or date.today()).strftime("%Y%m%d"),
        force=True,
        symbols=sorted(symbols),
    )
