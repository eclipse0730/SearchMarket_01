from __future__ import annotations

from datetime import date

import pandas as pd
import psycopg
from psycopg.types.json import Jsonb

from market_scanner.storage.common import clean_number, row_payload


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
