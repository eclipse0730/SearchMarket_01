from __future__ import annotations

import argparse
from datetime import date, datetime
from typing import Any

import pandas as pd


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
    atr = true_range.rolling(window=period, min_periods=period).mean()
    return round(float(atr.iloc[-1]), 4) if pd.notna(atr.iloc[-1]) else None


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


def _progress_bar(completed: int, total: int, width: int = 24) -> str:
    if total <= 0:
        return "-" * width
    filled = min(width, int(width * completed / total))
    return "#" * filled + "-" * (width - filled)


def _load_price_history(conn: Any, instrument_id: int, through_date: date) -> pd.DataFrame:
    """DB에서 OHLCV 히스토리를 가져옵니다. (fdr → yfinance 우선순위)"""
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
    frame = pd.DataFrame(
        rows, columns=["trade_date", "Open", "High", "Low", "Close", "Volume"]
    )
    frame["trade_date"] = pd.to_datetime(frame["trade_date"])
    frame = frame.set_index("trade_date")
    return frame.apply(pd.to_numeric, errors="coerce").dropna(subset=["Close"])


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
    high_52w = _safe(close.iloc[-trailing_window:].max(), price_decimals)
    low_52w = _safe(close.iloc[-trailing_window:].min(), price_decimals)
    from_high_pct = round((current - high_52w) / high_52w * 100, 1) if high_52w else None
    from_low_pct = round((current - low_52w) / low_52w * 100, 1) if low_52w else None

    range_highs: dict[int, float | None] = {}
    range_lows: dict[int, float | None] = {}
    breakouts: dict[int, bool] = {}
    for period in _RANGE_PERIODS:
        if len(close) < period:
            range_highs[period] = None
            range_lows[period] = None
            breakouts[period] = False
            continue
        range_high = _safe(close.iloc[-period:].max(), price_decimals)
        range_low = _safe(close.iloc[-period:].min(), price_decimals)
        prior_high = _safe(close.iloc[-period - 1:-1].max(), price_decimals) if len(close) > period else None
        range_highs[period] = range_high
        range_lows[period] = range_low
        breakouts[period] = bool(prior_high and current > prior_high)

    vol_last = _safe(volume_s.iloc[-1]) if volume_s is not None else None
    vol_avg20 = (
        _safe(volume_s.iloc[-21:-1].mean())
        if volume_s is not None and len(volume_s) >= 21 else None
    )
    volume_ratio = round(vol_last / vol_avg20, 2) if vol_last and vol_avg20 else None

    rsi = calc_rsi(close)
    macd, macd_signal, macd_hist, macd_state = calc_macd(close)
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

    trend_score, trend = calc_trend(close, ma_values, ma_series_dict, _TREND_MA_PERIODS)

    return {
        "rsi": rsi,
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
        "macd": macd,
        "macd_signal": macd_signal,
        "macd_hist": macd_hist,
        "macd_state": macd_state,
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
        "breakout_20d": breakouts.get(20, False),
        "breakout_60d": breakouts.get(60, False),
        "volume_ratio": volume_ratio,
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
    }


def compute_for_instrument(
    conn: Any,
    instrument_id: int,
    trade_date: date,
    run_id: str,
    source_provider: str = "fdr",
    price_decimals: int = 2,
) -> tuple[bool, str | None]:
    """단일 종목의 daily_indicators를 계산해 upsert합니다."""
    from market_scanner.storage.db import upsert_daily_indicator

    hist = _load_price_history(conn, instrument_id, trade_date)
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


def run_compute(
    market_key: str,
    date_str: str | None = None,
    explicit_url: str | None = None,
    limit: int | None = None,
) -> None:
    from psycopg.types.json import Jsonb

    from market_scanner.storage.db import (
        connect,
        country_currency_for_market,
        home_market_key,
        price_source_for_market,
    )
    from market_scanner.config.markets import MARKETS

    trade_date = date.today() if not date_str else datetime.strptime(date_str, "%Y%m%d").date()
    source_provider = price_source_for_market(market_key)
    market = MARKETS[market_key]
    price_decimals = market.price_decimals

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

        run_result = conn.execute(
            """
            INSERT INTO collection_runs (
                run_type, market_key, trade_date, source_provider, status, requested_count, params
            )
            VALUES ('indicators', %s, %s, %s, 'running', %s, %s)
            RETURNING run_id
            """,
            (
                home_market_key(market_key),
                trade_date,
                source_provider,
                len(instruments),
                Jsonb({"mode": "compute"}),
            ),
        ).fetchone()
        run_id = str(run_result[0])

        print(f"  indicators compute [{market_key}] {len(instruments)} symbols  run_id={run_id}")

        success, failed, skipped = 0, 0, 0
        error_samples: list[dict[str, Any]] = []

        def print_progress(force: bool = False) -> None:
            processed = success + failed + skipped
            if not force and processed < len(instruments):
                return
            pct = processed / len(instruments) * 100
            bar = _progress_bar(processed, len(instruments))
            print(
                f"\r    [{bar}] {processed}/{len(instruments)} "
                f"{pct:5.1f}% success={success} failed={failed} skipped={skipped}",
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
        conn.execute(
            """
            UPDATE collection_runs
            SET status = %s, finished_at = now(),
                success_count = %s, failed_count = %s, skipped_count = %s,
                error_samples = %s
            WHERE run_id = %s
            """,
            (status, success, failed, skipped, Jsonb(error_samples), run_id),
        )
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
    compute_p.add_argument("--limit", type=int, default=None)

    args = parser.parse_args()
    if args.command == "compute":
        run_compute(args.market, args.date, args.database_url, args.limit)


if __name__ == "__main__":
    main()
