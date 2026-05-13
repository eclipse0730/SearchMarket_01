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
    rsi = calc_rsi_series(close, period)
    clean = rsi.dropna()
    if clean.empty:
        return None
    return round(float(clean.iloc[-1]), 1)


def calc_rsi_series(close: pd.Series, period: int = 14) -> pd.Series:
    rsi = pd.Series(float("nan"), index=close.index, dtype="float64")
    if len(close) < period + 1:
        return rsi

    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = _wilder_smooth(gain, period)
    avg_loss = _wilder_smooth(loss, period)

    rs = avg_gain / avg_loss
    rsi_vals = 100 - (100 / (1 + rs))
    # 0/0 인 경우 (가격 완전 횡보) 원본 로직과 동일하게 100 으로 처리
    both_zero = (avg_gain == 0) & (avg_loss == 0)
    rsi_vals = rsi_vals.mask(both_zero, 100.0)
    return rsi_vals.round(1)


def _wilder_smooth(series: pd.Series, period: int) -> pd.Series:
    """Wilder smoothing: SMA(series[1:period+1]) seed, then EMA(α=1/period).

    원본 구현의 첫 RSI/ATR 위치(`period` 인덱스)와 이후 재귀식 ``avg_new =
    (avg_old*(period-1) + value)/period`` 를 그대로 보존하면서 ``ewm`` 으로
    벡터화.
    """
    result = pd.Series(float("nan"), index=series.index, dtype="float64")
    if len(series) < period + 1:
        return result

    seed = float(series.iloc[1:period + 1].mean())
    tail = series.iloc[period + 1:].reset_index(drop=True)
    inputs = pd.concat([pd.Series([seed]), tail], ignore_index=True)
    smoothed = inputs.ewm(alpha=1.0 / period, adjust=False).mean()
    result.iloc[period:] = smoothed.values
    return result


