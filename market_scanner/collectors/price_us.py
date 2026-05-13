from __future__ import annotations

import io
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from contextlib import redirect_stderr, redirect_stdout
from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd
import psycopg

from market_scanner.domain.market_policy import country_currency_for_market, home_market_key
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

_DEFAULT_FETCH_WORKERS = 8
_REQUEST_TIMEOUT = 2
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
    *,
    allow_fdr_fallback: bool = True,
) -> tuple[pd.DataFrame, str]:
    hist = _fetch_yfinance(symbol, start, end)
    if not hist.empty:
        return hist, "yfinance"
    if allow_fdr_fallback:
        hist = _fetch_fdr_daily(symbol, start, end)
        if not hist.empty:
            return hist, "fdr"
    return pd.DataFrame(), "none"


def _fetch_yfinance(symbol: str, start: str, end: str) -> pd.DataFrame:
    try:
        import yfinance as yf
    except ImportError:
        return pd.DataFrame()

    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        hist = yf.Ticker(symbol).history(
            start=start,
            end=end,
            auto_adjust=True,
            timeout=_REQUEST_TIMEOUT,
        )
    normalized = _normalize_ohlcv(hist)
    return normalized if not normalized.empty else pd.DataFrame()


def _inclusive_end_from_exclusive(end: str) -> str:
    return (date.fromisoformat(end) - timedelta(days=1)).isoformat()


def _fetch_fdr_daily(symbol: str, start: str, end: str) -> pd.DataFrame:
    try:
        import FinanceDataReader as fdr
    except ImportError:
        return pd.DataFrame()

    try:
        inclusive_end = _inclusive_end_from_exclusive(end)
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            hist = fdr.DataReader(symbol, start, inclusive_end)
        normalized = _normalize_ohlcv(hist)
        normalized = normalized.loc[start:inclusive_end]
        return normalized if not normalized.empty else pd.DataFrame()
    except Exception:
        return pd.DataFrame()


def _is_us(market_key: str) -> bool:
    return home_market_key(market_key) == "us"


def _next_day(d: date) -> date:
    return d + timedelta(days=1)


def _parse_date_arg(value: str | None) -> date | None:
    return datetime.strptime(value, "%Y%m%d").date() if value else None


def _default_target_date() -> date:
    return date.today() - timedelta(days=1)


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
) -> None:
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


def run_fetch(
    market_key: str,
    date_str: str | None = None,
    explicit_url: str | None = None,
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

    with connect(explicit_url) as conn:
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
                "workers": workers,
            },
        )
        worker_count = max(1, min(workers, len(tasks)))
        print(
            f"  prices fetch [{market_key}] {len(tasks)} symbols  "
            f"{start_date.isoformat()} ~ {end_date.isoformat()}  "
            f"workers={worker_count}  run_id={run_id}"
        )

        success, failed, submitted = 0, 0, 0
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
                    active=submitted - processed,
                    success=success,
                    failed=failed,
                    skipped=skipped,
                ),
                end="",
                flush=True,
            )

        def fetch_task(task: dict[str, Any]) -> dict[str, Any]:
            frame, source = fetch_ohlcv(
                task["instrument"]["symbol"],
                task["start"],
                task["end"],
                allow_fdr_fallback=_is_us(market_key),
            )
            return {**task, "frame": frame, "source": source}

        def handle_result(result: dict[str, Any]) -> None:
            nonlocal success, failed
            instr = result["instrument"]
            if result["frame"].empty:
                failed += 1
                error_samples.append({
                    "symbol": instr["symbol"],
                    "reason": "fetch_failed",
                    "from": result["from"].isoformat(),
                    "to": result["to"].isoformat(),
                })
                print_progress(True)
                return

            instr_currency = instr["currency_code"] or currency_code
            _upsert_ohlcv_frame(conn, instr["instrument_id"], result["frame"], result["source"], run_id, instr_currency)
            success += 1
            print_progress()

        print_progress(True)
        task_iter = iter(tasks)
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            pending: dict[Any, dict[str, Any]] = {}

            def submit_next() -> bool:
                nonlocal submitted
                try:
                    task = next(task_iter)
                except StopIteration:
                    return False
                pending[executor.submit(fetch_task, task)] = task
                submitted += 1
                return True

            for _ in range(worker_count):
                if not submit_next():
                    break
            print_progress(True)

            while pending:
                done, _ = wait(pending, timeout=1, return_when=FIRST_COMPLETED)
                if not done:
                    print_progress(True)
                    continue
                for future in done:
                    task = pending.pop(future)
                    try:
                        handle_result(future.result(timeout=_REQUEST_TIMEOUT * 2))
                    except Exception as exc:
                        failed += 1
                        error_samples.append({
                            "symbol": task["instrument"]["symbol"],
                            "reason": type(exc).__name__,
                            "from": task["from"].isoformat(),
                            "to": task["to"].isoformat(),
                        })
                        print_progress(True)
                    submit_next()
                    print_progress(True)

        print_progress(True)
        print()
        status = "success" if not failed else ("partial" if success else "failed")
        finish_run(conn, run_id, status=status, success_count=success, failed_count=failed, skipped_count=skipped, error_samples=error_samples)
        print(
            f"  prices fetch [{market_key}] done: "
            f"success={success} failed={failed} skipped={skipped} status={status}"
        )
        if error_samples:
            sample_text = ", ".join(f"{sample['symbol']}:{sample['reason']}" for sample in error_samples[:5])
            print(f"  failed samples: {sample_text}")


def run_retry(
    market_key: str,
    run_id: str | None = None,
    explicit_url: str | None = None,
) -> None:
    with connect(explicit_url) as conn:
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
            explicit_url=explicit_url,
            workers=1,
            date_from=start_date.strftime("%Y%m%d"),
            date_to=end_date.strftime("%Y%m%d"),
            force=True,
            symbols=sorted(symbols),
        )
