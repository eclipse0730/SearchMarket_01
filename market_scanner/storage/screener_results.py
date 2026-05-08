from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd
import psycopg
from psycopg.types.json import Jsonb

from market_scanner.domain.market_policy import home_market_key
from market_scanner.storage.common import clean_number, row_payload


def upsert_scan_result(
    conn: psycopg.Connection,
    run_id: str,
    instrument_id: int,
    market_key: str,
    universe_key: str,
    trade_date: date,
    row: pd.Series,
    rank_no: int,
) -> None:
    conn.execute(
        """
        INSERT INTO scan_results (
            run_id, instrument_id, market_key, universe_key, trade_date,
            chart_score, technical_score, fundamental_score, theme_score, flow_score,
            composite_score, rank_no, setup_tags, risk_flags, summary_payload
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, ARRAY[]::TEXT[], ARRAY[]::TEXT[], %s)
        ON CONFLICT (run_id, instrument_id) DO UPDATE SET
            chart_score = EXCLUDED.chart_score,
            technical_score = EXCLUDED.technical_score,
            fundamental_score = EXCLUDED.fundamental_score,
            theme_score = EXCLUDED.theme_score,
            flow_score = EXCLUDED.flow_score,
            composite_score = EXCLUDED.composite_score,
            rank_no = EXCLUDED.rank_no,
            summary_payload = EXCLUDED.summary_payload
        """,
        (
            run_id,
            instrument_id,
            home_market_key(market_key),
            universe_key,
            trade_date,
            clean_number(row.get("chart_score")),
            clean_number(row.get("technical_score")),
            clean_number(row.get("fundamental_score")),
            clean_number(row.get("theme_score")),
            clean_number(row.get("flow_score")),
            clean_number(row.get("composite_score")),
            rank_no,
            Jsonb(
                row_payload(
                    row,
                    ["symbol", "name_local", "sector", "change_pct", "candle_type", "trend", "composite_score"],
                )
            ),
        ),
    )


def upsert_market_snapshot(
    conn: psycopg.Connection,
    market_key: str,
    universe_key: str,
    trade_date: date,
    snapshot: dict[str, Any],
    run_id: str,
) -> None:
    conn.execute(
        """
        INSERT INTO market_snapshots (
            market_key, universe_key, trade_date, run_id, total_count, scanned_count,
            success_count, failed_count, advance_count, decline_count, unchanged_count,
            avg_change_pct, median_change_pct, avg_rsi14, bullish_breadth_pct,
            avg_composite_score, market_score, regime, risk_level, macro_payload
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, 0, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (market_key, trade_date, universe_key) DO UPDATE SET
            run_id = EXCLUDED.run_id,
            total_count = EXCLUDED.total_count,
            scanned_count = EXCLUDED.scanned_count,
            success_count = EXCLUDED.success_count,
            advance_count = EXCLUDED.advance_count,
            decline_count = EXCLUDED.decline_count,
            unchanged_count = EXCLUDED.unchanged_count,
            avg_change_pct = EXCLUDED.avg_change_pct,
            median_change_pct = EXCLUDED.median_change_pct,
            avg_rsi14 = EXCLUDED.avg_rsi14,
            bullish_breadth_pct = EXCLUDED.bullish_breadth_pct,
            avg_composite_score = EXCLUDED.avg_composite_score,
            market_score = EXCLUDED.market_score,
            regime = EXCLUDED.regime,
            risk_level = EXCLUDED.risk_level,
            macro_payload = EXCLUDED.macro_payload,
            created_at = now()
        """,
        (
            home_market_key(market_key),
            universe_key,
            trade_date,
            run_id,
            snapshot["total_count"],
            snapshot["scanned_count"],
            snapshot["success_count"],
            snapshot["advance_count"],
            snapshot["decline_count"],
            snapshot["unchanged_count"],
            snapshot["avg_change_pct"],
            snapshot["median_change_pct"],
            snapshot["avg_rsi14"],
            snapshot["bullish_breadth_pct"],
            snapshot["avg_composite_score"],
            snapshot["market_score"],
            snapshot["regime"],
            snapshot["risk_level"],
            Jsonb(snapshot["macro_payload"]),
        ),
    )


def upsert_sector_snapshots(
    conn: psycopg.Connection,
    market_key: str,
    universe_key: str,
    trade_date: date,
    snapshots: list[dict[str, Any]],
    run_id: str,
) -> None:
    for snapshot in snapshots:
        conn.execute(
            """
            INSERT INTO sector_snapshots (
                market_key, universe_key, trade_date, sector, run_id, instrument_count,
                advance_count, decline_count, avg_change_pct, median_change_pct,
                avg_rsi14, avg_composite_score, top_instruments
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (market_key, trade_date, universe_key, sector) DO UPDATE SET
                run_id = EXCLUDED.run_id,
                instrument_count = EXCLUDED.instrument_count,
                advance_count = EXCLUDED.advance_count,
                decline_count = EXCLUDED.decline_count,
                avg_change_pct = EXCLUDED.avg_change_pct,
                median_change_pct = EXCLUDED.median_change_pct,
                avg_rsi14 = EXCLUDED.avg_rsi14,
                avg_composite_score = EXCLUDED.avg_composite_score,
                top_instruments = EXCLUDED.top_instruments,
                created_at = now()
            """,
            (
                home_market_key(market_key),
                universe_key,
                trade_date,
                snapshot["sector"],
                run_id,
                snapshot["instrument_count"],
                snapshot["advance_count"],
                snapshot["decline_count"],
                snapshot["avg_change_pct"],
                snapshot["median_change_pct"],
                snapshot["avg_rsi14"],
                snapshot["avg_composite_score"],
                Jsonb(snapshot["top_instruments"]),
            ),
        )
