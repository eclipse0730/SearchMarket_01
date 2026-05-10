from __future__ import annotations

import argparse
from datetime import date, datetime
from typing import Any

import pandas as pd

from market_scanner.config.markets import MARKETS
from market_scanner.domain.market_policy import home_market_key, price_source_for_market
from market_scanner.progress import progress_line
from market_scanner.storage.connection import connect
from market_scanner.storage.indicators import load_price_history, upsert_daily_indicator
from market_scanner.storage.runs import create_collection_run, finish_run


TREND_LABELS = {
    5: "Strong Uptrend",
    4: "Uptrend",
    3: "Neutral",
    2: "Downtrend",
    1: "Strong Downtrend",
    0: "Strong Downtrend",
}

_MA_PERIODS: tuple[int, ...] = (5, 20, 60, 120, 240)
_TREND_MA_PERIODS: tuple[int, ...] = (60, 120, 240)
_RETURN_PERIODS: tuple[int, ...] = (5, 20, 60, 120, 240)
_RANGE_PERIODS: tuple[int, ...] = (20, 60)
_VOLATILITY_PERIODS: tuple[int, ...] = (20, 60)
_MA_THRESHOLD_PCT: float = 3.0
_MIN_HISTORY: int = 270  # 240일 MA + 여유분


# ── 순수 계산 함수 (기존) ─────────────────────────────────────────────────────

def calc_rsi(close: pd.Series, period: int = 14) -> float | None:
    if len(close) < period + 1:
        return None

    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.iloc[1:period + 1].mean()
    avg_loss = loss.iloc[1:period + 1].mean()

    for i in range(period + 1, len(close)):
        avg_gain = ((avg_gain * (period - 1)) + gain.iloc[i]) / period
        avg_loss = ((avg_loss * (period - 1)) + loss.iloc[i]) / period

    if avg_loss == 0:
        return 100.0
    if avg_gain == 0:
        return 0.0

    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return round(float(rsi), 1)


