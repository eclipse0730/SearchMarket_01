from __future__ import annotations

from datetime import date
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from market_scanner.storage.common import clean_number


def last_macro_date(
    conn: psycopg.Connection,
    indicator_code: str,
    source_provider: str,
) -> date | None:
    row = conn.execute(
        """
        SELECT MAX(trade_date)
        FROM daily_macro
        WHERE indicator_code = %s AND source_provider = %s
        """,
        (indicator_code, source_provider),
    ).fetchone()
    return row[0] if row and row[0] else None


def upsert_daily_macro(
    conn: psycopg.Connection,
    indicator_code: str,
    trade_date: date,
    source_provider: str,
    value: Any,
    *,
    prev_value: Any = None,
    change_pct: Any = None,
    raw_payload: dict[str, Any] | None = None,
) -> None:
    clean_value = clean_number(value)
    if clean_value is None:
        return
    conn.execute(
        """
        INSERT INTO daily_macro (
            indicator_code, trade_date, source_provider, value, prev_value,
            change_pct, raw_payload
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (indicator_code, trade_date, source_provider) DO UPDATE SET
            value = EXCLUDED.value,
            prev_value = EXCLUDED.prev_value,
            change_pct = EXCLUDED.change_pct,
            raw_payload = EXCLUDED.raw_payload,
            collected_at = now()
        """,
        (
            indicator_code,
            trade_date,
            source_provider,
            clean_value,
            clean_number(prev_value),
            clean_number(change_pct),
            Jsonb(raw_payload or {}),
        ),
    )
