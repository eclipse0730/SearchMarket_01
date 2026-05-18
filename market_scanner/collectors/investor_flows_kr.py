from __future__ import annotations

import os
from datetime import date, datetime
from typing import Any

import pandas as pd
import psycopg
from psycopg.types.json import Jsonb

from market_scanner.progress import progress_line
from market_scanner.storage.connection import connect
from market_scanner.storage.investor_flows import (
    SOURCE_PROVIDER,
    ensure_investor_flow_schema,
    existing_flow_symbols,
    upsert_daily_investor_flow,
)
from market_scanner.storage.runs import finish_run


_INVESTOR_COLUMN_MAP = {
    "개인": "individual",
    "외국인합계": "foreign",
    "외국인": "foreign",
    "기관합계": "institution",
}
_FLOW_KIND_MAP = {
    "매수": "buy",
    "매도": "sell",
    "순매수": "net_buy",
}
_MAX_ERROR_SAMPLES = 30


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


def _krx_market_key(market_key: str) -> str:
    if market_key == "kospi":
        return "KOSPI"
    if market_key == "kosdaq":
        return "KOSDAQ"
    raise ValueError("investor flows are supported for kospi and kosdaq only")


def _pykrx_symbol(symbol: str) -> str:
    return symbol.replace(".KS", "").replace(".KQ", "").zfill(6)


def _normalize_flow_frame(frame: pd.DataFrame, suffix: str) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()
    normalized = pd.DataFrame(index=pd.to_datetime(frame.index).date)
    for source_column, investor_key in _INVESTOR_COLUMN_MAP.items():
        if source_column in frame.columns:
            normalized[f"{investor_key}_{suffix}"] = pd.to_numeric(frame[source_column], errors="coerce")
    return normalized


def _fetch_kind(symbol: str, start: str, end: str, on: str, *, volume: bool) -> pd.DataFrame:
    from pykrx import stock

    if volume:
        return stock.get_market_trading_volume_by_date(start, end, symbol, on=on)
    return stock.get_market_trading_value_by_date(start, end, symbol, on=on)


def _create_investor_flow_run(
    conn: psycopg.Connection,
    market_key: str,
    trade_date: date,
    requested_count: int,
    params: dict[str, Any],
) -> str:
    result = conn.execute(
        """
        INSERT INTO collection_runs (
            run_type, market_key, trade_date, source_provider, status, requested_count, params
        )
        VALUES ('investor_flows', %s, %s, %s, 'running', %s, %s)
        RETURNING run_id
        """,
        (market_key, trade_date, SOURCE_PROVIDER, requested_count, Jsonb(params)),
    ).fetchone()
    return str(result[0])


def fetch_investor_flows(symbol: str, start: date, end: date, *, include_volume: bool = False) -> pd.DataFrame:
    start_str = start.strftime("%Y%m%d")
    end_str = end.strftime("%Y%m%d")
    krx_symbol = _pykrx_symbol(symbol)

    frames: list[pd.DataFrame] = []
    for on, suffix in _FLOW_KIND_MAP.items():
        frames.append(_normalize_flow_frame(_fetch_kind(krx_symbol, start_str, end_str, on, volume=False), f"{suffix}_value"))
    if include_volume:
        for on, suffix in _FLOW_KIND_MAP.items():
            frames.append(_normalize_flow_frame(_fetch_kind(krx_symbol, start_str, end_str, on, volume=True), f"{suffix}_volume"))

    valid_frames = [frame for frame in frames if not frame.empty]
    if not valid_frames:
        return pd.DataFrame()
    return pd.concat(valid_frames, axis=1).sort_index()


