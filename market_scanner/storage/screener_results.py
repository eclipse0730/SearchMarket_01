from __future__ import annotations

from datetime import date

import pandas as pd
import psycopg
from psycopg.types.json import Jsonb

from market_scanner.storage.common import clean_number, home_market_key, row_payload


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
    frame: pd.DataFrame,
    run_id: str,
) -> None:
    change = pd.to_numeric(frame.get("change_pct"), errors="coerce") if "change_pct" in frame else pd.Series(dtype=float)
    rsi = pd.to_numeric(frame.get("rsi"), errors="coerce") if "rsi" in frame else pd.Series(dtype=float)
    score = pd.to_numeric(frame.get("composite_score"), errors="coerce") if "composite_score" in frame else pd.Series(dtype=float)
    market_score = round(float(score.dropna().mean()), 4) if not score.dropna().empty else None
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
            len(frame),
            len(frame),
            len(frame),
            int((change > 0).sum()),
            int((change < 0).sum()),
            int((change == 0).sum()),
            round(float(change.dropna().mean()), 4) if not change.dropna().empty else None,
            round(float(change.dropna().median()), 4) if not change.dropna().empty else None,
            round(float(rsi.dropna().mean()), 4) if not rsi.dropna().empty else None,
            round(float((change > 0).sum() / len(frame) * 100), 4) if len(frame) else None,
            market_score,
            market_score,
            regime_for_score(market_score),
            risk_for_score(market_score),
            Jsonb({}),
        ),
    )


def regime_for_score(score: float | None) -> str | None:
    if score is None:
        return None
    if score >= 65:
        return "bullish"
    if score <= 40:
        return "bearish"
    return "neutral"


def risk_for_score(score: float | None) -> str | None:
    if score is None:
        return None
    if score >= 70:
        return "low"
    if score <= 40:
        return "high"
    return "normal"


def upsert_sector_snapshots(
    conn: psycopg.Connection,
    market_key: str,
    universe_key: str,
    trade_date: date,
    frame: pd.DataFrame,
    run_id: str,
) -> None:
    if "sector" not in frame.columns or frame.empty:
        return
    for sector, group in frame.groupby("sector", dropna=False):
        sector_name = str(sector or "Unknown")
        change = pd.to_numeric(group.get("change_pct"), errors="coerce") if "change_pct" in group else pd.Series(dtype=float)
        rsi = pd.to_numeric(group.get("rsi"), errors="coerce") if "rsi" in group else pd.Series(dtype=float)
        score = pd.to_numeric(group.get("composite_score"), errors="coerce") if "composite_score" in group else pd.Series(dtype=float)
        top = (
            group.sort_values("composite_score", ascending=False)
            .head(5)[["symbol", "name_local", "composite_score"]]
            .to_dict(orient="records")
            if "composite_score" in group
            else []
        )
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
                sector_name,
                run_id,
                len(group),
                int((change > 0).sum()),
                int((change < 0).sum()),
                round(float(change.dropna().mean()), 4) if not change.dropna().empty else None,
                round(float(change.dropna().median()), 4) if not change.dropna().empty else None,
                round(float(rsi.dropna().mean()), 4) if not rsi.dropna().empty else None,
                round(float(score.dropna().mean()), 4) if not score.dropna().empty else None,
                Jsonb(top),
            ),
        )