def calc_macd(
    close: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[float | None, float | None, float | None, str, str, float | None]:
    if len(close) < slow + signal:
        return None, None, None, "Unknown", "none", None

    ema_fast = close.ewm(span=fast, adjust=False, min_periods=fast).mean()
    ema_slow = close.ewm(span=slow, adjust=False, min_periods=slow).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    hist = macd_line - signal_line
    frame = pd.DataFrame({"macd": macd_line, "signal": signal_line, "hist": hist}).dropna()
    if frame.empty:
        return None, None, None, "Unknown", "none", None

    curr = frame.iloc[-1]
    prev = frame.iloc[-2] if len(frame) >= 2 else curr
    last_hist = float(curr["hist"])
    prev_hist = float(prev["hist"])
    if last_hist > 0 and last_hist >= prev_hist:
        state = "Bullish"
    elif last_hist > 0:
        state = "Positive"
    elif last_hist > prev_hist:
        state = "Improving"
    else:
        state = "Bearish"

    cross = "none"
    hist_change = None
    if len(frame) >= 2:
        if float(prev["macd"]) <= float(prev["signal"]) and float(curr["macd"]) > float(curr["signal"]):
            cross = "golden"
        elif float(prev["macd"]) >= float(prev["signal"]) and float(curr["macd"]) < float(curr["signal"]):
            cross = "dead"
        hist_change = round(last_hist - prev_hist, 4)

    return (
        round(float(curr["macd"]), 4),
        round(float(curr["signal"]), 4),
        round(last_hist, 4),
        state,
        cross,
        hist_change,
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


def _candle_block(
    current: float,
    prev_close: float | None,
    open_price: float | None,
    high_price: float | None,
    low_price: float | None,
) -> dict[str, Any]:
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
    return {
        "change_pct": change_pct,
        "gap_pct": gap_pct,
        "candle_body_pct": candle_body_pct,
        "candle_range_pct": candle_range_pct,
        "upper_shadow_pct": upper_shadow_pct,
        "lower_shadow_pct": lower_shadow_pct,
        "candle_type": calc_candle_type(open_price, high_price, low_price, current),
    }


def _yearly_range_block(
    close: pd.Series,
    high_s: pd.Series,
    low_s: pd.Series,
    current: float,
    price_decimals: int,
) -> dict[str, Any]:
    trailing_window = min(252, len(close))
    high_52w = _safe(high_s.iloc[-trailing_window:].max(), price_decimals)
    low_52w = _safe(low_s.iloc[-trailing_window:].min(), price_decimals)
    return {
        "high_52w": high_52w,
        "low_52w": low_52w,
        "from_high_pct": round((current - high_52w) / high_52w * 100, 1) if high_52w else None,
        "from_low_pct": round((current - low_52w) / low_52w * 100, 1) if low_52w else None,
    }


def _short_range_block(
    close: pd.Series,
    high_s: pd.Series,
    low_s: pd.Series,
    current: float,
    high_price: float | None,
    price_decimals: int,
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for period in _RANGE_PERIODS:
        if len(close) < period:
            out[f"high_{period}d"] = None
            out[f"low_{period}d"] = None
            out[f"breakout_{period}d"] = False
            out[f"breakout_high_{period}d"] = False
            out[f"close_position_in_range_{period}d"] = None
            continue
        range_high = _safe(high_s.iloc[-period:].max(), price_decimals)
        range_low = _safe(low_s.iloc[-period:].min(), price_decimals)
        prior_high = (
            _safe(high_s.iloc[-period - 1:-1].max(), price_decimals)
            if len(close) > period else None
        )
        out[f"high_{period}d"] = range_high
        out[f"low_{period}d"] = range_low
        out[f"breakout_{period}d"] = bool(prior_high and current > prior_high)
        out[f"breakout_high_{period}d"] = bool(
            prior_high and high_price is not None and high_price > prior_high
        )
        out[f"close_position_in_range_{period}d"] = _range_position(current, range_low, range_high)
    return out


def _volume_block(
    close: pd.Series,
    volume_s: pd.Series | None,
    current: float,
) -> dict[str, Any]:
    if volume_s is None:
        return {
            "volume_ratio": None,
            "value_traded": None,
            "value_ratio_20d": None,
            "volume_avg20": None,
            "volume_avg60": None,
        }
    vol_last = _safe(volume_s.iloc[-1])
    vol_avg20 = _avg_prior(volume_s, 20)
    vol_avg60 = _avg_prior(volume_s, 60)
    volume_ratio = round(vol_last / vol_avg20, 2) if vol_last and vol_avg20 else None
    value_traded = round(current * vol_last, 2) if vol_last is not None else None
    value_avg20 = _avg_prior(close * volume_s, 20)
    value_ratio_20d = round(value_traded / value_avg20, 2) if value_traded and value_avg20 else None
    return {
        "volume_ratio": volume_ratio,
        "value_traded": value_traded,
        "value_ratio_20d": value_ratio_20d,
        "volume_avg20": vol_avg20,
        "volume_avg60": vol_avg60,
    }


def _momentum_block(
    close: pd.Series,
    high_s: pd.Series,
    low_s: pd.Series,
    current: float,
) -> dict[str, Any]:
    rsi14_clean = calc_rsi_series(close, 14).dropna()
    rsi14 = round(float(rsi14_clean.iloc[-1]), 1) if not rsi14_clean.empty else None
    rsi14_prev = round(float(rsi14_clean.iloc[-2]), 1) if len(rsi14_clean) >= 2 else None
    rsi14_change = (
        round(rsi14 - rsi14_prev, 1) if rsi14 is not None and rsi14_prev is not None else None
    )
    rsi14_ma5 = round(float(rsi14_clean.tail(5).mean()), 1) if len(rsi14_clean) >= 5 else None

    macd, macd_signal, macd_hist, macd_state, macd_cross, macd_hist_change = calc_macd(close)
    bollinger_width_pct, bollinger_percent_b = calc_bollinger(close)
    atr14 = calc_atr(high_s, low_s, close)
    atr14_pct = round(atr14 / current * 100, 2) if atr14 and current else None

    return {
        "rsi14": rsi14,
        "rsi14_prev": rsi14_prev,
        "rsi14_change": rsi14_change,
        "rsi14_ma5": rsi14_ma5,
        "rsi2": calc_rsi(close, 2),
        "rsi5": calc_rsi(close, 5),
        "rsi30": calc_rsi(close, 30),
        "macd": macd,
        "macd_signal": macd_signal,
        "macd_hist": macd_hist,
        "macd_state": macd_state,
        "macd_cross": macd_cross,
        "macd_hist_change": macd_hist_change,
        "bollinger_width_pct": bollinger_width_pct,
        "bollinger_percent_b": bollinger_percent_b,
        "atr14": atr14,
        "atr14_pct": atr14_pct,
    }


def _return_volatility_block(close: pd.Series) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for period in _RETURN_PERIODS:
        out[f"return_{period}d"] = calc_return(close, period)
    for period in _VOLATILITY_PERIODS:
        out[f"volatility_{period}d"] = calc_annualized_volatility(close, period)
    return out


def _ma_block(
    close: pd.Series,
    current: float,
    ma_periods: tuple[int, ...],
    threshold_pct: float,
    price_decimals: int,
) -> tuple[dict[str, Any], dict[int, pd.Series], dict[int, float | None]]:
    out: dict[str, Any] = {}
    ma_series_dict: dict[int, pd.Series] = {}
    ma_values: dict[int, float | None] = {}

    for period in ma_periods:
        if len(close) < period:
            ma_values[period] = None
            out[f"ma{period}"] = None
            out[f"diff_{period}_pct"] = None
            out[f"near_{period}"] = False
            continue
        series = close.rolling(window=period).mean()
        ma_series_dict[period] = series
        ma_val = _safe(series.iloc[-1], price_decimals)
        ma_values[period] = ma_val
        out[f"ma{period}"] = ma_val
        if ma_val:
            diff = round((current - ma_val) / ma_val * 100, 2)
            out[f"diff_{period}_pct"] = diff
            out[f"near_{period}"] = abs(diff) <= threshold_pct
        else:
            out[f"diff_{period}_pct"] = None
            out[f"near_{period}"] = False

    alignment_pairs = ((5, 20), (20, 60), (60, 120), (120, 240))
    score = sum(
        1 for fast, slow in alignment_pairs
        if ma_values.get(fast) is not None and ma_values.get(slow) is not None
        and ma_values[fast] > ma_values[slow]  # type: ignore[operator]
    )
    out["ma_alignment_score"] = score
    out["is_ma_bullish_alignment"] = score == len(alignment_pairs)
    out["ma20_slope_pct"] = _ma_slope_pct(ma_series_dict.get(20))
    out["ma60_slope_pct"] = _ma_slope_pct(ma_series_dict.get(60))
    return out, ma_series_dict, ma_values


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

    result: dict[str, Any] = {}
    result.update(_candle_block(current, prev_close, open_price, high_price, low_price))
    result.update(_yearly_range_block(close, high_s, low_s, current, price_decimals))
    result.update(_short_range_block(close, high_s, low_s, current, high_price, price_decimals))
    result.update(_volume_block(close, volume_s, current))
    result.update(_momentum_block(close, high_s, low_s, current))
    result.update(_return_volatility_block(close))
    ma_block, ma_series_dict, ma_values = _ma_block(
        close, current, ma_periods, threshold_pct, price_decimals
    )
    result.update(ma_block)

    trend_score, trend = calc_trend(close, ma_values, ma_series_dict, _TREND_MA_PERIODS)
    result["trend"] = trend
    result["trend_score"] = trend_score
    return result


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


def _resolve_target_dates(
    conn: Any,
    market_key: str,
    date_str: str | None,
    date_from: str | None,
    date_to: str | None,
) -> list[date]:
    if date_str:
        if date_from or date_to:
            raise ValueError("--date cannot be used with --from/--to")
        return [_parse_date_arg(date_str)]
    if not (date_from or date_to):
        return [date.today()]

    start_date, end_date = _resolve_date_range(date_from, date_to)
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
    else:
        print(
            f"  indicators compute [{market_key}]: {len(target_dates)} date(s) "
            f"from {start_date.isoformat()} to {end_date.isoformat()}"
        )
    return target_dates


def _load_active_instruments(
    conn: Any,
    market_key: str,
    limit: int | None,
) -> list[dict[str, Any]]:
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
    return instruments


def _process_date(
    conn: Any,
    market_key: str,
    trade_date: date,
    source_provider: str,
    price_decimals: int,
    instruments: list[dict[str, Any]],
) -> None:
    run_id = create_collection_run(
        conn, "indicators", market_key, trade_date, source_provider, len(instruments),
        params={"mode": "compute"},
    )
    print(f"  indicators compute [{market_key}] {len(instruments)} symbols  run_id={run_id}")

    success, failed, skipped = 0, 0, 0
    error_samples: list[dict[str, Any]] = []

    def print_progress() -> None:
        processed = success + failed + skipped
        print(
            progress_line(
                processed, len(instruments),
                success=success, failed=failed, skipped=skipped,
            ),
            end="",
            flush=True,
        )

    print_progress()

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
            print_progress()
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
        print_progress()

    print()
    if failed or skipped:
        status = "partial" if success else "failed"
    else:
        status = "success"
    finish_run(
        conn, run_id, status=status,
        success_count=success, failed_count=failed, skipped_count=skipped,
        error_samples=error_samples,
    )
    print(
        f"  indicators compute [{market_key}] done: "
        f"success={success} failed={failed} skipped={skipped} status={status}"
    )


def run_compute(
    market_key: str,
    date_str: str | None = None,
    database_url: str | None = None,
    limit: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> None:
    source_provider = price_source_for_market(market_key)
    price_decimals = MARKETS[market_key].price_decimals

    with connect(database_url) as conn:
        target_dates = _resolve_target_dates(conn, market_key, date_str, date_from, date_to)
        if not target_dates:
            return

        instruments = _load_active_instruments(conn, market_key, limit)
        if not instruments:
            print(f"  indicators compute [{market_key}]: no active instruments")
            return

        for trade_date in target_dates:
            _process_date(
                conn, market_key, trade_date, source_provider, price_decimals, instruments,
            )
            # 날짜 단위 커밋 경계 유지 — 중간 실패 시 이전 날짜는 보존
            conn.commit()


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
