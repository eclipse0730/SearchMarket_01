from __future__ import annotations

from datetime import date
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from market_scanner.domain.market_policy import home_market_key, price_source_for_market


def create_run(
    conn: psycopg.Connection,
    market_key: str,
    universe_key: str,
    trade_date: date,
    requested_count: int,
) -> str:
    result = conn.execute(
        """
        INSERT INTO collection_runs (
            run_type, market_key, universe_key, trade_date, source_provider, status,
            requested_count, params
        )
        VALUES ('scan', %s, %s, %s, %s, 'running', %s, %s)
        RETURNING run_id
        """,
        (
            home_market_key(market_key),
            universe_key,
            trade_date,
            price_source_for_market(market_key),
            requested_count,
            Jsonb({"loaded_from": "csv", "scan_market_key": market_key}),
        ),
    ).fetchone()
    return str(result[0])


def finish_run(
    conn: psycopg.Connection,
    run_id: str,
    *,
    status: str,
    success_count: int,
    failed_count: int = 0,
    skipped_count: int = 0,
    params: dict[str, Any] | None = None,
    error_samples: list[Any] | None = None,
    notes: str | None = None,
) -> None:
    conn.execute(
        """
        UPDATE collection_runs
        SET status = %s,
            finished_at = now(),
            success_count = %s,
            failed_count = %s,
            skipped_count = %s,
            params = params || %s,
            error_samples = %s,
            notes = COALESCE(%s, notes)
        WHERE run_id = %s
        """,
        (
            status,
            success_count,
            failed_count,
            skipped_count,
            Jsonb(params or {}),
            Jsonb(error_samples or []),
            notes,
            run_id,
        ),
    )


def create_collection_run(
    conn: psycopg.Connection,
    run_type: str,
    market_key: str,
    trade_date: date,
    source_provider: str,
    requested_count: int,
    *,
    universe_key: str | None = None,
    params: dict[str, Any] | None = None,
) -> str:
    result = conn.execute(
        """
        INSERT INTO collection_runs (
            run_type, market_key, universe_key, trade_date, source_provider, status, requested_count, params
        )
        VALUES (%s, %s, %s, %s, %s, 'running', %s, %s)
        RETURNING run_id
        """,
        (
            run_type,
            home_market_key(market_key),
            universe_key,
            trade_date,
            source_provider,
            requested_count,
            Jsonb(params or {}),
        ),
    ).fetchone()
    return str(result[0])


def run_error_samples(conn: psycopg.Connection, run_id: str) -> list[Any] | None:
    row = conn.execute(
        "SELECT error_samples FROM collection_runs WHERE run_id = %s",
        (run_id,),
    ).fetchone()
    return row[0] if row else None


def last_failed_run_error_samples(
    conn: psycopg.Connection,
    market_key: str,
    run_types: list[str],
) -> list[Any] | None:
    row = conn.execute(
        """
        SELECT error_samples FROM collection_runs
        WHERE market_key = %s AND run_type = ANY(%s)
          AND status IN ('failed', 'partial')
        ORDER BY started_at DESC
        LIMIT 1
        """,
        (home_market_key(market_key), run_types),
    ).fetchone()
    return row[0] if row else None


def create_universe_run(
    conn: psycopg.Connection,
    market_key: str,
    universe_key: str,
    trade_date: date,
    requested_count: int,
    *,
    params: dict[str, Any] | None = None,
) -> str:
    run_params = {"loaded_from": "universe_loader", "scan_market_key": market_key}
    if params:
        run_params.update(params)
    result = conn.execute(
        """
        INSERT INTO collection_runs (
            run_type, market_key, universe_key, trade_date, source_provider, status,
            requested_count, params
        )
        VALUES ('universe', %s, %s, %s, 'market_scanner', 'running', %s, %s)
        RETURNING run_id
        """,
        (
            home_market_key(market_key),
            universe_key,
            trade_date,
            requested_count,
            Jsonb(run_params),
        ),
    ).fetchone()
    return str(result[0])