def _load_instruments(
    conn: psycopg.Connection,
    market_key: str,
    end_date: date,
    *,
    limit: int | None,
    force: bool,
    symbols: list[str] | None,
) -> tuple[list[dict[str, Any]], int, int]:
    params: list[Any] = [market_key]
    symbol_filter = ""
    if symbols:
        symbol_filter = "AND symbol = ANY(%s)"
        params.append(symbols)
    rows = conn.execute(
        f"""
        SELECT instrument_id, symbol
        FROM instruments
        WHERE market_key = %s
          AND is_active = TRUE
          {symbol_filter}
        ORDER BY symbol
        """,
        params,
    ).fetchall()
    all_instruments = [{"instrument_id": row[0], "symbol": str(row[1])} for row in rows]
    if force:
        instruments = all_instruments
        skipped = 0
    else:
        done_symbols = existing_flow_symbols(conn, market_key, end_date)
        instruments = [instr for instr in all_instruments if instr["symbol"] not in done_symbols]
        skipped = max(0, len(all_instruments) - len(instruments))
    return (instruments[:limit] if limit else instruments), len(all_instruments), skipped


def _run_fetch_single_market(
    market_key: str,
    date_str: str | None,
    database_url: str | None,
    limit: int | None,
    date_from: str | None,
    date_to: str | None,
    force: bool,
    symbols: list[str] | None,
    include_volume: bool,
) -> None:
    _krx_market_key(market_key)
    start_date, end_date = _resolve_date_range(date_str, date_from, date_to)

    with connect(database_url) as conn:
        ensure_investor_flow_schema(conn)
        if not os.getenv("KRX_ID") or not os.getenv("KRX_PW"):
            print("  investor flows: KRX_ID/KRX_PW is not set. pykrx may return empty data for KRX-authenticated APIs.")
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
                print(f"  investor flows [{market_key}]: no active instruments found. Run refresh first.")
                return
            print(f"  investor flows [{market_key}]: all active instruments already have flows through {end_date.isoformat()}")
            return

        run_id = _create_investor_flow_run(
            conn,
            market_key,
            end_date,
            len(instruments),
            {
                "mode": "fetch",
                "from": start_date.isoformat(),
                "to": end_date.isoformat(),
                "force": force,
                "include_volume": include_volume,
                "source": SOURCE_PROVIDER,
            },
        )
        print(
            f"  investor flows [{market_key}] {len(instruments)} symbols  "
            f"{start_date.isoformat()} ~ {end_date.isoformat()}  source={SOURCE_PROVIDER}  run_id={run_id}"
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
            symbol = instr["symbol"]
            reason = "fetch_empty"
            try:
                frame = fetch_investor_flows(symbol, start_date, end_date, include_volume=include_volume)
            except Exception as exc:
                frame = pd.DataFrame()
                reason = type(exc).__name__

            if frame.empty:
                failed += 1
                if len(error_samples) < _MAX_ERROR_SAMPLES:
                    error_samples.append({
                        "symbol": symbol,
                        "reason": reason,
                        "from": start_date.isoformat(),
                        "to": end_date.isoformat(),
                    })
                processed += 1
                print_progress()
                continue

            for flow_date, row in frame.iterrows():
                upsert_daily_investor_flow(conn, instr["instrument_id"], flow_date, row, run_id, include_volume=include_volume)
                stored_rows += 1
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
            f"  investor flows [{market_key}] done: "
            f"success={success} failed={failed} skipped={skipped} stored_rows={stored_rows} status={status}"
        )


def run_fetch(
    market_key: str,
    date_str: str | None = None,
    database_url: str | None = None,
    limit: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    force: bool = False,
    symbols: list[str] | None = None,
    include_volume: bool = False,
) -> None:
    if market_key == "kr":
        for child_market in ["kospi", "kosdaq"]:
            _run_fetch_single_market(
                child_market,
                date_str,
                database_url,
                limit,
                date_from,
                date_to,
                force,
                symbols,
                include_volume,
            )
        return

    _run_fetch_single_market(
        market_key,
        date_str,
        database_url,
        limit,
        date_from,
        date_to,
        force,
        symbols,
        include_volume,
    )
