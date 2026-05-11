from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd
import psycopg
from psycopg.types.json import Jsonb

from market_scanner.domain.market_policy import home_market_key
from market_scanner.storage.common import clean_int, clean_number, clean_text, row_payload


def _tag_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [tag.strip() for tag in value.split(",") if tag.strip()]
    if isinstance(value, (list, tuple, set)):
        return [str(tag).strip() for tag in value if str(tag).strip()]
    return []


def _risk_flags(row: pd.Series) -> list[str]:
    flags = _tag_list(row.get("risk_flags"))
    risk_score = clean_number(row.get("risk_score"))
    overbought_score = clean_number(row.get("overbought_score"))
    if risk_score is not None and risk_score >= 55:
        flags.append("리스크")
    if overbought_score is not None and overbought_score >= 75:
        flags.append("과열주의")
    return list(dict.fromkeys(flags))


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
            composite_score,
            pullback_score, breakout_score, box_breakout_score, trend_quality_score,
            reversal_score, overbought_score, risk_score, raw_composite_score,
            action_score, quality_score, setup_label, pullback_ma_period,
            close_price, change_pct, value_traded, rsi14,
            rank_no, setup_tags, risk_flags, summary_payload
        )
        VALUES (
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s,
            %s,
            %s, %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s, %s, %s
        )
        ON CONFLICT (run_id, instrument_id) DO UPDATE SET
            chart_score = EXCLUDED.chart_score,
            technical_score = EXCLUDED.technical_score,
            fundamental_score = EXCLUDED.fundamental_score,
            theme_score = EXCLUDED.theme_score,
            flow_score = EXCLUDED.flow_score,
            composite_score = EXCLUDED.composite_score,
            pullback_score = EXCLUDED.pullback_score,
            breakout_score = EXCLUDED.breakout_score,
            box_breakout_score = EXCLUDED.box_breakout_score,
            trend_quality_score = EXCLUDED.trend_quality_score,
            reversal_score = EXCLUDED.reversal_score,
            overbought_score = EXCLUDED.overbought_score,
            risk_score = EXCLUDED.risk_score,
            raw_composite_score = EXCLUDED.raw_composite_score,
            action_score = EXCLUDED.action_score,
            quality_score = EXCLUDED.quality_score,
            setup_label = EXCLUDED.setup_label,
            pullback_ma_period = EXCLUDED.pullback_ma_period,
            close_price = EXCLUDED.close_price,
            change_pct = EXCLUDED.change_pct,
            value_traded = EXCLUDED.value_traded,
            rsi14 = EXCLUDED.rsi14,
            rank_no = EXCLUDED.rank_no,
            setup_tags = EXCLUDED.setup_tags,
            risk_flags = EXCLUDED.risk_flags,
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
            clean_number(row.get("pullback_score")),
            clean_number(row.get("breakout_score")),
            clean_number(row.get("box_breakout_score")),
            clean_number(row.get("trend_quality_score")),
            clean_number(row.get("reversal_score")),
            clean_number(row.get("overbought_score")),
            clean_number(row.get("risk_score")),
            clean_number(row.get("raw_composite_score")),
            clean_number(row.get("action_score")),
            clean_number(row.get("quality_score")),
            clean_text(row.get("setup_label")),
            clean_int(row.get("pullback_ma_period")),
            clean_number(row.get("close_price") if row.get("close_price") is not None else row.get("close")),
            clean_number(row.get("change_pct")),
            clean_number(row.get("value_traded")),
            clean_number(row.get("rsi14")),
            rank_no,
            _tag_list(row.get("signal_tags")),
            _risk_flags(row),
            Jsonb(
                row_payload(
                    row,
                    [
                        "symbol", "name_local", "sector", "change_pct", "candle_type", "trend",
                        "composite_score", "raw_composite_score", "setup_label", "signal_tags",
                        "pullback_score", "breakout_score", "box_breakout_score",
                        "trend_quality_score", "reversal_score", "overbought_score",
                        "risk_score", "action_score", "quality_score",
                        "pullback_ma_period",
                    ],
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
