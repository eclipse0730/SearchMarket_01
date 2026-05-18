from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

from market_scanner.domain.market_policy import home_market_key


def latest_indicator_date(
    conn: Any,
    market_key: str,
    universe_key: str | None = None,
) -> date | None:
    base_market = home_market_key(market_key)
    params: list[Any] = [base_market]
    universe_filter = ""
    if universe_key:
        universe_filter = """
        JOIN universe_memberships um
            ON um.instrument_id = i.instrument_id
            AND um.universe_key = %s
            AND um.effective_to IS NULL
        """
        params = [universe_key, base_market]

    row = conn.execute(
        f"""
        SELECT MAX(di.trade_date)
        FROM daily_indicators di
        JOIN instruments i ON i.instrument_id = di.instrument_id
        {universe_filter}
        WHERE i.market_key = %s
          AND i.is_active = TRUE
        """,
        params,
    ).fetchone()
    return row[0] if row and row[0] else None


def load_screen_frame(
    conn: Any,
    market_key: str,
    trade_date: date,
    universe_key: str | None = None,
) -> pd.DataFrame:
    base_market = home_market_key(market_key)
    params: list[Any] = [trade_date, trade_date, trade_date, base_market]
    universe_filter = ""
    if universe_key:
        universe_filter = """
        JOIN universe_memberships um
            ON um.instrument_id = i.instrument_id
            AND um.universe_key = %s
            AND um.effective_to IS NULL
        """
        params = [universe_key, trade_date, trade_date, trade_date, base_market]

    rows = conn.execute(
        f"""
        SELECT
            i.instrument_id,
            i.symbol,
            i.display_symbol,
            i.name_en,
            i.name_local,
            i.sector,
            i.description,
            -- daily_indicators
            di.rsi14         AS rsi,
            di.rsi14,
            di.rsi14_prev,
            di.rsi14_change,
            di.rsi14_ma5,
            di.rsi2,
            di.rsi5,
            di.rsi30,
            di.ma5,
            di.ma20,
            di.ma60,
            di.ma120,
            di.ma240,
            di.diff_5_pct    AS diff_5,
            di.diff_20_pct   AS diff_20,
            di.diff_60_pct   AS diff_60,
            di.diff_120_pct  AS diff_120,
            di.diff_240_pct  AS diff_240,
            di.near_5,
            di.near_20,
            di.near_60,
            di.near_120,
            di.near_240,
            di.macd,
            di.macd_signal,
            di.macd_hist,
            di.macd_state,
            di.bollinger_width_pct,
            di.bollinger_percent_b,
            di.high_52w,
            di.low_52w,
            di.from_high_pct,
            di.from_low_pct,
            di.high_20d,
            di.low_20d,
            di.high_60d,
            di.low_60d,
            di.breakout_20d,
            di.breakout_60d,
            di.breakout_high_20d,
            di.breakout_high_60d,
            di.volume_ratio,
            di.value_traded,
            di.value_ratio_20d,
            di.volume_avg20,
            di.volume_avg60,
            di.ma_alignment_score,
            di.is_ma_bullish_alignment,
            di.ma20_slope_pct,
            di.ma60_slope_pct,
            di.macd_cross,
            di.macd_hist_change,
            di.close_position_in_range_20d,
            di.close_position_in_range_60d,
            di.return_5d,
            di.return_20d,
            di.return_60d,
            di.return_120d,
            di.return_240d,
            di.atr14,
            di.atr14_pct,
            di.volatility_20d,
            di.volatility_60d,
            di.change_pct,
            di.gap_pct,
            di.candle_body_pct,
            di.candle_range_pct,
            di.upper_shadow_pct,
            di.lower_shadow_pct,
            di.candle_type,
            di.trend,
            di.trend_score,
            -- daily_prices (fdr 우선)
            dp.close_price   AS close,
            dp.open_price    AS open,
            dp.high_price    AS high,
            dp.low_price     AS low,
            dp.volume,
            -- fundamentals (최신)
            f.trailing_pe,
            f.price_to_book,
            f.return_on_equity_pct  AS return_on_equity,
            f.revenue_growth_pct    AS revenue_growth,
            f.market_cap,
            f.target_price,
            flows.foreign_net_buy_1d,
            flows.foreign_net_buy_5d,
            flows.foreign_net_buy_20d,
            flows.institution_net_buy_1d,
            flows.institution_net_buy_5d,
            flows.institution_net_buy_20d,
            flows.flow_latest_date
        FROM instruments i
        {universe_filter}
        JOIN daily_indicators di
            ON di.instrument_id = i.instrument_id AND di.trade_date = %s
        JOIN LATERAL (
            SELECT close_price, open_price, high_price, low_price, volume
            FROM daily_prices
            WHERE instrument_id = i.instrument_id AND trade_date = %s
            ORDER BY CASE source_provider WHEN 'fdr' THEN 1 WHEN 'yfinance' THEN 2 ELSE 3 END
            LIMIT 1
        ) dp ON TRUE
        LEFT JOIN LATERAL (
            SELECT trailing_pe, price_to_book, return_on_equity_pct,
                   revenue_growth_pct, market_cap, target_price
            FROM instrument_fundamentals
            WHERE instrument_id = i.instrument_id
            ORDER BY
                as_of_date DESC,
                CASE source_provider
                    WHEN 'naver' THEN 1
                    WHEN 'yahoo' THEN 2
                    WHEN 'yfinance' THEN 3
                    WHEN 'fdr' THEN 4
                    ELSE 5
                END
            LIMIT 1
        ) f ON TRUE
        LEFT JOIN LATERAL (
            SELECT
                SUM(foreign_net_buy_value) FILTER (WHERE rn <= 1) AS foreign_net_buy_1d,
                SUM(foreign_net_buy_value) FILTER (WHERE rn <= 5) AS foreign_net_buy_5d,
                SUM(foreign_net_buy_value) FILTER (WHERE rn <= 20) AS foreign_net_buy_20d,
                SUM(institution_net_buy_value) FILTER (WHERE rn <= 1) AS institution_net_buy_1d,
                SUM(institution_net_buy_value) FILTER (WHERE rn <= 5) AS institution_net_buy_5d,
                SUM(institution_net_buy_value) FILTER (WHERE rn <= 20) AS institution_net_buy_20d,
                MAX(trade_date) AS flow_latest_date
            FROM (
                SELECT
                    trade_date,
                    foreign_net_buy_value,
                    institution_net_buy_value,
                    ROW_NUMBER() OVER (ORDER BY trade_date DESC) AS rn
                FROM daily_investor_flows
                WHERE instrument_id = i.instrument_id
                  AND trade_date <= %s
                ORDER BY trade_date DESC
                LIMIT 20
            ) recent_flows
        ) flows ON TRUE
        WHERE i.market_key = %s AND i.is_active = TRUE
        ORDER BY i.symbol
        """,
        params,
    ).fetchall()

    if not rows:
        return pd.DataFrame()

    columns = [
        "instrument_id", "symbol", "display_symbol", "name_en", "name_local",
        "sector", "description",
        "rsi", "rsi14", "rsi14_prev", "rsi14_change", "rsi14_ma5", "rsi2", "rsi5", "rsi30",
        "ma_5", "ma_20", "ma_60", "ma_120", "ma_240",
        "diff_5", "diff_20", "diff_60", "diff_120", "diff_240",
        "near_5", "near_20", "near_60", "near_120", "near_240",
        "macd", "macd_signal", "macd_hist", "macd_state",
        "bollinger_width_pct", "bollinger_percent_b",
        "high_52w", "low_52w", "from_high_pct", "from_low_pct",
        "high_20d", "low_20d", "high_60d", "low_60d",
        "breakout_20d", "breakout_60d", "breakout_high_20d", "breakout_high_60d", "volume_ratio",
        "value_traded", "value_ratio_20d", "volume_avg20", "volume_avg60",
        "ma_alignment_score", "is_ma_bullish_alignment", "ma20_slope_pct", "ma60_slope_pct",
        "macd_cross", "macd_hist_change",
        "close_position_in_range_20d", "close_position_in_range_60d",
        "return_5d", "return_20d", "return_60d", "return_120d", "return_240d",
        "atr14", "atr14_pct", "volatility_20d", "volatility_60d",
        "change_pct", "gap_pct",
        "candle_body_pct", "candle_range_pct", "upper_shadow_pct", "lower_shadow_pct",
        "candle_type", "trend", "trend_score",
        "close", "open", "high", "low", "volume",
        "trailing_pe", "price_to_book", "return_on_equity", "revenue_growth",
        "market_cap", "target_price",
        "foreign_net_buy_1d", "foreign_net_buy_5d", "foreign_net_buy_20d",
        "institution_net_buy_1d", "institution_net_buy_5d", "institution_net_buy_20d",
        "flow_latest_date",
    ]
    frame = pd.DataFrame(rows, columns=columns)

    numeric_cols = [c for c in frame.columns if c not in (
        "instrument_id", "symbol", "display_symbol", "name_en", "name_local",
        "sector", "description", "macd_state", "macd_cross", "candle_type", "trend",
        "flow_latest_date",
        "near_5", "near_20", "near_60", "near_120", "near_240",
        "breakout_20d", "breakout_60d", "breakout_high_20d", "breakout_high_60d",
        "is_ma_bullish_alignment",
    )]
    frame[numeric_cols] = frame[numeric_cols].apply(pd.to_numeric, errors="coerce")

    close_num = pd.to_numeric(frame["close"], errors="coerce")
    target_num = pd.to_numeric(frame["target_price"], errors="coerce")
    frame["upside_pct"] = ((target_num - close_num) / close_num * 100).round(1)

    return frame
