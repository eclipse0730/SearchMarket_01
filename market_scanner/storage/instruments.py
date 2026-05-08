from __future__ import annotations

import pandas as pd
import psycopg
from psycopg.types.json import Jsonb

from market_scanner.domain.instruments import classify_asset_type, display_symbol_for_row
from market_scanner.domain.market_policy import country_currency_for_market, home_market_key
from market_scanner.models import MarketDefinition
from market_scanner.storage.common import clean_text, row_payload


def upsert_instrument(
    conn: psycopg.Connection,
    market: MarketDefinition,
    row: pd.Series,
    *,
    source_provider: str = "csv",
    source_rank: int = 80,
) -> int:
    symbol = clean_text(row.get("symbol"))
    if not symbol:
        raise ValueError("Missing symbol")
    home_key = home_market_key(market.key)
    country_code, currency_code, _ = country_currency_for_market(market.key)
    asset_type = classify_asset_type(row, market.key)
    raw_metadata = row_payload(
        row,
        ["symbol", "display_symbol", "name_en", "name_local", "sector", "description"],
    )
    result = conn.execute(
        """
        INSERT INTO instruments (
            market_key, symbol, display_symbol, country_code, currency_code, asset_type,
            listing_status, name_en, name_local, sector, description, source_provider,
            source_rank, raw_metadata, is_active
        )
        VALUES (%s, %s, %s, %s, %s, %s, 'active', %s, %s, %s, %s, %s, %s, %s, TRUE)
        ON CONFLICT (market_key, symbol) DO UPDATE SET
            display_symbol = COALESCE(EXCLUDED.display_symbol, instruments.display_symbol),
            country_code = COALESCE(EXCLUDED.country_code, instruments.country_code),
            currency_code = COALESCE(EXCLUDED.currency_code, instruments.currency_code),
            asset_type = EXCLUDED.asset_type,
            name_en = COALESCE(EXCLUDED.name_en, instruments.name_en),
            name_local = COALESCE(EXCLUDED.name_local, instruments.name_local),
            sector = COALESCE(EXCLUDED.sector, instruments.sector),
            description = COALESCE(EXCLUDED.description, instruments.description),
            source_provider = EXCLUDED.source_provider,
            source_rank = EXCLUDED.source_rank,
            raw_metadata = instruments.raw_metadata || EXCLUDED.raw_metadata,
            is_active = TRUE
        RETURNING instrument_id
        """,
        (
            home_key,
            symbol,
            display_symbol_for_row(row, market),
            country_code,
            currency_code,
            asset_type,
            clean_text(row.get("name_en")),
            clean_text(row.get("name_local")),
            clean_text(row.get("sector")),
            clean_text(row.get("description")),
            source_provider,
            source_rank,
            Jsonb(raw_metadata),
        ),
    ).fetchone()
    return int(result[0])

