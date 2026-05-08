from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd
import psycopg

from market_scanner.storage.common import clean_bool, clean_int, clean_number, clean_text


def load_price_history(conn: Any, instrument_id: int, through_date: date) -> pd.DataFrame:
    rows = conn.execute(
        """
        SELECT DISTINCT ON (trade_date)
            trade_date, open_price, high_price, low_price, close_price, volume
        FROM daily_prices
        WHERE instrument_id = %s
          AND trade_date <= %s
        ORDER BY trade_date,
            CASE source_provider WHEN 'fdr' THEN 1 WHEN 'yfinance' THEN 2 ELSE 3 END
        """,
        (instrument_id, through_date),
    ).fetchall()
    if not rows:
        return pd.DataFrame()
    frame = pd.DataFrame(rows, columns=["trade_date", "Open", "High", "Low", "Close", "Volume"])
    frame["trade_date"] = pd.to_datetime(frame["trade_date"])
    frame = frame.set_index("trade_date")
    return frame.apply(pd.to_numeric, errors="coerce").dropna(subset=["Close"])


def upsert_daily_indicator(
    conn: psycopg.Connection,
    instrument_id: int,
    trade_date: date,
    source_provider: str,
    row: pd.Series,
    run_id: str,
) -> None:
    values = {
        "instrument_id": instrument_id,
        "trade_date": trade_date,
        "price_source_provider": source_provider,
        "rsi14": clean_number(row.get("rsi")),
        "ma5": clean_number(row.get("ma_5")),
        "ma20": clean_number(row.get("ma_20")),
        "ma60": clean_number(row.get("ma_60")),
        "ma120": clean_number(row.get("ma_120")),
        "ma240": clean_number(row.get("ma_240")),
        "diff_5_pct": clean_number(row.get("diff_5")),
        "diff_20_pct": clean_number(row.get("diff_20")),
        "diff_60_pct": clean_number(row.get("diff_60")),
        "diff_120_pct": clean_number(row.get("diff_120")),
        "diff_240_pct": clean_number(row.get("diff_240")),
        "near_5": clean_bool(row.get("near_5")),
        "near_20": clean_bool(row.get("near_20")),
        "near_60": clean_bool(row.get("near_60")),
        "near_120": clean_bool(row.get("near_120")),
        "near_240": clean_bool(row.get("near_240")),
        "macd": clean_number(row.get("macd")),
        "macd_signal": clean_number(row.get("macd_signal")),
        "macd_hist": clean_number(row.get("macd_hist")),
        "macd_state": clean_text(row.get("macd_state")) or "Unknown",
        "bollinger_width_pct": clean_number(row.get("bollinger_width_pct")),
        "bollinger_percent_b": clean_number(row.get("bollinger_percent_b")),
        "high_52w": clean_number(row.get("high_52w")),
        "low_52w": clean_number(row.get("low_52w")),
        "from_high_pct": clean_number(row.get("from_high_pct")),
        "from_low_pct": clean_number(row.get("from_low_pct")),
        "high_20d": clean_number(row.get("high_20d")),
        "low_20d": clean_number(row.get("low_20d")),
        "high_60d": clean_number(row.get("high_60d")),
        "low_60d": clean_number(row.get("low_60d")),
        "breakout_20d": clean_bool(row.get("breakout_20d")),
        "breakout_60d": clean_bool(row.get("breakout_60d")),
        "volume_ratio": clean_number(row.get("volume_ratio")),
        "return_5d": clean_number(row.get("return_5d")),
        "return_20d": clean_number(row.get("return_20d")),
        "return_60d": clean_number(row.get("return_60d")),
        "return_120d": clean_number(row.get("return_120d")),
        "return_240d": clean_number(row.get("return_240d")),
        "atr14": clean_number(row.get("atr14")),
        "atr14_pct": clean_number(row.get("atr14_pct")),
        "volatility_20d": clean_number(row.get("volatility_20d")),
        "volatility_60d": clean_number(row.get("volatility_60d")),
        "change_pct": clean_number(row.get("change_pct")),
        "gap_pct": clean_number(row.get("gap_pct")),
        "candle_body_pct": clean_number(row.get("candle_body_pct")),
        "candle_range_pct": clean_number(row.get("candle_range_pct")),
        "upper_shadow_pct": clean_number(row.get("upper_shadow_pct")),
        "lower_shadow_pct": clean_number(row.get("lower_shadow_pct")),
        "candle_type": clean_text(row.get("candle_type")) or "Unknown",
        "trend": clean_text(row.get("trend")),
        "trend_score": clean_int(row.get("trend_score")),
        "run_id": run_id,
    }
    columns = list(values)
    placeholders = ", ".join(["%s"] * len(columns))
    update_assignments = ",\n            ".join(
        f"{column} = EXCLUDED.{column}"
        for column in columns
        if column not in {"instrument_id", "trade_date"}
    )
    conn.execute(
        f"""
        INSERT INTO daily_indicators ({", ".join(columns)})
        VALUES ({placeholders})
        ON CONFLICT (instrument_id, trade_date) DO UPDATE SET
            {update_assignments},
            calculated_at = now()
        """,
        tuple(values[column] for column in columns),
    )
