from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout
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

_DEFAULT_FETCH_WORKERS = 1
_MAX_FETCH_WORKERS = 8
_BATCH_SIZE = 100
_REQUEST_TIMEOUT = 20
_PRIMARY_SOURCE = "yfinance"


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


def fetch_ohlcv(
    symbol: str,
    start: str,
    end: str,
) -> tuple[pd.DataFrame, str]:
    hist = _fetch_yfinance_batch([symbol], start, end, threads=False).get(symbol, pd.DataFrame())
    if not hist.empty:
        return hist, _PRIMARY_SOURCE
    return pd.DataFrame(), "none"


def _extract_symbol_frame(frame: pd.DataFrame, symbol: str) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()
    if not isinstance(frame.columns, pd.MultiIndex):
        return _normalize_ohlcv(frame)

    for level in range(frame.columns.nlevels):
        values = {str(value).upper(): value for value in frame.columns.get_level_values(level)}
        key = values.get(symbol.upper())
        if key is None:
            continue
        try:
            symbol_frame = frame.xs(key, axis=1, level=level, drop_level=True)
        except (KeyError, ValueError):
            continue
        normalized = _normalize_ohlcv(symbol_frame)
        if not normalized.empty:
            return normalized
    return pd.DataFrame()


def _fetch_yfinance_batch(
    symbols: list[str],
    start: str,
    end: str,
    *,
    threads: bool | int,
) -> dict[str, pd.DataFrame]:
    try:
        import yfinance as yf
    except ImportError:
        return {}

    try:
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            hist = yf.download(
                tickers=symbols,
                start=start,
                end=end,
                auto_adjust=True,
                group_by="ticker",
                progress=False,
                threads=threads,
                timeout=_REQUEST_TIMEOUT,
            )
    except Exception:
        return {symbol: pd.DataFrame() for symbol in symbols}
    return {symbol: _extract_symbol_frame(hist, symbol) for symbol in symbols}


def _next_day(d: date) -> date:
    return d + timedelta(days=1)


def _parse_date_arg(value: str | None) -> date | None:
    return datetime.strptime(value, "%Y%m%d").date() if value else None


def _default_target_date() -> date:
    return date.today()


def _resolve_date_range(date_from: str | None, date_to: str | None) -> tuple[date, date]:
    end_date = _parse_date_arg(date_to) or _default_target_date()
    start_date = _parse_date_arg(date_from) or end_date
    if start_date > end_date:
        raise ValueError("--from must be earlier than or equal to --to")
    return start_date, end_date


def _fetch_end_for_date(end_date: date) -> str:
    return _next_day(end_date).isoformat()


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


