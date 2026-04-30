from __future__ import annotations

import pandas as pd


TREND_LABELS = {
    5: "Strong Uptrend",
    4: "Uptrend",
    3: "Neutral",
    2: "Downtrend",
    1: "Strong Downtrend",
    0: "Strong Downtrend",
}


def calc_rsi(close: pd.Series, period: int = 14) -> float | None:
    if len(close) < period + 1:
        return None

    delta = close.diff(1)
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    last_loss = float(avg_loss.iloc[-1])
    if last_loss == 0:
        return 100.0

    rs = float(avg_gain.iloc[-1]) / last_loss
    return round(100 - (100 / (1 + rs)), 1)


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
