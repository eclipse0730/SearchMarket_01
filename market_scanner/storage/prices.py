from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd
import psycopg
from psycopg.types.json import Jsonb

from market_scanner.domain.market_policy import home_market_key
from market_scanner.storage.common import clean_int, clean_number, row_payload


def last_price_date(conn: psycopg.Connection, instrument_id: int, source_provider: str) -> date | None:
    row = conn.execute(
        "SELECT MAX(trade_date) FROM daily_prices WHERE instrument_id = %s AND source_provider = %s",
        (instrument_id, source_provider),
    ).fetchone()
    return row[0] if row and row[0] else None


def last_price_date_any_source(conn: psycopg.Connection, instrument_id: int) -> date | None:
    row = conn.execute(
        "SELECT MAX(trade_date) FROM daily_prices WHERE instrument_id = %s",
        (instrument_id,),
    ).fetchone()
    return row[0] if row and row[0] else None


def active_instrument_count(conn: psycopg.Connection, market_key: str) -> int:
    row = conn.execute(
        "SELECT COUNT(*) FROM instruments WHERE market_key = %s AND is_active = TRUE",
        (home_market_key(market_key),),
    ).fetchone()
    return int(row[0] or 0)


def instruments_for_market(conn: psycopg.Connection, market_key: str) -> list[dict[str, Any]]:
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


def instruments_needing_prices(
    conn: psycopg.Connection,
    market_key: str,
    target_date: date,
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT i.instrument_id, i.symbol, i.currency_code, MAX(dp.trade_date) AS last_price_date
        FROM instruments i
        LEFT JOIN daily_prices dp ON dp.instrument_id = i.instrument_id
        WHERE i.market_key = %s AND i.is_active = TRUE
        GROUP BY i.instrument_id, i.symbol, i.currency_code
        HAVING MAX(dp.trade_date) IS NULL OR MAX(dp.trade_date) < %s
        ORDER BY i.symbol
        """,
        (home_market_key(market_key), target_date),
    ).fetchall()
    return [
        {"instrument_id": row[0], "symbol": str(row[1]), "currency_code": row[2], "last_price_date": row[3]}
        for row in rows
    ]


def instruments_by_symbols(
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


def upsert_daily_price(
    conn: psycopg.Connection,
    instrument_id: int,
    trade_date: date,
    source_provider: str,
    row: pd.Series,
    run_id: str,
    currency_code: str | None,
) -> None:
    close_price = clean_number(row.get("close")) or clean_number(row.get("price"))
    if close_price is None:
        return
    conn.execute(
        """
        INSERT INTO daily_prices (
            instrument_id, trade_date, source_provider, open_price, high_price, low_price,
            close_price, adj_close_price, volume, currency_code, is_adjusted, run_id, raw_payload
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, NULL, %s, %s, FALSE, %s, %s)
        ON CONFLICT (instrument_id, trade_date, source_provider) DO UPDATE SET
            open_price = EXCLUDED.open_price,
            high_price = EXCLUDED.high_price,
            low_price = EXCLUDED.low_price,
            close_price = EXCLUDED.close_price,
            volume = EXCLUDED.volume,
            currency_code = EXCLUDED.currency_code,
            run_id = EXCLUDED.run_id,
            raw_payload = EXCLUDED.raw_payload,
            collected_at = now()
        """,
        (
            instrument_id,
            trade_date,
            source_provider,
            clean_number(row.get("open")),
            clean_number(row.get("high")),
            clean_number(row.get("low")),
            close_price,
            clean_int(row.get("volume")),
            currency_code,
            run_id,
            Jsonb(row_payload(row, ["open", "high", "low", "close", "price", "prev_close", "volume"])),
        ),
    )
