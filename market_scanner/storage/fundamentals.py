from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd
import psycopg
from psycopg.types.json import Jsonb

from market_scanner.domain.market_policy import home_market_key
from market_scanner.storage.common import clean_number, row_payload


def instruments_for_market(conn: psycopg.Connection, market_key: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT instrument_id, symbol
        FROM instruments
        WHERE market_key = %s AND is_active = TRUE
        ORDER BY symbol
        """,
        (home_market_key(market_key),),
    ).fetchall()
    return [{"instrument_id": row[0], "symbol": str(row[1])} for row in rows]


def instruments_stale_fundamentals(
    conn: psycopg.Connection, market_key: str, stale_days: int = 7
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT i.instrument_id, i.symbol
        FROM instruments i
        LEFT JOIN (
            SELECT instrument_id, MAX(as_of_date) AS last_date
            FROM instrument_fundamentals
            GROUP BY instrument_id
        ) f ON f.instrument_id = i.instrument_id
        WHERE i.market_key = %s
          AND i.is_active = TRUE
          AND (f.last_date IS NULL OR f.last_date < CURRENT_DATE - %s)
        ORDER BY i.symbol
        """,
        (home_market_key(market_key), stale_days),
    ).fetchall()
    return [{"instrument_id": row[0], "symbol": str(row[1])} for row in rows]


def upsert_fundamentals(
    conn: psycopg.Connection,
    instrument_id: int,
    trade_date: date,
    source_provider: str,
    row: pd.Series,
    run_id: str,
) -> None:
    conn.execute(
        """
        INSERT INTO instrument_fundamentals (
            instrument_id, as_of_date, source_provider, trailing_pe, price_to_book,
            return_on_equity_pct, revenue_growth_pct, market_cap, target_price,
            shares_outstanding, raw_payload, run_id
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (instrument_id, as_of_date, source_provider) DO UPDATE SET
            trailing_pe = EXCLUDED.trailing_pe,
            price_to_book = EXCLUDED.price_to_book,
            return_on_equity_pct = EXCLUDED.return_on_equity_pct,
            revenue_growth_pct = EXCLUDED.revenue_growth_pct,
            market_cap = EXCLUDED.market_cap,
            target_price = EXCLUDED.target_price,
            shares_outstanding = EXCLUDED.shares_outstanding,
            raw_payload = EXCLUDED.raw_payload,
            run_id = EXCLUDED.run_id,
            collected_at = now()
        """,
        (
            instrument_id,
            trade_date,
            source_provider,
            clean_number(row.get("trailing_pe")),
            clean_number(row.get("price_to_book")),
            clean_number(row.get("return_on_equity")),
            clean_number(row.get("revenue_growth")),
            clean_number(row.get("market_cap")),
            clean_number(row.get("target_price")),
            clean_number(row.get("shares_outstanding")),
            Jsonb(
                row_payload(
                    row,
                    [
                        "trailing_pe",
                        "price_to_book",
                        "return_on_equity",
                        "revenue_growth",
                        "market_cap",
                        "target_price",
                        "shares_outstanding",
                        "raw_sources",
                    ],
                )
            ),
            run_id,
        ),
    )