def calc_macd(
    close: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[float | None, float | None, float | None, str]:
    if len(close) < slow + signal:
        return None, None, None, "Unknown"

    ema_fast = close.ewm(span=fast, adjust=False, min_periods=fast).mean()
    ema_slow = close.ewm(span=slow, adjust=False, min_periods=slow).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    hist = macd_line - signal_line
    clean = hist.dropna()
    if clean.empty:
        return None, None, None, "Unknown"

    last_hist = float(clean.iloc[-1])
    prev_hist = float(clean.iloc[-2]) if len(clean) >= 2 else last_hist
    if last_hist > 0 and last_hist >= prev_hist:
        state = "Bullish"
    elif last_hist > 0:
        state = "Positive"
    elif last_hist > prev_hist:
        state = "Improving"
    else:
        state = "Bearish"

    return (
        round(float(macd_line.iloc[-1]), 4) if pd.notna(macd_line.iloc[-1]) else None,
        round(float(signal_line.iloc[-1]), 4) if pd.notna(signal_line.iloc[-1]) else None,
        round(last_hist, 4),
        state,
    )


def calc_macd_cross(
    close: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[str, float | None]:
    if len(close) < slow + signal + 1:
        return "none", None

    ema_fast = close.ewm(span=fast, adjust=False, min_periods=fast).mean()
    ema_slow = close.ewm(span=slow, adjust=False, min_periods=slow).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    hist = macd_line - signal_line
    frame = pd.DataFrame({"macd": macd_line, "signal": signal_line, "hist": hist}).dropna()
    if len(frame) < 2:
        return "none", None

    prev = frame.iloc[-2]
    curr = frame.iloc[-1]
    cross = "none"
    if float(prev["macd"]) <= float(prev["signal"]) and float(curr["macd"]) > float(curr["signal"]):
        cross = "golden"
    elif float(prev["macd"]) >= float(prev["signal"]) and float(curr["macd"]) < float(curr["signal"]):
        cross = "dead"

    hist_change = float(curr["hist"]) - float(prev["hist"])
    return cross, round(hist_change, 4)


def calc_bollinger(
    close: pd.Series,
    period: int = 20,
    deviations: float = 2.0,
) -> tuple[float | None, float | None]:
    if len(close) < period:
        return None, None

    basis = close.rolling(window=period).mean()
    std = close.rolling(window=period).std()
    last_basis = basis.iloc[-1]
    last_std = std.iloc[-1]
    current = close.iloc[-1]
    if pd.isna(last_basis) or pd.isna(last_std) or float(last_basis) == 0:
        return None, None

    upper = float(last_basis + deviations * last_std)
    lower = float(last_basis - deviations * last_std)
    width = upper - lower
    if width <= 0:
        return None, None

    width_pct = width / float(last_basis) * 100
    percent_b = (float(current) - lower) / width
    return round(width_pct, 2), round(percent_b, 3)


def calc_atr(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 14,
) -> float | None:
    if len(close) < period + 1:
        return None

    prev_close = close.shift(1)
    true_range = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    clean_tr = true_range.dropna()
    if len(clean_tr) < period:
        return None

    atr_value = float(clean_tr.iloc[:period].mean())
    for value in clean_tr.iloc[period:]:
        atr_value = ((atr_value * (period - 1)) + float(value)) / period
    return round(atr_value, 4)


def calc_return(close: pd.Series, period: int) -> float | None:
    if len(close) <= period:
        return None
    base = _safe(close.iloc[-period - 1])
    current = _safe(close.iloc[-1])
    if not base or current is None:
        return None
    return round((current - base) / base * 100, 2)


def calc_annualized_volatility(close: pd.Series, period: int) -> float | None:
    if len(close) <= period:
        return None
    returns = close.pct_change()
    rolling_std = returns.rolling(window=period, min_periods=period).std()
    value = rolling_std.iloc[-1]
    if pd.isna(value):
        return None
    return round(float(value) * (252 ** 0.5) * 100, 2)


def calc_trend(
    close: pd.Series,
    ma_values: dict[int, float | None],
    ma_series: dict[int, pd.Series],
    periods: tuple[int, ...] = (60, 120, 240),
) -> tuple[int, str]:
    current_price = float(close.iloc[-1])
    score = 0
    sorted_periods = sorted(periods)

    if sorted_periods:
        ma_short = ma_values.get(sorted_periods[0])
        if ma_short and current_price > ma_short:
            score += 1

    for i in range(len(sorted_periods) - 1):
        ma_fast = ma_values.get(sorted_periods[i])
        ma_slow = ma_values.get(sorted_periods[i + 1])
        if ma_fast and ma_slow and ma_fast > ma_slow:
            score += 1

    for window in sorted_periods[:2]:
        series = ma_series.get(window)
        if series is None:
            continue
        clean = series.dropna()
        if len(clean) >= 21 and float(clean.iloc[-1]) > float(clean.iloc[-21]):
            score += 1

    return score, TREND_LABELS[min(score, 5)]


# ── 캔들 타입 ─────────────────────────────────────────────────────────────────

def calc_candle_type(
    open_price: float | None,
    high_price: float | None,
    low_price: float | None,
    close_price: float | None,
) -> str:
    if open_price is None or high_price is None or low_price is None or close_price is None:
        return "Unknown"
    candle_range = high_price - low_price
    if candle_range <= 0:
        return "Flat"

    body = close_price - open_price
    body_abs = abs(body)
    upper_shadow = high_price - max(open_price, close_price)
    lower_shadow = min(open_price, close_price) - low_price
    body_ratio = body_abs / candle_range
    upper_ratio = upper_shadow / candle_range
    lower_ratio = lower_shadow / candle_range

    if body_ratio <= 0.12:
        if lower_ratio >= 0.45:
            return "Long Lower Doji"
        if upper_ratio >= 0.45:
            return "Long Upper Doji"
        return "Doji"
    if body > 0 and lower_ratio >= 0.45:
        return "Bullish Reversal"
    if body < 0 and upper_ratio >= 0.45:
        return "Bearish Rejection"
    if body > 0 and body_ratio >= 0.65:
        return "Strong Bullish"
    if body < 0 and body_ratio >= 0.65:
        return "Strong Bearish"
    return "Bullish" if body > 0 else "Bearish"


# ── DB-based 계산 ─────────────────────────────────────────────────────────────

def _safe(value: Any, digits: int | None = None) -> float | None:
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(f):
        return None
    return round(f, digits) if digits is not None else f


def _avg_prior(series: pd.Series, period: int) -> float | None:
    if len(series) < period + 1:
        return None
    return _safe(series.iloc[-period - 1:-1].mean())


def _range_position(value: float | None, low: float | None, high: float | None) -> float | None:
    if value is None or low is None or high is None:
        return None
    width = high - low
    if width <= 0:
        return None
    return round((value - low) / width * 100, 2)


def _ma_slope_pct(series: pd.Series | None, lookback: int = 20) -> float | None:
    if series is None:
        return None
    clean = series.dropna()
    if len(clean) < lookback + 1:
        return None
    base = float(clean.iloc[-lookback - 1])
    if base == 0:
        return None
    return round((float(clean.iloc[-1]) - base) / base * 100, 2)


def _rsi_ma(close: pd.Series, period: int = 14, ma_period: int = 5) -> float | None:
    values: list[float] = []
    for end in range(len(close) - ma_period + 1, len(close) + 1):
        value = calc_rsi(close.iloc[:end], period)
        if value is None:
            return None
        values.append(value)
    return round(sum(values) / len(values), 1)


def _compute_from_hist(
    hist: pd.DataFrame,
    price_decimals: int = 2,
    ma_periods: tuple[int, ...] = _MA_PERIODS,
    threshold_pct: float = _MA_THRESHOLD_PCT,
) -> dict[str, Any]:
    close = hist["Close"]
    open_s = hist["Open"]
    high_s = hist["High"]
    low_s = hist["Low"]
    volume_s = hist.get("Volume")

    current = _safe(close.iloc[-1], price_decimals)
    if current is None:
        return {}

    prev_close = _safe(close.iloc[-2], price_decimals) if len(close) >= 2 else None
    open_price = _safe(open_s.iloc[-1], price_decimals)
    high_price = _safe(high_s.iloc[-1], price_decimals)
    low_price = _safe(low_s.iloc[-1], price_decimals)

    change_pct = round((current - prev_close) / prev_close * 100, 2) if prev_close else None
    gap_pct = (
        round((open_price - prev_close) / prev_close * 100, 2)
        if open_price and prev_close else None
    )
    candle_body_pct = round((current - open_price) / open_price * 100, 2) if open_price else None
    candle_range_pct = (
        round((high_price - low_price) / open_price * 100, 2)
        if open_price and high_price is not None and low_price is not None else None
    )
    upper_shadow_pct = (
        round((high_price - max(open_price, current)) / open_price * 100, 2)
        if open_price and high_price is not None else None
    )
    lower_shadow_pct = (
        round((min(open_price, current) - low_price) / open_price * 100, 2)
        if open_price and low_price is not None else None
    )
    candle_type = calc_candle_type(open_price, high_price, low_price, current)

    trailing_window = min(252, len(close))
    high_52w = _safe(high_s.iloc[-trailing_window:].max(), price_decimals)
    low_52w = _safe(low_s.iloc[-trailing_window:].min(), price_decimals)
    from_high_pct = round((current - high_52w) / high_52w * 100, 1) if high_52w else None
    from_low_pct = round((current - low_52w) / low_52w * 100, 1) if low_52w else None

    range_highs: dict[int, float | None] = {}
    range_lows: dict[int, float | None] = {}
    breakout_close: dict[int, bool] = {}
    breakout_high: dict[int, bool] = {}
    close_position_in_range: dict[int, float | None] = {}
    for period in _RANGE_PERIODS:
        if len(close) < period:
            range_highs[period] = None
            range_lows[period] = None
            breakout_close[period] = False
            breakout_high[period] = False
            close_position_in_range[period] = None
            continue
        range_high = _safe(high_s.iloc[-period:].max(), price_decimals)
        range_low = _safe(low_s.iloc[-period:].min(), price_decimals)
        prior_high = _safe(high_s.iloc[-period - 1:-1].max(), price_decimals) if len(close) > period else None
        range_highs[period] = range_high
        range_lows[period] = range_low
        breakout_close[period] = bool(prior_high and current > prior_high)
        breakout_high[period] = bool(prior_high and high_price is not None and high_price > prior_high)
        close_position_in_range[period] = _range_position(current, range_low, range_high)

    vol_last = _safe(volume_s.iloc[-1]) if volume_s is not None else None
    vol_avg20 = _avg_prior(volume_s, 20) if volume_s is not None else None
    vol_avg60 = _avg_prior(volume_s, 60) if volume_s is not None else None
    volume_ratio = round(vol_last / vol_avg20, 2) if vol_last and vol_avg20 else None
    value_traded = round(current * vol_last, 2) if vol_last is not None else None
    value_ratio_20d = None
    if volume_s is not None:
        value_s = close * volume_s
        value_avg20 = _avg_prior(value_s, 20)
        value_ratio_20d = round(value_traded / value_avg20, 2) if value_traded and value_avg20 else None

    rsi = calc_rsi(close)
    rsi_prev = calc_rsi(close.iloc[:-1]) if len(close) > 1 else None
    rsi_change = round(rsi - rsi_prev, 1) if rsi is not None and rsi_prev is not None else None
    rsi14_ma5 = _rsi_ma(close, 14, 5)
    rsi2 = calc_rsi(close, 2)
    rsi5 = calc_rsi(close, 5)
    rsi30 = calc_rsi(close, 30)
    macd, macd_signal, macd_hist, macd_state = calc_macd(close)
    macd_cross, macd_hist_change = calc_macd_cross(close)
    bollinger_width_pct, bollinger_percent_b = calc_bollinger(close)
    atr14 = calc_atr(high_s, low_s, close)
    atr14_pct = round(atr14 / current * 100, 2) if atr14 and current else None
    returns = {period: calc_return(close, period) for period in _RETURN_PERIODS}
    volatility = {period: calc_annualized_volatility(close, period) for period in _VOLATILITY_PERIODS}

    ma_values: dict[int, float | None] = {}
    ma_diff_pct: dict[int, float | None] = {}
    near_flags: dict[int, bool] = {}
    ma_series_dict: dict[int, pd.Series] = {}

    for period in ma_periods:
        if len(close) < period:
            ma_values[period] = None
            ma_diff_pct[period] = None
            near_flags[period] = False
            continue
        series = close.rolling(window=period).mean()
        ma_series_dict[period] = series
        ma_val = _safe(series.iloc[-1], price_decimals)
        ma_values[period] = ma_val
        if ma_val:
            diff = round((current - ma_val) / ma_val * 100, 2)
            ma_diff_pct[period] = diff
            near_flags[period] = abs(diff) <= threshold_pct
        else:
            ma_diff_pct[period] = None
            near_flags[period] = False

    alignment_pairs = [(5, 20), (20, 60), (60, 120), (120, 240)]
    ma_alignment_score = 0
    for fast, slow in alignment_pairs:
        fast_ma = ma_values.get(fast)
        slow_ma = ma_values.get(slow)
        if fast_ma is not None and slow_ma is not None and fast_ma > slow_ma:
            ma_alignment_score += 1
    is_ma_bullish_alignment = ma_alignment_score == len(alignment_pairs)
    ma20_slope_pct = _ma_slope_pct(ma_series_dict.get(20))
    ma60_slope_pct = _ma_slope_pct(ma_series_dict.get(60))

    trend_score, trend = calc_trend(close, ma_values, ma_series_dict, _TREND_MA_PERIODS)

    return {
        "rsi": rsi,
        "rsi14": rsi,
        "ma_5": ma_values.get(5),
        "ma_20": ma_values.get(20),
        "ma_60": ma_values.get(60),
        "ma_120": ma_values.get(120),
        "ma_240": ma_values.get(240),
        "diff_5": ma_diff_pct.get(5),
        "diff_20": ma_diff_pct.get(20),
        "diff_60": ma_diff_pct.get(60),
        "diff_120": ma_diff_pct.get(120),
        "diff_240": ma_diff_pct.get(240),
        "near_5": near_flags.get(5, False),
        "near_20": near_flags.get(20, False),
        "near_60": near_flags.get(60, False),
        "near_120": near_flags.get(120, False),
        "near_240": near_flags.get(240, False),
        "rsi_prev": rsi_prev,
        "rsi_change": rsi_change,
        "rsi14_prev": rsi_prev,
        "rsi14_change": rsi_change,
        "rsi14_ma5": rsi14_ma5,
        "rsi2": rsi2,
        "rsi5": rsi5,
        "rsi30": rsi30,
        "macd": macd,
        "macd_signal": macd_signal,
        "macd_hist": macd_hist,
        "macd_state": macd_state,
        "macd_cross": macd_cross,
        "macd_hist_change": macd_hist_change,
        "bollinger_width_pct": bollinger_width_pct,
        "bollinger_percent_b": bollinger_percent_b,
        "high_52w": high_52w,
        "low_52w": low_52w,
        "from_high_pct": from_high_pct,
        "from_low_pct": from_low_pct,
        "high_20d": range_highs.get(20),
        "low_20d": range_lows.get(20),
        "high_60d": range_highs.get(60),
        "low_60d": range_lows.get(60),
        "breakout_20d": breakout_close.get(20, False),
        "breakout_60d": breakout_close.get(60, False),
        "breakout_high_20d": breakout_high.get(20, False),
        "breakout_high_60d": breakout_high.get(60, False),
        "new_high_20d_close": breakout_close.get(20, False),
        "new_high_20d_high": breakout_high.get(20, False),
        "new_high_60d_close": breakout_close.get(60, False),
        "new_high_60d_high": breakout_high.get(60, False),
        "close_position_in_range_20d": close_position_in_range.get(20),
        "close_position_in_range_60d": close_position_in_range.get(60),
        "volume_ratio": volume_ratio,
        "value_traded": value_traded,
        "value_ratio_20d": value_ratio_20d,
        "volume_avg20": vol_avg20,
        "volume_avg60": vol_avg60,
        "return_5d": returns.get(5),
        "return_20d": returns.get(20),
        "return_60d": returns.get(60),
        "return_120d": returns.get(120),
        "return_240d": returns.get(240),
        "atr14": atr14,
        "atr14_pct": atr14_pct,
        "volatility_20d": volatility.get(20),
        "volatility_60d": volatility.get(60),
        "change_pct": change_pct,
        "gap_pct": gap_pct,
        "candle_body_pct": candle_body_pct,
        "candle_range_pct": candle_range_pct,
        "upper_shadow_pct": upper_shadow_pct,
        "lower_shadow_pct": lower_shadow_pct,
        "candle_type": candle_type,
        "trend": trend,
        "trend_score": trend_score,
        "ma_alignment_score": ma_alignment_score,
        "is_ma_bullish_alignment": is_ma_bullish_alignment,
        "ma20_slope_pct": ma20_slope_pct,
        "ma60_slope_pct": ma60_slope_pct,
    }


def compute_for_instrument(
    conn: Any,
    instrument_id: int,
    trade_date: date,
    run_id: str,
    source_provider: str = "fdr",
    price_decimals: int = 2,
) -> tuple[bool, str | None]:
    hist = load_price_history(conn, instrument_id, trade_date)
    if hist.empty:
        return False, "empty_price_history"
    if len(hist) < _MIN_HISTORY // 2:
        return False, "insufficient_history"

    result = _compute_from_hist(hist, price_decimals=price_decimals)
    if not result:
        return False, "compute_empty"

    indicator_row = pd.Series(result)
    upsert_daily_indicator(conn, instrument_id, trade_date, source_provider, indicator_row, run_id)
    return True, None


def _parse_date_arg(value: str | None) -> date | None:
    return datetime.strptime(value, "%Y%m%d").date() if value else None


def _resolve_date_range(date_from: str | None, date_to: str | None) -> tuple[date, date]:
    end_date = _parse_date_arg(date_to) or date.today()
    start_date = _parse_date_arg(date_from) or end_date
    if start_date > end_date:
        raise ValueError("--from must be earlier than or equal to --to")
    return start_date, end_date


def run_compute(
    market_key: str,
    date_str: str | None = None,
    explicit_url: str | None = None,
    limit: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> None:
    if date_str:
        if date_from or date_to:
            raise ValueError("--date cannot be used with --from/--to")
        target_dates = [_parse_date_arg(date_str)]
    elif date_from or date_to:
        start_date, end_date = _resolve_date_range(date_from, date_to)
        target_dates = None
    else:
        target_dates = [date.today()]
    source_provider = price_source_for_market(market_key)
    market = MARKETS[market_key]
    price_decimals = market.price_decimals

    if target_dates is None:
        with connect(explicit_url) as conn:
            rows = conn.execute(
                """
                SELECT DISTINCT dp.trade_date
                FROM daily_prices dp
                JOIN instruments i ON i.instrument_id = dp.instrument_id
                WHERE i.market_key = %s
                  AND i.is_active = TRUE
                  AND dp.trade_date BETWEEN %s AND %s
                ORDER BY dp.trade_date
                """,
                (home_market_key(market_key), start_date, end_date),
            ).fetchall()
        target_dates = [row[0] for row in rows]
        if not target_dates:
            print(
                f"  indicators compute [{market_key}]: no price dates found "
                f"from {start_date.isoformat()} to {end_date.isoformat()}"
            )
            return
        print(
            f"  indicators compute [{market_key}]: {len(target_dates)} date(s) "
            f"from {start_date.isoformat()} to {end_date.isoformat()}"
        )
        for target_date in target_dates:
            run_compute(
                market_key,
                target_date.strftime("%Y%m%d"),
                explicit_url,
                limit,
            )
        return

    trade_date = target_dates[0]

    with connect(explicit_url) as conn:
        rows = conn.execute(
            """
            SELECT instrument_id, symbol
            FROM instruments
            WHERE market_key = %s AND is_active = TRUE
            ORDER BY symbol
            """,
            (home_market_key(market_key),),
        ).fetchall()

        instruments = [{"instrument_id": row[0], "symbol": str(row[1])} for row in rows]
        if limit:
            instruments = instruments[:limit]

        if not instruments:
            print(f"  indicators compute [{market_key}]: no active instruments")
            return

        run_id = create_collection_run(
            conn, "indicators", market_key, trade_date, source_provider, len(instruments),
            params={"mode": "compute"},
        )

        print(f"  indicators compute [{market_key}] {len(instruments)} symbols  run_id={run_id}")

        success, failed, skipped = 0, 0, 0
        error_samples: list[dict[str, Any]] = []

        def print_progress(force: bool = False) -> None:
            processed = success + failed + skipped
            if not force and processed < len(instruments):
                return
            print(
                progress_line(
                    processed,
                    len(instruments),
                    success=success,
                    failed=failed,
                    skipped=skipped,
                ),
                end="",
                flush=True,
            )

        print_progress(force=True)

        for instr in instruments:
            instrument_id = instr["instrument_id"]
            symbol = instr["symbol"]

            has_price = conn.execute(
                "SELECT 1 FROM daily_prices WHERE instrument_id = %s AND trade_date = %s LIMIT 1",
                (instrument_id, trade_date),
            ).fetchone()
            if not has_price:
                skipped += 1
                if len(error_samples) < 30:
                    error_samples.append({"symbol": symbol, "status": "skipped", "reason": "missing_target_price"})
                print_progress(force=True)
                continue

            ok, reason = compute_for_instrument(
                conn, instrument_id, trade_date, run_id, source_provider, price_decimals
            )
            if ok:
                success += 1
            else:
                failed += 1
                if len(error_samples) < 30:
                    error_samples.append({"symbol": symbol, "status": "failed", "reason": reason or "unknown"})
            print_progress(force=True)

        print()
        if failed or skipped:
            status = "partial" if success else "failed"
        else:
            status = "success"
        finish_run(conn, run_id, status=status, success_count=success, failed_count=failed, skipped_count=skipped, error_samples=error_samples)
        print(
            f"  indicators compute [{market_key}] done: "
            f"success={success} failed={failed} skipped={skipped} status={status}"
        )


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Daily indicator calculator (DB-based).")
    parser.add_argument("--database-url", default=None)
    sub = parser.add_subparsers(dest="command", required=True)

    compute_p = sub.add_parser("compute", help="Compute daily_indicators from daily_prices.")
    compute_p.add_argument("--market", required=True)
    compute_p.add_argument("--date", default=None, help="Trade date YYYYMMDD (default: today).")
    compute_p.add_argument("--from", dest="date_from", default=None, help="Start trade date YYYYMMDD.")
    compute_p.add_argument("--to", dest="date_to", default=None, help="End trade date YYYYMMDD.")
    compute_p.add_argument("--limit", type=int, default=None)

    args = parser.parse_args()
    try:
        if args.command == "compute":
            run_compute(args.market, args.date, args.database_url, args.limit, args.date_from, args.date_to)
    except ValueError as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
