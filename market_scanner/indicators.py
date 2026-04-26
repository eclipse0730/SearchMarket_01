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

