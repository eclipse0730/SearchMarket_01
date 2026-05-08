from __future__ import annotations

from datetime import date

import pandas as pd
import psycopg
from psycopg.types.json import Jsonb

from market_scanner.storage.common import clean_int, clean_number, row_payload


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