def _chunks(items: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    return [items[index:index + size] for index in range(0, len(items), size)]


def run_fetch(
    market_key: str,
    date_str: str | None = None,
    database_url: str | None = None,
    limit: int | None = None,
    workers: int = _DEFAULT_FETCH_WORKERS,
    date_from: str | None = None,
    date_to: str | None = None,
    force: bool = False,
    symbols: list[str] | None = None,
) -> None:
    if date_str:
        if date_from or date_to:
            raise ValueError("--date cannot be used with --from/--to")
        date_from = date_str
        date_to = date_str
    start_date, end_date = _resolve_date_range(date_from, date_to)
    fetch_end = _fetch_end_for_date(end_date)
    _, currency_code, _ = country_currency_for_market(market_key)

    with connect(database_url) as conn:
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
        if limit:
            instruments = instruments[:limit]
        if not instruments:
            if active_count == 0:
                print(
                    f"  prices fetch [{market_key}]: no active instruments found. "
                    "Run refresh-master for this market first."
                )
                return
            print(f"  prices fetch [{market_key}]: all active instruments already have prices through {end_date.isoformat()}")
            return

        tasks: list[dict[str, Any]] = []
        for instr in instruments:
            last = instr.get("last_price_date")
            task_from = start_date if force or not last else max(_next_day(last), start_date)
            if task_from > end_date:
                skipped += 1
                continue
            tasks.append({
                "instrument": instr,
                "start": task_from.isoformat(),
                "end": fetch_end,
                "from": task_from,
                "to": end_date,
            })

        if not tasks:
            print(f"  prices fetch [{market_key}]: no target instruments")
            return

        run_id = create_collection_run(
            conn, "prices", market_key, end_date, _PRIMARY_SOURCE, len(tasks),
            params={
                "mode": "fetch",
                "from": start_date.isoformat(),
                "to": end_date.isoformat(),
                "fetch_end": fetch_end,
                "force": force,
                "batch_size": _BATCH_SIZE,
                "workers": min(max(1, workers), _MAX_FETCH_WORKERS),
            },
        )
        worker_count = max(1, min(workers, _MAX_FETCH_WORKERS, len(tasks)))
        print(
            f"  prices fetch [{market_key}] {len(tasks)} symbols  "
            f"{start_date.isoformat()} ~ {end_date.isoformat()}  "
            f"batch_size={_BATCH_SIZE}  workers={worker_count}  run_id={run_id}"
        )

        success, failed, submitted, active = 0, 0, 0, 0
        stored_rows = 0
        error_samples: list[Any] = []
        progress_interval = max(1, len(tasks) // 100)

        def print_progress(force_print: bool = False) -> None:
            processed = success + failed
            if not force_print and processed % progress_interval != 0:
                return
            print(
                progress_line(
                    processed,
                    len(tasks),
                    queued=submitted,
                    active=active,
                    success=success,
                    failed=failed,
                    skipped=skipped,
                    stored_rows=stored_rows,
                ),
                end="",
                flush=True,
            )

        def handle_result(task: dict[str, Any], frame: pd.DataFrame) -> None:
            nonlocal success, failed, stored_rows
            instr = task["instrument"]
            if frame.empty:
                failed += 1
                error_samples.append({
                    "symbol": instr["symbol"],
                    "reason": "fetch_failed",
                    "from": task["from"].isoformat(),
                    "to": task["to"].isoformat(),
                })
                print_progress()
                return

            instr_currency = instr["currency_code"] or currency_code
            stored_rows += _upsert_ohlcv_frame(conn, instr["instrument_id"], frame, _PRIMARY_SOURCE, run_id, instr_currency)
            success += 1
            print_progress()

        print_progress(True)
        grouped_tasks: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for task in tasks:
            grouped_tasks.setdefault((task["start"], task["end"]), []).append(task)

        yfinance_threads: bool | int = worker_count if worker_count > 1 else False
        for (batch_start, batch_end), group in grouped_tasks.items():
            for batch in _chunks(group, _BATCH_SIZE):
                symbols_in_batch = [task["instrument"]["symbol"] for task in batch]
                submitted += len(batch)
                active = len(batch)
                print_progress(True)
                frames = _fetch_yfinance_batch(
                    symbols_in_batch,
                    batch_start,
                    batch_end,
                    threads=yfinance_threads,
                )
                active = 0
                for task in batch:
                    symbol = task["instrument"]["symbol"]
                    handle_result(task, frames.get(symbol, pd.DataFrame()))
                print_progress(True)

        print_progress(True)
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
        if error_samples:
            sample_text = ", ".join(f"{sample['symbol']}:{sample['reason']}" for sample in error_samples[:5])
            print(f"  failed samples: {sample_text}")


def run_retry(
    market_key: str,
    run_id: str | None = None,
    database_url: str | None = None,
) -> None:
    with connect(database_url) as conn:
        if run_id:
            samples = run_error_samples(conn, run_id)
        else:
            samples = last_failed_run_error_samples(conn, market_key, ["prices"])

    if not samples:
        print(f"  prices retry [{market_key}]: no failed run found")
        return

    grouped: dict[tuple[date, date], set[str]] = {}
    for sample in samples:
        if not isinstance(sample, dict) or "symbol" not in sample:
            continue
        try:
            start_date = date.fromisoformat(str(sample.get("from") or sample.get("start")))
        except (TypeError, ValueError):
            start_date = date.today()
        try:
            end_date = date.fromisoformat(str(sample.get("to")))
        except (TypeError, ValueError):
            end_date = start_date
        if start_date > end_date:
            start_date, end_date = end_date, start_date
        grouped.setdefault((start_date, end_date), set()).add(str(sample["symbol"]))

    if not grouped:
        print(f"  prices retry [{market_key}]: no symbols in error_samples")
        return

    total = sum(len(symbols) for symbols in grouped.values())
    print(f"  prices retry [{market_key}]: retrying {total} symbols in {len(grouped)} date range(s)")
    for (start_date, end_date), symbols in sorted(grouped.items()):
        run_fetch(
            market_key,
            database_url=database_url,
            workers=1,
            date_from=start_date.strftime("%Y%m%d"),
            date_to=end_date.strftime("%Y%m%d"),
            force=True,
            symbols=sorted(symbols),
        )
