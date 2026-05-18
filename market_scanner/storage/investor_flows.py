from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd
import psycopg
from psycopg.types.json import Jsonb

from market_scanner.storage.common import clean_int, clean_number, row_payload


SOURCE_PROVIDER = "pykrx"


_VALUE_COLUMNS = [
    "individual_buy_value",
    "individual_sell_value",
    "individual_net_buy_value",
    "foreign_buy_value",
    "foreign_sell_value",
    "foreign_net_buy_value",
    "institution_buy_value",
    "institution_sell_value",
    "institution_net_buy_value",
]

_VOLUME_COLUMNS = [
    "individual_buy_volume",
    "individual_sell_volume",
    "individual_net_buy_volume",
    "foreign_buy_volume",
    "foreign_sell_volume",
    "foreign_net_buy_volume",
    "institution_buy_volume",
    "institution_sell_volume",
    "institution_net_buy_volume",
]


def ensure_investor_flow_schema(conn: psycopg.Connection) -> None:
    """Create the flow table and keep existing DB check constraints compatible."""
    conn.execute(
        """
        ALTER TABLE collection_runs
        DROP CONSTRAINT IF EXISTS collection_runs_type_check
        """
    )
    conn.execute(
        """
        ALTER TABLE collection_runs
        ADD CONSTRAINT collection_runs_type_check CHECK (
            run_type IN (
                'universe', 'prices', 'indicators', 'scan', 'news', 'render',
                'backfill', 'fundamentals', 'investor_flows'
            )
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS daily_investor_flows (
            instrument_id BIGINT NOT NULL REFERENCES instruments(instrument_id),
            trade_date DATE NOT NULL,
            source_provider TEXT NOT NULL,
            individual_buy_value NUMERIC(28, 2),
            individual_sell_value NUMERIC(28, 2),
            individual_net_buy_value NUMERIC(28, 2),
            foreign_buy_value NUMERIC(28, 2),
            foreign_sell_value NUMERIC(28, 2),
            foreign_net_buy_value NUMERIC(28, 2),
            institution_buy_value NUMERIC(28, 2),
            institution_sell_value NUMERIC(28, 2),
            institution_net_buy_value NUMERIC(28, 2),
            individual_buy_volume BIGINT,
            individual_sell_volume BIGINT,
            individual_net_buy_volume BIGINT,
            foreign_buy_volume BIGINT,
            foreign_sell_volume BIGINT,
            foreign_net_buy_volume BIGINT,
            institution_buy_volume BIGINT,
            institution_sell_volume BIGINT,
            institution_net_buy_volume BIGINT,
            raw_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            collected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            run_id UUID REFERENCES collection_runs(run_id),
            PRIMARY KEY (instrument_id, trade_date, source_provider)
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_daily_investor_flows_date
            ON daily_investor_flows (trade_date DESC)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_daily_investor_flows_instrument_date
            ON daily_investor_flows (instrument_id, trade_date DESC)
        """
    )


def existing_flow_symbols(conn: psycopg.Connection, market_key: str, trade_date: date) -> set[str]:
    rows = conn.execute(
        """
        SELECT i.symbol
        FROM daily_investor_flows f
        JOIN instruments i ON i.instrument_id = f.instrument_id
        WHERE i.market_key = %s
          AND f.trade_date = %s
          AND f.source_provider = %s
        """,
        (market_key, trade_date, SOURCE_PROVIDER),
    ).fetchall()
    return {str(row[0]) for row in rows}


def upsert_daily_investor_flow(
    conn: psycopg.Connection,
    instrument_id: int,
    trade_date: date,
    row: pd.Series,
    run_id: str,
    *,
    include_volume: bool,
) -> None:
    payload_columns = _VALUE_COLUMNS + (_VOLUME_COLUMNS if include_volume else [])
    conn.execute(
        """
        INSERT INTO daily_investor_flows (
            instrument_id, trade_date, source_provider,
            individual_buy_value, individual_sell_value, individual_net_buy_value,
            foreign_buy_value, foreign_sell_value, foreign_net_buy_value,
            institution_buy_value, institution_sell_value, institution_net_buy_value,
            individual_buy_volume, individual_sell_volume, individual_net_buy_volume,
            foreign_buy_volume, foreign_sell_volume, foreign_net_buy_volume,
            institution_buy_volume, institution_sell_volume, institution_net_buy_volume,
            raw_payload, run_id
        )
        VALUES (
            %s, %s, %s,
            %s, %s, %s,
            %s, %s, %s,
            %s, %s, %s,
            %s, %s, %s,
            %s, %s, %s,
            %s, %s, %s,
            %s, %s
        )
        ON CONFLICT (instrument_id, trade_date, source_provider) DO UPDATE SET
            individual_buy_value = EXCLUDED.individual_buy_value,
            individual_sell_value = EXCLUDED.individual_sell_value,
            individual_net_buy_value = EXCLUDED.individual_net_buy_value,
            foreign_buy_value = EXCLUDED.foreign_buy_value,
            foreign_sell_value = EXCLUDED.foreign_sell_value,
            foreign_net_buy_value = EXCLUDED.foreign_net_buy_value,
            institution_buy_value = EXCLUDED.institution_buy_value,
            institution_sell_value = EXCLUDED.institution_sell_value,
            institution_net_buy_value = EXCLUDED.institution_net_buy_value,
            individual_buy_volume = EXCLUDED.individual_buy_volume,
            individual_sell_volume = EXCLUDED.individual_sell_volume,
            individual_net_buy_volume = EXCLUDED.individual_net_buy_volume,
            foreign_buy_volume = EXCLUDED.foreign_buy_volume,
            foreign_sell_volume = EXCLUDED.foreign_sell_volume,
            foreign_net_buy_volume = EXCLUDED.foreign_net_buy_volume,
            institution_buy_volume = EXCLUDED.institution_buy_volume,
            institution_sell_volume = EXCLUDED.institution_sell_volume,
            institution_net_buy_volume = EXCLUDED.institution_net_buy_volume,
            raw_payload = EXCLUDED.raw_payload,
            run_id = EXCLUDED.run_id,
            collected_at = now()
        """,
        (
            instrument_id,
            trade_date,
            SOURCE_PROVIDER,
            clean_number(row.get("individual_buy_value")),
            clean_number(row.get("individual_sell_value")),
            clean_number(row.get("individual_net_buy_value")),
            clean_number(row.get("foreign_buy_value")),
            clean_number(row.get("foreign_sell_value")),
            clean_number(row.get("foreign_net_buy_value")),
            clean_number(row.get("institution_buy_value")),
            clean_number(row.get("institution_sell_value")),
            clean_number(row.get("institution_net_buy_value")),
            clean_int(row.get("individual_buy_volume")),
            clean_int(row.get("individual_sell_volume")),
            clean_int(row.get("individual_net_buy_volume")),
            clean_int(row.get("foreign_buy_volume")),
            clean_int(row.get("foreign_sell_volume")),
            clean_int(row.get("foreign_net_buy_volume")),
            clean_int(row.get("institution_buy_volume")),
            clean_int(row.get("institution_sell_volume")),
            clean_int(row.get("institution_net_buy_volume")),
            Jsonb(row_payload(row, payload_columns)),
            run_id,
        ),
    )
