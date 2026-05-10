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


# `_compute_from_hist()` 결과 dict 의 키와 daily_indicators 컬럼명이 1:1 일치한다.
# 각 컬럼의 타입에 맞는 cleaner 만 매핑.
_NUMERIC_COLUMNS: tuple[str, ...] = (
    "rsi14", "rsi14_prev", "rsi14_change", "rsi14_ma5", "rsi2", "rsi5", "rsi30",
    "ma5", "ma20", "ma60", "ma120", "ma240",
    "diff_5_pct", "diff_20_pct", "diff_60_pct", "diff_120_pct", "diff_240_pct",
    "macd", "macd_signal", "macd_hist", "macd_hist_change",
    "bollinger_width_pct", "bollinger_percent_b",
    "high_52w", "low_52w", "from_high_pct", "from_low_pct",
    "high_20d", "low_20d", "high_60d", "low_60d",
    "close_position_in_range_20d", "close_position_in_range_60d",
    "volume_ratio", "value_traded", "value_ratio_20d", "volume_avg20", "volume_avg60",
    "ma20_slope_pct", "ma60_slope_pct",
    "return_5d", "return_20d", "return_60d", "return_120d", "return_240d",
    "atr14", "atr14_pct",
    "volatility_20d", "volatility_60d",
    "change_pct", "gap_pct",
    "candle_body_pct", "candle_range_pct", "upper_shadow_pct", "lower_shadow_pct",
)
_BOOL_COLUMNS: tuple[str, ...] = (
    "near_5", "near_20", "near_60", "near_120", "near_240",
    "breakout_20d", "breakout_60d", "breakout_high_20d", "breakout_high_60d",
    "is_ma_bullish_alignment",
)
_INT_COLUMNS: tuple[str, ...] = ("ma_alignment_score", "trend_score")
_TEXT_COLUMNS_WITH_DEFAULT: dict[str, str] = {
    "macd_state": "Unknown",
    "macd_cross": "none",
    "candle_type": "Unknown",
}
_TEXT_COLUMNS: tuple[str, ...] = ("trend",)


def upsert_daily_indicator(
    conn: psycopg.Connection,
    instrument_id: int,
    trade_date: date,
    source_provider: str,
    row: pd.Series,
    run_id: str,
) -> None:
    values: dict[str, Any] = {
        "instrument_id": instrument_id,
        "trade_date": trade_date,
        "price_source_provider": source_provider,
    }
    for col in _NUMERIC_COLUMNS:
        values[col] = clean_number(row.get(col))
    for col in _BOOL_COLUMNS:
        values[col] = clean_bool(row.get(col))
    for col in _INT_COLUMNS:
        values[col] = clean_int(row.get(col))
    for col, default in _TEXT_COLUMNS_WITH_DEFAULT.items():
        values[col] = clean_text(row.get(col)) or default
    for col in _TEXT_COLUMNS:
        values[col] = clean_text(row.get(col))
    values["run_id"] = run_id

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
