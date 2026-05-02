from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import redirect_stdout
from datetime import datetime, timedelta
from functools import lru_cache
from html import escape
import io
import json
from pathlib import Path
import time
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

from market_scanner.indicators import calc_bollinger, calc_macd, calc_rsi, calc_trend
from market_scanner.markets import MARKETS
from market_scanner.models import MarketDefinition, ScanRecord, ScanSettings

TEMPLATE_DIR = Path(__file__).with_name("templates")
ASSET_DIR = Path(__file__).with_name("assets")
NEWS_CACHE_PATH = ASSET_DIR / "news_cache.json"
YFINANCE_CACHE_DIR = ASSET_DIR / ".yfinance_cache"

YFINANCE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
yf.set_tz_cache_location(str(YFINANCE_CACHE_DIR))


def _safe_number(value, digits: int | None = None) -> float | None:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(numeric):
        return None
    return round(numeric, digits) if digits is not None else numeric


def _resolve_metadata(market: MarketDefinition, symbol: str, info: dict) -> tuple[str, str, str, str]:
    static_meta = market.metadata_loader().get(symbol)
    if static_meta:
        return (
            static_meta.name_en,
            static_meta.name_local,
            static_meta.sector,
            static_meta.description,
        )

    name_en = info.get("longName") or info.get("shortName") or symbol
    sector_raw = info.get("sector", "") or "Unknown"
    sector = market.sector_aliases.get(sector_raw, sector_raw)
    summary = (info.get("longBusinessSummary") or "").strip()
    description = summary[:120] if summary else "No description"
    return name_en, name_en, sector, description


def _clean_text(value: object) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def _is_placeholder_text(value: object) -> bool:
    return _clean_text(value).lower() in {"", "-", "nan", "none", "unknown", "no description", "n/a"}


def _is_placeholder_name(value: object, symbol: str) -> bool:
    text = _clean_text(value)
    if _is_placeholder_text(text):
        return True
    normalized = symbol.strip().upper()
    display = normalized.replace(".KS", "").replace(".KQ", "")
    return text.upper() in {normalized, display}


def _has_hangul(value: object) -> bool:
    return any("\uac00" <= char <= "\ud7a3" for char in _clean_text(value))


def _looks_like_english_company_name(value: object, symbol: str) -> bool:
    text = _clean_text(value)
    if _is_placeholder_name(text, symbol) or _has_hangul(text):
        return False
    if not any(char.isalpha() for char in text):
        return False
    upper = text.upper()
    company_markers = (
        " INC", " CORP", " CORPORATION", " CO.", " CO ", " LTD", " LIMITED",
        " HOLDINGS", " ENGINEERING", " CONSTRUCTION", " ELECTRONICS",
        " CHEMICAL", " INDUSTRIES", " FINANCIAL", " INSURANCE",
    )
    return " " in text or any(marker in upper for marker in company_markers)


def _display_symbol_name(row: pd.Series, symbol: str) -> str:
    display = _clean_text(row.get("display_symbol"))
    if symbol.endswith((".KS", ".KQ")):
        if display and display.isdigit():
            return display.zfill(6)
        code = symbol.replace(".KS", "").replace(".KQ", "")
        return code.zfill(6) if code.isdigit() else code
    if display:
        return display
    return symbol.replace(".KS", "").replace(".KQ", "")


def enrich_metadata_frame(frame: pd.DataFrame, market: MarketDefinition) -> pd.DataFrame:
    if frame.empty or "symbol" not in frame.columns:
        return frame

    metadata = market.metadata_loader()
    if not metadata:
        return frame

    enriched = frame.copy()
    if "display_symbol" not in enriched.columns:
        enriched["display_symbol"] = ""
    else:
        enriched["display_symbol"] = enriched["display_symbol"].astype("object")
    for column in ("name_en", "name_local", "sector", "description"):
        if column not in enriched.columns:
            enriched[column] = ""
        else:
            enriched[column] = enriched[column].astype("object")

    for index, row in enriched.iterrows():
        symbol = _clean_text(row.get("symbol"))
        meta = metadata.get(symbol)
        if not symbol:
            continue

        if meta is not None:
            if _is_placeholder_name(row.get("name_en"), symbol) and not _is_placeholder_text(meta.name_en):
                enriched.at[index, "name_en"] = meta.name_en
            if _is_placeholder_name(row.get("name_local"), symbol) and not _is_placeholder_text(meta.name_local):
                enriched.at[index, "name_local"] = meta.name_local
            if _is_placeholder_text(row.get("sector")) and not _is_placeholder_text(meta.sector):
                enriched.at[index, "sector"] = meta.sector
            if _is_placeholder_text(row.get("description")) and not _is_placeholder_text(meta.description):
                enriched.at[index, "description"] = meta.description

        if market.key in {"kospi", "kosdaq"}:
            enriched.at[index, "display_symbol"] = _display_symbol_name(row, symbol)
            local_name = enriched.at[index, "name_local"]
            if _is_placeholder_name(local_name, symbol) or _looks_like_english_company_name(local_name, symbol):
                enriched.at[index, "name_local"] = _display_symbol_name(row, symbol)

    return enriched


def _candle_type(
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


def _is_korea_market(market: MarketDefinition) -> bool:
    return market.key in {"kospi", "kosdaq"}


def _history_start_date(period: str) -> str:
    today = datetime.today().date()
    text = str(period or "").strip().lower()
    try:
        if text.endswith("y"):
            return (today - timedelta(days=int(text[:-1]) * 365 + 30)).isoformat()
        if text.endswith("mo"):
            return (today - timedelta(days=int(text[:-2]) * 31 + 10)).isoformat()
        if text.endswith("d"):
            return (today - timedelta(days=int(text[:-1]) + 10)).isoformat()
    except ValueError:
        pass
    return (today - timedelta(days=760)).isoformat()


def _normalize_history_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()
    normalized = frame.rename(
        columns={
            "open": "Open",
            "high": "High",
            "low": "Low",
            "close": "Close",
            "volume": "Volume",
        }
    ).copy()
    required = ["Open", "High", "Low", "Close", "Volume"]
    if any(column not in normalized.columns for column in required):
        return pd.DataFrame()
    normalized = normalized[required].apply(pd.to_numeric, errors="coerce")
    normalized = normalized.dropna(subset=["Open", "High", "Low", "Close"])
    return normalized.sort_index()


def _korea_symbol_code(symbol: str) -> str:
    return symbol.replace(".KS", "").replace(".KQ", "").zfill(6)


def _fetch_fdr_history(symbol: str, settings: ScanSettings) -> pd.DataFrame:
    try:
        import FinanceDataReader as fdr
    except Exception:
        return pd.DataFrame()

    code = _korea_symbol_code(symbol)
    start = _history_start_date(settings.history_period)
    end = datetime.today().date().isoformat()
    for attempt in range(2):
        if attempt:
            time.sleep(1)
        try:
            with redirect_stdout(io.StringIO()):
                hist = fdr.DataReader(code, start, end)
        except Exception:
            continue
        hist = _normalize_history_frame(hist)
        if not hist.empty:
            return hist
    return pd.DataFrame()


def _fetch_yfinance_history(symbol: str, settings: ScanSettings) -> tuple[pd.DataFrame, yf.Ticker | None]:
    hist = pd.DataFrame()
    ticker: yf.Ticker | None = None
    for attempt in range(3):
        if attempt:
            time.sleep(attempt * 2)
        try:
            ticker = yf.Ticker(symbol)
            hist = _normalize_history_frame(ticker.history(period=settings.history_period))
        except Exception:
            continue
        if not hist.empty:
            break
    return hist, ticker


def _fetch_price_history(
    symbol: str,
    market: MarketDefinition,
    settings: ScanSettings,
    min_history: int,
) -> tuple[pd.DataFrame, yf.Ticker | None]:
    if _is_korea_market(market):
        hist = _fetch_fdr_history(symbol, settings)
        if not hist.empty and len(hist) >= min_history:
            return hist, None
    hist, ticker = _fetch_yfinance_history(symbol, settings)
    if not hist.empty and len(hist) >= min_history:
        return hist, ticker
    return pd.DataFrame(), ticker


def fetch_record(symbol: str, market: MarketDefinition, settings: ScanSettings) -> ScanRecord | None:
    min_history = max(settings.ma_periods) + settings.min_history_buffer
    hist, ticker = _fetch_price_history(symbol, market, settings, min_history)
    if hist.empty:
        return None

    open_series = hist["Open"]
    high_series = hist["High"]
    low_series = hist["Low"]
    close = hist["Close"]
    volume = hist["Volume"]
    current_price = _safe_number(close.iloc[-1], market.price_decimals)
    if current_price is None:
        return None
    open_price = _safe_number(open_series.iloc[-1], market.price_decimals)
    high_price = _safe_number(high_series.iloc[-1], market.price_decimals)
    low_price = _safe_number(low_series.iloc[-1], market.price_decimals)
    close_price = current_price
    previous_close = _safe_number(close.iloc[-2], market.price_decimals) if len(close) >= 2 else None
    change_pct = None
    if previous_close:
        change_pct = round((current_price - previous_close) / previous_close * 100, 2)
    gap_pct = round((open_price - previous_close) / previous_close * 100, 2) if open_price is not None and previous_close else None
    candle_body_pct = round((close_price - open_price) / open_price * 100, 2) if open_price else None
    candle_range_pct = round((high_price - low_price) / open_price * 100, 2) if open_price and high_price is not None and low_price is not None else None
    upper_shadow_pct = (
        round((high_price - max(open_price, close_price)) / open_price * 100, 2)
        if open_price and high_price is not None
        else None
    )
    lower_shadow_pct = (
        round((min(open_price, close_price) - low_price) / open_price * 100, 2)
        if open_price and low_price is not None
        else None
    )
    candle_type = _candle_type(open_price, high_price, low_price, close_price)

    info: dict = {}
    try:
        if ticker is not None:
            info = ticker.info
    except Exception:
        info = {}

    name_en, name_local, sector, description = _resolve_metadata(market, symbol, info)
    rsi = calc_rsi(close)

    trailing_window = min(252, len(close))
    high_52w = _safe_number(close.iloc[-trailing_window:].max(), market.price_decimals)
    low_52w = _safe_number(close.iloc[-trailing_window:].min(), market.price_decimals)
    from_high_pct = None
    if high_52w:
        from_high_pct = round((current_price - high_52w) / high_52w * 100, 1)

    vol_last = _safe_number(volume.iloc[-1])
    vol_avg20 = _safe_number(volume.iloc[-21:-1].mean()) if len(volume) >= 21 else _safe_number(volume.mean())
    volume_ratio = round(vol_last / vol_avg20, 2) if vol_last and vol_avg20 else None

    ma_values: dict[int, float | None] = {}
    ma_diff_pct: dict[int, float | None] = {}
    near_flags: dict[int, bool] = {}
    ma_series: dict[int, pd.Series] = {}
    for period in settings.ma_periods:
        if len(close) < period:
            ma_values[period] = None
            ma_diff_pct[period] = None
            near_flags[period] = False
            continue

        series = close.rolling(window=period).mean()
        ma_series[period] = series
        ma_value = _safe_number(series.iloc[-1], market.price_decimals)
        ma_values[period] = ma_value
        if ma_value:
            diff = round((current_price - ma_value) / ma_value * 100, 2)
            ma_diff_pct[period] = diff
            near_flags[period] = abs(diff) <= settings.threshold_pct
        else:
            ma_diff_pct[period] = None
            near_flags[period] = False

    trend_score, trend = calc_trend(close, ma_values, ma_series, settings.ma_periods)
    macd, macd_signal, macd_hist, macd_state = calc_macd(close)
    bollinger_width_pct, bollinger_percent_b = calc_bollinger(close)
    target_price = _safe_number(info.get("targetMeanPrice"), market.price_decimals)
    trailing_pe = _safe_number(info.get("trailingPE"), 1)
    price_to_book = _safe_number(info.get("priceToBook"), 2)
    roe_raw = _safe_number(info.get("returnOnEquity"), 4)
    growth_raw = _safe_number(info.get("revenueGrowth"), 4)
    return_on_equity = round(roe_raw * 100, 1) if roe_raw is not None else None
    revenue_growth = round(growth_raw * 100, 1) if growth_raw is not None else None
    market_cap = _safe_number(info.get("marketCap"))
    upside_pct = None
    if target_price and current_price:
        upside_pct = round((target_price - current_price) / current_price * 100, 1)

    return ScanRecord(
        symbol=symbol,
        display_symbol=market.display_symbol_builder(symbol),
        name_en=name_en,
        name_local=name_local,
        sector=sector,
        description=description,
        open_price=open_price,
        high_price=high_price,
        low_price=low_price,
        close_price=close_price,
        prev_close=previous_close,
        price=current_price,
        change_pct=change_pct,
        gap_pct=gap_pct,
        candle_body_pct=candle_body_pct,
        candle_range_pct=candle_range_pct,
        upper_shadow_pct=upper_shadow_pct,
        lower_shadow_pct=lower_shadow_pct,
        candle_type=candle_type,
        rsi=rsi,
        high_52w=high_52w,
        low_52w=low_52w,
        from_high_pct=from_high_pct,
        volume_ratio=volume_ratio,
        trailing_pe=trailing_pe,
        price_to_book=price_to_book,
        return_on_equity=return_on_equity,
        revenue_growth=revenue_growth,
        market_cap=market_cap,
        target_price=target_price,
        upside_pct=upside_pct,
        macd=macd,
        macd_signal=macd_signal,
        macd_hist=macd_hist,
        macd_state=macd_state,
        bollinger_width_pct=bollinger_width_pct,
        bollinger_percent_b=bollinger_percent_b,
        trend=trend,
        trend_score=trend_score,
        ma_values=ma_values,
        ma_diff_pct=ma_diff_pct,
        near_flags=near_flags,
    )


def _clamp_score(value: float) -> float:
    return round(max(0.0, min(100.0, value)), 2)


def _score_chart(row: pd.Series, settings: ScanSettings) -> float:
    trend_score = float(row.get("trend_score") or 0)
    near_count = sum(1 for period in settings.ma_periods if bool(row.get(f"near_{period}", False)))
    near_ratio = near_count / max(len(settings.ma_periods), 1)
    diffs = [
        abs(float(row.get(f"diff_{period}")))
        for period in settings.ma_periods
        if pd.notna(row.get(f"diff_{period}"))
    ]
    closest = min(diffs) if diffs else None
    from_high = row.get("from_high_pct")

    score = trend_score * 12 + near_ratio * 20
    if closest is not None:
        if closest <= 2:
            score += 12
        elif closest <= 5:
            score += 7
    if pd.notna(from_high):
        value = float(from_high)
        if -30 <= value <= -5:
            score += 8
        elif value > -5:
            score += 5
        elif value < -45:
            score -= 8
    return _clamp_score(score)


def _score_technical(row: pd.Series) -> float:
    parts: list[float] = []

    rsi = row.get("rsi")
    if pd.notna(rsi):
        value = float(rsi)
        if 40 <= value <= 60:
            parts.append(100)
        elif 30 <= value < 40 or 60 < value <= 68:
            parts.append(75)
        elif value < 30:
            parts.append(45)
        else:
            parts.append(25)

    macd_state = str(row.get("macd_state") or "")
    if macd_state:
        parts.append({
            "Bullish": 100,
            "Positive": 78,
            "Improving": 68,
            "Bearish": 25,
        }.get(macd_state, 50))

    percent_b = row.get("bollinger_percent_b")
    if pd.notna(percent_b):
        value = float(percent_b)
        if 0.2 <= value <= 0.8:
            parts.append(85)
        elif 0 <= value < 0.2:
            parts.append(70)
        elif 0.8 < value <= 1.0:
            parts.append(55)
        else:
            parts.append(30)

    volume = row.get("volume_ratio")
    if pd.notna(volume):
        value = float(volume)
        if 1.2 <= value <= 4.0:
            parts.append(85)
        elif value > 4.0:
            parts.append(65)
        elif value >= 0.8:
            parts.append(55)
        else:
            parts.append(40)

    candle_type = str(row.get("candle_type") or "")
    if candle_type:
        parts.append({
            "Strong Bullish": 90,
            "Bullish Reversal": 88,
            "Bullish": 72,
            "Long Lower Doji": 68,
            "Doji": 55,
            "Long Upper Doji": 38,
            "Bearish": 35,
            "Bearish Rejection": 25,
            "Strong Bearish": 20,
        }.get(candle_type, 50))

    return _clamp_score(sum(parts) / len(parts) if parts else 50)


def _score_fundamental(row: pd.Series) -> float:
    parts: list[float] = []

    pe = row.get("trailing_pe")
    if pd.notna(pe) and float(pe) > 0:
        value = float(pe)
        if value < 10:
            parts.append(92)
        elif value < 20:
            parts.append(82)
        elif value < 30:
            parts.append(65)
        elif value < 50:
            parts.append(45)
        else:
            parts.append(25)

    pbr = row.get("price_to_book")
    if pd.notna(pbr) and float(pbr) > 0:
        value = float(pbr)
        if value < 1:
            parts.append(88)
        elif value < 3:
            parts.append(75)
        elif value < 6:
            parts.append(58)
        else:
            parts.append(35)

    roe = row.get("return_on_equity")
    if pd.notna(roe):
        value = float(roe)
        if value >= 20:
            parts.append(92)
        elif value >= 10:
            parts.append(78)
        elif value > 0:
            parts.append(58)
        else:
            parts.append(25)

    growth = row.get("revenue_growth")
    if pd.notna(growth):
        value = float(growth)
        if value >= 20:
            parts.append(90)
        elif value >= 5:
            parts.append(75)
        elif value >= 0:
            parts.append(55)
        else:
            parts.append(30)

    return _clamp_score(sum(parts) / len(parts) if parts else 50)


def _score_flow(row: pd.Series) -> float:
    parts: list[float] = []

    volume = row.get("volume_ratio")
    if pd.notna(volume):
        value = float(volume)
        if 1.5 <= value <= 5.0:
            parts.append(88)
        elif value > 5.0:
            parts.append(65)
        elif value >= 1.0:
            parts.append(58)
        else:
            parts.append(42)

    from_high = row.get("from_high_pct")
    if pd.notna(from_high):
        value = float(from_high)
        if -30 <= value <= -10:
            parts.append(85)
        elif -10 < value <= 0:
            parts.append(62)
        elif -50 <= value < -30:
            parts.append(58)
        else:
            parts.append(35)

    upside = row.get("upside_pct")
    if pd.notna(upside):
        value = float(upside)
        if value >= 25:
            parts.append(92)
        elif value >= 15:
            parts.append(78)
        elif value >= 5:
            parts.append(60)
        elif value >= 0:
            parts.append(45)
        else:
            parts.append(20)

    change = row.get("change_pct")
    if pd.notna(change):
        value = float(change)
        if value >= 2:
            parts.append(75)
        elif value > 0:
            parts.append(65)
        elif value >= -2:
            parts.append(50)
        else:
            parts.append(32)

    gap = row.get("gap_pct")
    candle_type = str(row.get("candle_type") or "")
    if pd.notna(gap):
        value = float(gap)
        if value > 0 and candle_type in {"Strong Bullish", "Bullish", "Bullish Reversal"}:
            parts.append(78)
        elif value < 0 and candle_type in {"Bullish Reversal", "Long Lower Doji"}:
            parts.append(72)
        elif value > 1.5 and candle_type in {"Bearish Rejection", "Long Upper Doji"}:
            parts.append(35)
        else:
            parts.append(52)

    return _clamp_score(sum(parts) / len(parts) if parts else 50)


def _theme_scores(frame: pd.DataFrame) -> pd.Series:
    if frame.empty or "sector" not in frame.columns:
        return pd.Series(50.0, index=frame.index)

    working = frame.copy()
    working["trend_score"] = pd.to_numeric(working.get("trend_score", pd.Series(dtype=float)), errors="coerce")
    working["change_pct"] = pd.to_numeric(working.get("change_pct", pd.Series(dtype=float)), errors="coerce")
    grouped = (
        working.dropna(subset=["sector"])
        .groupby("sector")
        .agg(count=("sector", "size"), avg_trend=("trend_score", "mean"), avg_change=("change_pct", "mean"))
    )
    if grouped.empty:
        return pd.Series(50.0, index=frame.index)

    scores = (50 + (grouped["avg_trend"].fillna(2.5) - 2.5) * 12 + grouped["avg_change"].fillna(0) * 7)
    grouped["theme_score"] = scores.clip(0, 100)
    return working["sector"].map(grouped["theme_score"]).fillna(50).round(2)


def score_record(row: pd.Series, settings: ScanSettings) -> float:
    chart = float(row.get("chart_score") if pd.notna(row.get("chart_score")) else _score_chart(row, settings))
    technical = float(row.get("technical_score") if pd.notna(row.get("technical_score")) else _score_technical(row))
    fundamental = float(row.get("fundamental_score") if pd.notna(row.get("fundamental_score")) else _score_fundamental(row))
    theme = float(row.get("theme_score") if pd.notna(row.get("theme_score")) else 50)
    flow = float(row.get("flow_score") if pd.notna(row.get("flow_score")) else _score_flow(row))
    return round(chart * 0.30 + technical * 0.25 + fundamental * 0.20 + theme * 0.15 + flow * 0.10, 2)


def add_scoring_columns(frame: pd.DataFrame, settings: ScanSettings) -> pd.DataFrame:
    if frame.empty:
        return frame
    scored = frame.copy()
    scored["chart_score"] = scored.apply(_score_chart, axis=1, settings=settings)
    scored["technical_score"] = scored.apply(_score_technical, axis=1)
    scored["fundamental_score"] = scored.apply(_score_fundamental, axis=1)
    scored["theme_score"] = _theme_scores(scored)
    scored["flow_score"] = scored.apply(_score_flow, axis=1)
    scored["composite_score"] = scored.apply(score_record, axis=1, settings=settings)
    return scored


def records_to_frame(records: list[ScanRecord], settings: ScanSettings) -> pd.DataFrame:
    rows: list[dict] = []
    for record in records:
        row = {
            "symbol": record.symbol,
            "display_symbol": record.display_symbol,
            "name_en": record.name_en,
            "name_local": record.name_local,
            "sector": record.sector,
            "description": record.description,
            "open": record.open_price,
            "high": record.high_price,
            "low": record.low_price,
            "close": record.close_price,
            "prev_close": record.prev_close,
            "price": record.price,
            "change_pct": record.change_pct,
            "gap_pct": record.gap_pct,
            "candle_body_pct": record.candle_body_pct,
            "candle_range_pct": record.candle_range_pct,
            "upper_shadow_pct": record.upper_shadow_pct,
            "lower_shadow_pct": record.lower_shadow_pct,
            "candle_type": record.candle_type,
            "rsi": record.rsi,
            "high_52w": record.high_52w,
            "low_52w": record.low_52w,
            "from_high_pct": record.from_high_pct,
            "volume_ratio": record.volume_ratio,
            "trailing_pe": record.trailing_pe,
            "price_to_book": record.price_to_book,
            "return_on_equity": record.return_on_equity,
            "revenue_growth": record.revenue_growth,
            "market_cap": record.market_cap,
            "target_price": record.target_price,
            "upside_pct": record.upside_pct,
            "macd": record.macd,
            "macd_signal": record.macd_signal,
            "macd_hist": record.macd_hist,
            "macd_state": record.macd_state,
            "bollinger_width_pct": record.bollinger_width_pct,
            "bollinger_percent_b": record.bollinger_percent_b,
            "trend": record.trend,
            "trend_score": record.trend_score,
        }
        for period in settings.ma_periods:
            row[f"ma_{period}"] = record.ma_values.get(period)
            row[f"diff_{period}"] = record.ma_diff_pct.get(period)
            row[f"near_{period}"] = record.near_flags.get(period, False)
        rows.append(row)

    frame = pd.DataFrame(rows)
    if not frame.empty:
        frame["near_count"] = frame[[f"near_{period}" for period in settings.ma_periods]].sum(axis=1)
        frame = add_scoring_columns(frame, settings)
    return frame


def output_paths(market: MarketDefinition, settings: ScanSettings, date_str: str) -> dict[str, Path]:
    base_dir = settings.output_dir / market.key
    base_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{market.output_prefix}_{date_str}"
    return {
        "csv": base_dir / f"{stem}.csv",
        "md": base_dir / f"{stem}.md",
        "html": base_dir / f"{stem}.html",
    }


def scan_market(
    market_key: str,
    settings: ScanSettings,
    symbols: list[str] | None = None,
) -> tuple[MarketDefinition, list[ScanRecord], pd.DataFrame]:
    market = MARKETS[market_key]
    symbols = list(symbols) if symbols is not None else market.universe_loader()
    if settings.symbol_limit is not None and settings.symbol_limit > 0:
        symbols = symbols[: settings.symbol_limit]
    records: list[ScanRecord] = []
    failed: list[str] = []

    total = len(symbols)
    print(f"[scan] {market.label}: {total} symbols")

    worker_count = max(1, min(settings.max_workers, total)) if total else 1
    if worker_count == 1:
        for index, symbol in enumerate(symbols, start=1):
            print(f"  {index:>3}/{total} {symbol:<12} scanning", end="\r")
            record = fetch_record(symbol, market, settings)
            if record:
                records.append(record)
            else:
                failed.append(symbol)
    else:
        print(f"[scan] using {worker_count} workers")
        completed = 0
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            future_map = {
                executor.submit(fetch_record, symbol, market, settings): symbol
                for symbol in symbols
            }
            for future in as_completed(future_map):
                completed += 1
                symbol = future_map[future]
                print(f"  {completed:>3}/{total} {symbol:<12} scanning", end="\r")
                try:
                    record = future.result()
                except Exception:
                    record = None
                if record:
                    records.append(record)
                else:
                    failed.append(symbol)
    print(" " * 72, end="\r")
    print(f"[scan] completed: {len(records)} rows")
    if failed:
        sample = ", ".join(failed[:12])
        suffix = f" (+{len(failed) - 12} more)" if len(failed) > 12 else ""
        print(f"[scan] failed: {len(failed)} symbols - {sample}{suffix}")

    frame = records_to_frame(records, settings)
    return market, records, frame


def _summary_lines_rich(
    frame: pd.DataFrame,
    market: MarketDefinition,
    settings: ScanSettings,
    date_str: str,
) -> list[str]:
    frame = frame.copy()
    near_cols_for_score = [f"near_{period}" for period in settings.ma_periods]
    if "near_count" not in frame.columns and set(near_cols_for_score).issubset(frame.columns):
        frame["near_count"] = frame[near_cols_for_score].sum(axis=1)
    score_columns = {"chart_score", "technical_score", "fundamental_score", "theme_score", "flow_score", "composite_score"}
    if not score_columns.issubset(frame.columns):
        frame = add_scoring_columns(frame, settings)
    if "macd_state" not in frame.columns:
        frame["macd_state"] = "Unknown"
    if "candle_type" not in frame.columns:
        frame["candle_type"] = "Unknown"

    def fmt_num(value, digits: int = 1, suffix: str = "") -> str:
        if value is None or pd.isna(value):
            return "-"
        return f"{float(value):.{digits}f}{suffix}"

    def fmt_price(value) -> str:
        if value is None or pd.isna(value):
            return "-"
        return f"{market.currency_symbol}{float(value):,.{market.price_decimals}f}"

    def ma_tag(row: pd.Series) -> str:
        parts: list[str] = []
        for period in settings.ma_periods:
            if bool(row.get(f"near_{period}", False)):
                diff = row.get(f"diff_{period}")
                if pd.notna(diff):
                    parts.append(f"MA{period} {float(diff):+.1f}%")
        return " / ".join(parts) if parts else "-"

    def candle_text(row: pd.Series) -> str:
        candle = str(row.get("candle_type") or "-")
        if candle == "Unknown":
            candle = "-"
        body = row.get("candle_body_pct")
        gap = row.get("gap_pct")
        parts = [candle]
        if pd.notna(body):
            parts.append(f"몸통 {float(body):+.1f}%")
        if pd.notna(gap):
            parts.append(f"갭 {float(gap):+.1f}%")
        return " / ".join(parts)

    def table_header() -> list[str]:
        return [
            "| 심볼 | 종목명 | 종합 | 차트 | 기술 | 재무 | 추세 | 현재가 | 등락 | 캔들 | RSI | MA 위치 |",
            "|---|---|---:|---:|---:|---:|:---:|---:|---:|---|---:|---|",
        ]

    def table_row(row: pd.Series) -> str:
        return (
            f"| {row.get('display_symbol', '-')}"
            f" | {str(row.get('name_local', '-'))[:18]}"
            f" | {fmt_num(row.get('composite_score'), 0)}"
            f" | {fmt_num(row.get('chart_score'), 0)}"
            f" | {fmt_num(row.get('technical_score'), 0)}"
            f" | {fmt_num(row.get('fundamental_score'), 0)}"
            f" | {_trend_badge_html(row.get('trend'))}"
            f" | {fmt_price(row.get('price'))}"
            f" | {fmt_num(row.get('change_pct'), 2, '%')}"
            f" | {candle_text(row)}"
            f" | {fmt_num(row.get('rsi'), 0)}"
            f" | {ma_tag(row)} |"
        )

    def section_table(lines: list[str], section_df: pd.DataFrame, limit: int | None = None) -> None:
        if section_df.empty:
            lines.append("_해당 종목 없음_")
            lines.append("")
            return
        lines.extend(table_header())
        view = section_df.head(limit) if limit else section_df
        for _, row in view.iterrows():
            lines.append(table_row(row))
        lines.append("")

    def describe_pick(row: pd.Series) -> str:
        reasons: list[str] = []
        near_count = int(row.get("near_count", 0) or 0)
        rsi_value = row.get("rsi")
        upside = row.get("upside_pct")
        pe_value = row.get("trailing_pe")
        from_high = row.get("from_high_pct")
        trend = row.get("trend", "-")
        macd_state = row.get("macd_state")
        candle_type = row.get("candle_type")
        composite = row.get("composite_score")

        if pd.notna(composite):
            reasons.append(
                f"종합 {fmt_num(composite, 0)}점"
                f"(차트 {fmt_num(row.get('chart_score'), 0)}, 기술 {fmt_num(row.get('technical_score'), 0)}, 재무 {fmt_num(row.get('fundamental_score'), 0)})"
            )

        # 1순위: 추세 방향 (방향성이 핵심)
        trend_score = int(row.get("trend_score") or 0)
        if trend_score >= 4:
            reasons.append(f"추세 양호({trend}), MA 배열·기울기 확인")
        elif trend_score == 3:
            reasons.append(f"추세 중립({trend}), 방향성 선택 대기 구간")
        else:
            reasons.append(f"추세 약세({trend}), 반등 여부 확인 필요")

        # 2순위: MA 위치 (필터 통과 맥락)
        if near_count >= 3:
            reasons.append(f"3개 MA 수렴, {ma_tag(row)} 압축 구간")
        elif near_count >= 2:
            reasons.append(f"2개 MA 수렴, {ma_tag(row)} 지지·저항 겹침")
        else:
            reasons.append(f"{ma_tag(row)} 단일 기준선 테스트")

        # 3순위: RSI 타이밍
        if pd.notna(rsi_value):
            r = float(rsi_value)
            rsi_text = f"RSI {fmt_num(rsi_value, 0)}"
            if r >= 70:
                reasons.append(f"{rsi_text} 과열 구간, 추격 매수 주의")
            elif r < 35:
                reasons.append(f"{rsi_text} 극단 과매도, 반등 확인 후 접근")
            elif r < 45:
                reasons.append(f"{rsi_text} 과매도 회복 시도 구간")
            elif r <= 60:
                reasons.append(f"{rsi_text} 부담 없는 진입 구간")

        if macd_state in {"Bullish", "Positive", "Improving"}:
            reasons.append(f"MACD {macd_state}")

        if candle_type in {"Strong Bullish", "Bullish Reversal", "Long Lower Doji"}:
            reasons.append(f"캔들 {candle_type}")
        elif candle_type in {"Bearish Rejection", "Strong Bearish", "Long Upper Doji"}:
            reasons.append(f"캔들 {candle_type}, 단기 매물 확인 필요")

        # 4순위: 업사이드·PER·낙폭
        if pd.notna(upside):
            u = float(upside)
            if u < 0:
                reasons.append(f"업사이드 {fmt_num(upside, 1, '%')} (목표가 하향, 주의)")
            elif u >= 20:
                reasons.append(f"애널리스트 업사이드 {fmt_num(upside, 1, '%')}")

        if pd.notna(pe_value) and 0 < float(pe_value) < 15:
            reasons.append(f"PER {fmt_num(pe_value, 1)} 저평가 구간")

        if pd.notna(from_high) and float(from_high) <= -20:
            reasons.append(f"52주 고점 대비 {fmt_num(from_high, 1, '%')}, 반등 여지")

        return f"- **{row.get('display_symbol')} {row.get('name_local')}**: {' / '.join(reasons[:4])}."

    def sector_commentary(section_df: pd.DataFrame) -> list[str]:
        comments: list[str] = []
        sector_counts = section_df["sector"].fillna("Unknown").value_counts()
        total_count = len(section_df)
        if total_count == 0:
            return comments

        for sector, count in sector_counts.head(3).items():
            sector_df = section_df[section_df["sector"].fillna("Unknown") == sector]
            ratio = count / total_count * 100
            avg_rsi = sector_df["rsi"].dropna().mean()
            avg_upside = sector_df["upside_pct"].dropna().mean()
            leader_symbol = "-"
            if "composite_score" in sector_df.columns and not sector_df.empty:
                leader = sector_df.sort_values("composite_score", ascending=False).iloc[0]
                leader_symbol = str(leader.get("display_symbol", "-"))
            comments.append(
                "- "
                f"**{sector}**: 근접 종목 {int(count)}개({ratio:.1f}%), "
                f"평균 RSI {fmt_num(avg_rsi, 0)}, 평균 업사이드 {fmt_num(avg_upside, 1, '%')}, "
                f"상위 후보는 {leader_symbol}."
            )

        top_ratio = sector_counts.iloc[0] / total_count * 100
        if top_ratio >= 30:
            comments.append(
                f"- 상위 섹터 비중이 {top_ratio:.1f}%로 높아 이번 스캔은 특정 섹터 쏠림이 비교적 강합니다."
            )
        else:
            comments.append(
                f"- 상위 섹터 비중이 {top_ratio:.1f}% 수준이라 섹터 쏠림은 과도하지 않은 편입니다."
            )
        return comments

    lines = [
        f"# {market.label} 시장 스캐너 분석 리포트",
        "",
        f"**기준일:** {date_str}  ",
        f"**유니버스:** {market.label} ({len(frame)}개 종목)  ",
        f"**스코어링:** 차트 30% + 기술지표 25% + 재무 20% + 테마 15% + 수급 10%",
        "",
        "---",
        "",
    ]

    if frame.empty:
        lines.append("데이터가 없습니다.")
        return lines

    near_cols = [f"near_{period}" for period in settings.ma_periods]
    near_any = frame[frame[near_cols].any(axis=1)].copy()
    near_multi = frame[frame["near_count"] >= 2].copy()

    lines.extend(["## 시장 총평", "", "| 구분 | 값 |", "|---|---:|"])
    for period in settings.ma_periods:
        lines.append(f"| MA{period} 근접 | **{int(frame[f'near_{period}'].sum())}개** |")
    lines.append(f"| 2개 이상 동시 근접 | **{len(near_multi)}개** |")
    lines.extend(["", "---", ""])

    total_near = len(near_any)
    total_universe = len(frame)
    near_ratio = (total_near / total_universe * 100) if total_universe else 0.0
    multi_ratio = (len(near_multi) / total_near * 100) if total_near else 0.0
    oversold_count = int((near_any["rsi"].notna() & (near_any["rsi"] < 40)).sum())
    hot_count = int((near_any["rsi"].notna() & (near_any["rsi"] >= 70)).sum())
    avg_rsi = near_any["rsi"].dropna().mean()
    avg_upside = near_any["upside_pct"].dropna().mean()
    avg_from_high = near_any["from_high_pct"].dropna().mean()
    avg_score = frame["composite_score"].dropna().mean() if "composite_score" in frame.columns else None
    avg_chart = frame["chart_score"].dropna().mean() if "chart_score" in frame.columns else None
    avg_technical = frame["technical_score"].dropna().mean() if "technical_score" in frame.columns else None
    avg_fundamental = frame["fundamental_score"].dropna().mean() if "fundamental_score" in frame.columns else None
    trend_counts = near_any["trend"].fillna("Unknown").value_counts()
    dominant_trend = trend_counts.index[0] if not trend_counts.empty else "Unknown"

    lines.extend(
        [
            "## 핵심 해석",
            "",
            f"- 전체 평균 종합점수는 **{fmt_num(avg_score, 0)}점**입니다. 세부 평균은 차트 **{fmt_num(avg_chart, 0)}**, 기술 **{fmt_num(avg_technical, 0)}**, 재무 **{fmt_num(avg_fundamental, 0)}**입니다.",
            f"- 이동평균선 근접 종목은 전체 {total_universe}개 중 {total_near}개로, 스캔 유니버스의 **{near_ratio:.1f}%** 입니다. 복수 MA 근접 비중은 **{multi_ratio:.1f}%** 입니다.",
            f"- 근접 종목 평균 RSI는 **{fmt_num(avg_rsi, 0)}**, 과매도 후보는 **{oversold_count}개**, 과열 경고 구간은 **{hot_count}개** 입니다.",
            f"- 근접 종목 평균 업사이드는 **{fmt_num(avg_upside, 1, '%')}**, 52주 고점 대비 평균 괴리는 **{fmt_num(avg_from_high, 1, '%')}** 입니다.",
            f"- 근접 종목의 대표 추세는 **{dominant_trend}** 입니다. 추세, 기술지표, 재무/테마/수급 점수를 같이 보며 후보를 선별합니다.",
            "",
            "---",
            "",
        ]
    )

    ranked = frame.sort_values(["composite_score", "near_count"], ascending=[False, False]).head(10)
    lines.extend(
        [
            "## 1. 오늘의 핵심 후보",
            "",
            "> PRD 기준 복합 스코어링(차트·기술·재무·테마·수급)을 반영한 전체 유니버스 상위 후보입니다.",
            "",
        ]
    )
    section_table(lines, ranked)
    for _, row in ranked.iterrows():
        lines.append(describe_pick(row))
    lines.extend(["", "---", ""])

    oversold = near_any[
        near_any["rsi"].notna()
        & (near_any["rsi"] < 40)
        & (near_any["trend"] != "Strong Downtrend")
    ].sort_values(["technical_score", "rsi"], ascending=[False, True])
    pullback = near_any[
        near_any["trend_score"].fillna(0).ge(3)
        & near_any["rsi"].notna()
        & near_any["rsi"].between(30, 55)
    ].sort_values(["composite_score", "chart_score"], ascending=[False, False])
    lines.extend(
        [
            "## 2. 전략별 후보",
            "",
            "### A. 상승추세 눌림 포착",
            "",
            "> 추세가 유지되면서 이동평균선 근처로 눌린 종목입니다. PRD의 Pullback in Uptrend 관점입니다.",
            "",
        ]
    )
    section_table(lines, pullback, limit=10)
    if not pullback.empty:
        best = pullback.iloc[0]
        lines.append(
            f"- 눌림목 관점의 선두는 **{best.get('display_symbol')}** 로, "
            f"종합 {fmt_num(best.get('composite_score'), 0)}점과 {ma_tag(best)}가 함께 보입니다."
        )
        lines.append("")

    lines.extend(
        [
            "### B. 과매도 반등 후보",
            "",
            "> RSI 40 미만이면서 이동평균선에 근접해 있는 종목입니다. Strong Downtrend 종목은 제외합니다.",
            "",
        ]
    )
    section_table(lines, oversold, limit=8)
    if not oversold.empty:
        best = oversold.iloc[0]
        lines.append(
            f"- 가장 강한 과매도 후보는 **{best.get('display_symbol')}** 로, RSI {fmt_num(best.get('rsi'), 0)}에서 "
            f"{ma_tag(best)} 구간을 시험 중입니다."
        )
        lines.append("")

    lines.extend(
        [
            "### C. 복수 MA 수렴 구간",
            "",
            "> 단기, 중기, 장기 평균선이 가격 근처로 모인 종목입니다.",
            "",
        ]
    )
    near_multi_sorted = near_multi.sort_values(["near_count", "composite_score"], ascending=[False, False])
    section_table(lines, near_multi_sorted, limit=10)
    if not near_multi_sorted.empty:
        leader = near_multi_sorted.iloc[0]
        lines.append(
            f"- 복수 MA 수렴의 중심 후보는 **{leader.get('display_symbol')}** 이며, "
            f"{ma_tag(leader)} 구간에서 방향성 선택을 앞둔 모습입니다."
        )
        lines.append("")

    growth = near_any[
        near_any["upside_pct"].notna()
        & (near_any["upside_pct"] >= 20)
        & (near_any["rsi"].isna() | (near_any["rsi"] < 65))
    ].sort_values(["flow_score", "upside_pct"], ascending=[False, False])
    lines.extend(
        [
            "### D. 수급·업사이드 개선 구간",
            "",
            "> 업사이드 20% 이상 + RSI 65 미만 종목입니다. 수급 점수와 목표가 여력을 함께 봅니다.",
            "",
        ]
    )
    section_table(lines, growth, limit=10)
    if not growth.empty:
        leader = growth.iloc[0]
        lines.append(
            f"- 성장 기대 구간의 선두는 **{leader.get('display_symbol')}** 로, "
            f"업사이드 {fmt_num(leader.get('upside_pct'), 1, '%')}와 {ma_tag(leader)}가 함께 보입니다."
        )
        lines.append("")

    macd_improving = near_any[
        near_any["macd_state"].isin(["Bullish", "Positive", "Improving"])
    ].sort_values(["technical_score", "composite_score"], ascending=[False, False])
    lines.extend(
        [
            "### E. MACD 개선 후보",
            "",
            "> MACD 히스토그램이 우호적이거나 개선 중인 종목입니다.",
            "",
        ]
    )
    section_table(lines, macd_improving, limit=8)
    if not macd_improving.empty:
        leader = macd_improving.iloc[0]
        lines.append(
            f"- MACD 개선 후보의 선두는 **{leader.get('display_symbol')}** 로, "
            f"MACD 상태는 {leader.get('macd_state')}이고 기술점수는 {fmt_num(leader.get('technical_score'), 0)}점입니다."
        )
        lines.append("")
    lines.extend(["---", ""])

    lines.extend(["## 3. 섹터 분포", ""])
    sector_counts = near_any["sector"].fillna("Unknown").value_counts()
    lines.extend(["| 섹터 | 근접 종목 수 | 비중 |", "|---|---:|---:|"])
    for sector, count in sector_counts.items():
        ratio = (count / len(near_any) * 100) if len(near_any) else 0
        lines.append(f"| {sector} | {int(count)} | {ratio:.1f}% |")
    lines.append("")
    lines.extend(sector_commentary(near_any))
    lines.extend(["", "---", ""])

    hot = near_any[near_any["rsi"].notna() & (near_any["rsi"] >= 70)].sort_values("rsi", ascending=False)
    lines.extend(
        [
            "## 4. 주의 종목",
            "",
            "> RSI 70 이상인데 이동평균선 근처에 있는 경우 단기 과열일 수 있습니다.",
            "",
        ]
    )
    section_table(lines, hot, limit=8)
    if not hot.empty:
        leader = hot.iloc[0]
        lines.append(
            f"- 단기 과열 경계선의 상단은 **{leader.get('display_symbol')}** 이며, "
            f"RSI {fmt_num(leader.get('rsi'), 0)}에서 추격 매수는 신중할 필요가 있습니다."
        )
        lines.append("")
    lines.extend(["---", ""])

    lines.extend(["## 5. 전체 근접 종목 목록", ""])
    for period in settings.ma_periods:
        near_df = frame[frame[f"near_{period}"]].copy()
        diff_col = f"diff_{period}"
        if diff_col not in near_df.columns:
            lines.extend([f"### MA{period} 근접", "", "_기준 컬럼이 없어 목록을 생략했습니다._", ""])
            continue
        near_df["_abs_diff"] = near_df[diff_col].abs()
        near_df = near_df.sort_values("_abs_diff")
        lines.extend([f"### MA{period} 근접 ({len(near_df)}개)", ""])
        section_table(lines, near_df)

    lines.append("*본 리포트는 스캐너 데이터와 규칙 기반 점수로 생성되었으며 투자 조언이 아닙니다. 투자 판단은 본인 책임 하에 이루어져야 합니다.*")
    return lines


def write_markdown(frame: pd.DataFrame, market: MarketDefinition, settings: ScanSettings, date_str: str, path: Path) -> str:
    frame = enrich_metadata_frame(frame, market)
    text = "\n".join(_summary_lines_rich(frame, market, settings, date_str))
    path.write_text(text, encoding="utf-8")
    return text


def _read_template(name: str) -> str:
    return (TEMPLATE_DIR / name).read_text(encoding="utf-8")


_TREND_BADGE: dict[str, tuple[str, str]] = {
    "Strong Uptrend":   ("badge-strong-up",   "⬆⬆"),
    "Uptrend":          ("badge-up",           "⬆"),
    "Neutral":          ("badge-neutral",      "→"),
    "Downtrend":        ("badge-down",         "⬇"),
    "Strong Downtrend": ("badge-strong-down",  "⬇⬇"),
}

def _trend_badge_html(trend: str | None) -> str:
    if not trend:
        return "-"
    cls, arrow = _TREND_BADGE.get(str(trend), ("badge-neutral", "→"))
    return f'<span class="badge {cls}" title="{trend}">{arrow}</span>'


def _render_html_template(context: dict[str, str]) -> str:
    html_template = _read_template("report.html")
    for key, value in context.items():
        html_template = html_template.replace(f"###{key}###", value)
    return html_template


def _json_script(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def _updated_at_text() -> str:
    return datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d %H:%M:%S KST")


def _summary_cards_interactive_html(frame: pd.DataFrame, settings: ScanSettings) -> str:
    card_classes = ["text-info", "text-warning", "text-danger", "text-primary", "text-success", "text-secondary"]
    cards: list[str] = []
    for index, period in enumerate(settings.ma_periods):
        count = int(frame[f"near_{period}"].sum()) if not frame.empty else 0
        tone = card_classes[index % len(card_classes)]
        cards.append(
            "<div class='col-6 col-md-3'><div class='card text-center p-3 stat-card'>"
            f"<div class='text-secondary small'>MA{period} 근접</div>"
            f"<h2 class='{tone}'>{count}</h2>"
            f"<div class='text-secondary small'>+/- {settings.threshold_pct:.0f}% 이내</div>"
            "</div></div>"
        )

    if len(settings.ma_periods) > 1:
        multi_count = int((frame["near_count"] >= 2).sum()) if not frame.empty and "near_count" in frame.columns else 0
        cards.append(
            "<div class='col-6 col-md-3'><div class='card text-center p-3 stat-card'>"
            "<div class='text-secondary small'>복수 MA 수렴</div>"
            f"<h2 class='{card_classes[len(settings.ma_periods) % len(card_classes)]}'>{multi_count}</h2>"
            "<div class='text-secondary small'>2개 이상</div>"
            "</div></div>"
        )
    return "".join(cards)


def _interactive_tab_nav_html(settings: ScanSettings) -> str:
    items = ['<li class="nav-item"><a class="nav-link active" href="#" data-tab="all">전체</a></li>']
    for period in settings.ma_periods:
        items.append(
            f'<li class="nav-item"><a class="nav-link" href="#" data-tab="ma{period}">MA{period}</a></li>'
        )
    if len(settings.ma_periods) > 1:
        items.append('<li class="nav-item"><a class="nav-link" href="#" data-tab="multi">복수MA</a></li>')
    return "".join(items)


def _interactive_table_headers_html(settings: ScanSettings, market: MarketDefinition) -> str:
    currency = escape(market.currency_symbol)
    headers = [
        '<th data-col="ticker">티커</th>',
        '<th data-col="kr_name">종목명</th>',
        '<th data-col="sector">섹터</th>',
        '<th data-col="trend">추세</th>',
        f'<th data-col="price">현재가({currency})</th>',
        '<th data-col="changePct">등락률</th>',
        '<th data-col="candleType">캔들</th>',
        '<th data-col="rsi">RSI</th>',
        '<th data-col="fromHigh">52주고점%</th>',
        '<th data-col="volRatio">거래량비율</th>',
        '<th data-col="per">PER</th>',
        '<th data-col="upside">업사이드</th>',
    ]
    # MA distance columns stay in DATA for charts/setup logic, but are hidden from the stock list for now.
    headers.append("<th>근접</th>")
    return "".join(headers)


def _sector_strength_data(frame: pd.DataFrame) -> tuple[list[str], list[int], list[int], list[int]]:
    if frame.empty or "sector" not in frame.columns or "trend" not in frame.columns:
        return [], [], [], []
    df = frame.copy()
    df["sector"] = df["sector"].fillna("Unknown")
    bull_trends = {"Strong Uptrend", "Uptrend"}
    bear_trends = {"Strong Downtrend", "Downtrend"}
    df["_cat"] = df["trend"].apply(
        lambda t: "bull" if t in bull_trends else ("bear" if t in bear_trends else "neu")
    )
    grouped = df.groupby("sector")["_cat"].value_counts().unstack(fill_value=0)
    for col in ("bull", "neu", "bear"):
        if col not in grouped.columns:
            grouped[col] = 0
    grouped["total"] = grouped["bull"] + grouped["neu"] + grouped["bear"]
    grouped = grouped[grouped["total"] >= 2]
    grouped["bull_ratio"] = grouped["bull"] / grouped["total"]
    grouped = grouped.sort_values("bull_ratio", ascending=True).tail(14)
    labels = grouped.index.tolist()
    return (
        labels,
        [int(v) for v in grouped["bull"].tolist()],
        [int(v) for v in grouped["neu"].tolist()],
        [int(v) for v in grouped["bear"].tolist()],
    )


def _rsi_chart_data(frame: pd.DataFrame) -> tuple[list[str], list[int]]:
    labels = ["<25", "25-30", "30-35", "35-40", "40-45", "45-50", "50-55", "55-60", "60-65", "65-70", "70-75", "75+"]
    if frame.empty or "rsi" not in frame.columns:
        return labels, [0] * len(labels)

    bins = [-float("inf"), 25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 75, float("inf")]
    rsi_values = pd.to_numeric(frame["rsi"], errors="coerce").dropna()
    if rsi_values.empty:
        return labels, [0] * len(labels)

    categories = pd.cut(rsi_values, bins=bins, labels=labels, right=False)
    counts = categories.value_counts(sort=False)
    return labels, [int(counts.get(label, 0)) for label in labels]


def _fear_label_and_note(level: float) -> tuple[str, str]:
    if level < 15:
        return "Calm", "변동성은 낮은 편입니다. 추세가 유지되면 눌림목 선별에 유리합니다."
    if level < 20:
        return "Normal", "변동성은 정상권입니다. 개별 종목 신호 품질을 우선 확인합니다."
    if level < 30:
        return "Elevated", "변동성이 높아진 구간입니다. 포지션 크기와 손절 기준이 중요합니다."
    return "Stress", "시장 스트레스가 큰 구간입니다. 방어적 접근과 현금 비중 점검이 필요합니다."


def _latest_global_indices_csv(date_str: str | None = None) -> Path | None:
    data_dir = Path("data")
    candidates: list[Path] = []
    if date_str:
        candidates.extend([data_dir / f"Data_GlobalIndices_{date_str}.csv", Path(f"Data_GlobalIndices_{date_str}.csv")])
    candidates.extend(sorted(data_dir.glob("Data_GlobalIndices_*.csv"), reverse=True))
    candidates.extend(sorted(Path(".").glob("Data_GlobalIndices_*.csv"), reverse=True))
    return next((path for path in candidates if path.exists()), None)


def _fear_from_scan_data(frame: pd.DataFrame | None, date_str: str | None) -> dict[str, object] | None:
    sources: list[pd.DataFrame] = []
    if frame is not None and not frame.empty:
        sources.append(frame)
    csv_path = _latest_global_indices_csv(date_str)
    if csv_path:
        try:
            sources.append(pd.read_csv(csv_path, encoding="utf-8-sig"))
        except Exception:
            pass

    for source in sources:
        if "symbol" not in source.columns:
            continue
        vix_rows = source[source["symbol"].astype(str) == "^VIX"]
        if vix_rows.empty:
            continue
        row = vix_rows.iloc[0]
        level = _safe_number(row.get("price"), 2)
        if level is None:
            continue
        change_pct = _safe_number(row.get("change_pct"), 1)
        label, note = _fear_label_and_note(level)
        return {
            "available": True,
            "symbol": "^VIX",
            "label": label,
            "level": level,
            "avg20": None,
            "avg60": None,
            "vs20Pct": change_pct,
            "vsLabel": "전일 대비",
            "trend": "rising" if change_pct is not None and change_pct > 0 else ("falling" if change_pct is not None and change_pct < 0 else "unknown"),
            "note": f"{note} VIX 값은 스캔 CSV fallback에서 읽었습니다.",
        }
    return None


def _fear_panel_data(frame: pd.DataFrame | None = None, date_str: str | None = None) -> dict[str, object]:
    fallback = {
        "available": False,
        "symbol": "^VIX",
        "label": "Unavailable",
        "level": None,
        "avg20": None,
        "avg60": None,
        "vs20Pct": None,
        "vsLabel": "20D 대비",
        "trend": "unknown",
        "note": "VIX data could not be loaded in this environment.",
    }
    try:
        hist = yf.Ticker("^VIX").history(period="3mo")
    except Exception:
        return _fear_from_scan_data(frame, date_str) or fallback

    if hist.empty or "Close" not in hist.columns:
        return _fear_from_scan_data(frame, date_str) or fallback

    close = pd.to_numeric(hist["Close"], errors="coerce").dropna()
    if close.empty:
        return _fear_from_scan_data(frame, date_str) or fallback

    level = float(close.iloc[-1])
    avg20 = float(close.tail(20).mean()) if len(close) >= 20 else float(close.mean())
    avg60 = float(close.tail(60).mean()) if len(close) >= 60 else float(close.mean())
    lookback = float(close.iloc[-6]) if len(close) >= 6 else float(close.iloc[0])
    vs20 = ((level - avg20) / avg20 * 100) if avg20 else None

    label, note = _fear_label_and_note(level)

    return {
        "available": True,
        "symbol": "^VIX",
        "label": label,
        "level": round(level, 2),
        "avg20": round(avg20, 2),
        "avg60": round(avg60, 2),
        "vs20Pct": round(vs20, 1) if vs20 is not None else None,
        "vsLabel": "20D 대비",
        "trend": "rising" if level > lookback else "falling",
        "note": note,
    }


def _news_briefing_data(frame: pd.DataFrame, market: MarketDefinition, date_str: str) -> dict[str, object]:
    base = {
        "available": False,
        "title": "뉴스 브리핑",
        "subtitle": "US 밤새 뉴스 수집은 가능하지만, 현재는 뉴스 캐시가 없어서 표시할 항목이 없습니다.",
        "note": "권장 구조: 별도 news 수집 단계에서 yfinance news/RSS/뉴스 API 결과를 캐시하고, 리포트는 캐시만 읽습니다.",
        "items": [],
    }
    if not NEWS_CACHE_PATH.exists():
        return base
    try:
        payload = json.loads(NEWS_CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return base

    raw_items: object = []
    if isinstance(payload, dict):
        dated = payload.get(date_str, payload)
        if isinstance(dated, dict):
            raw_items = dated.get(market.key)
            if raw_items is None and market.key in {"nasdaq100", "sp500", "dow30"}:
                raw_items = dated.get("us")
            if raw_items is None:
                raw_items = dated.get("items", [])
        elif isinstance(dated, list):
            raw_items = dated
    elif isinstance(payload, list):
        raw_items = payload

    if not isinstance(raw_items, list):
        return base

    symbols = set(frame.get("symbol", pd.Series(dtype=str)).astype(str).tolist())
    items: list[dict[str, object]] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        ticker = str(item.get("ticker") or item.get("symbol") or "")
        if ticker and symbols and ticker not in symbols:
            continue
        items.append(
            {
                "ticker": ticker,
                "title": str(item.get("title") or ""),
                "publisher": str(item.get("publisher") or item.get("source") or ""),
                "summary": str(item.get("summary") or item.get("text") or ""),
                "url": str(item.get("url") or item.get("link") or ""),
                "sentiment": str(item.get("sentiment") or "neutral"),
                "publishedAt": str(item.get("publishedAt") or item.get("published_at") or ""),
            }
        )

    if not items:
        return base
    return {
        "available": True,
        "title": "뉴스 브리핑",
        "subtitle": f"{date_str} 기준 캐시된 뉴스 {len(items)}건",
        "note": "뉴스는 캐시 파일 기반으로 표시됩니다. 실시간 요청은 렌더링 안정성을 위해 피합니다.",
        "items": items[:80],
    }


def _interactive_table_data(frame: pd.DataFrame, market: MarketDefinition, settings: ScanSettings) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for _, row in frame.iterrows():
        symbol = str(row.get("symbol", ""))
        payload: dict[str, object] = {
            "ticker": symbol,
            "displayTicker": str(row.get("display_symbol", symbol)),
            "quoteUrl": market.quote_url_builder(symbol),
            "en_name": row.get("name_en"),
            "kr_name": row.get("name_local"),
            "sector": row.get("sector"),
            "desc": row.get("description"),
            "open": _safe_number(row.get("open"), market.price_decimals),
            "high": _safe_number(row.get("high"), market.price_decimals),
            "low": _safe_number(row.get("low"), market.price_decimals),
            "close": _safe_number(row.get("close"), market.price_decimals),
            "prevClose": _safe_number(row.get("prev_close"), market.price_decimals),
            "price": _safe_number(row.get("price"), market.price_decimals),
            "changePct": _safe_number(row.get("change_pct"), 2),
            "gapPct": _safe_number(row.get("gap_pct"), 2),
            "candleBodyPct": _safe_number(row.get("candle_body_pct"), 2),
            "candleRangePct": _safe_number(row.get("candle_range_pct"), 2),
            "upperShadowPct": _safe_number(row.get("upper_shadow_pct"), 2),
            "lowerShadowPct": _safe_number(row.get("lower_shadow_pct"), 2),
            "candleType": row.get("candle_type") or "",
            "rsi": _safe_number(row.get("rsi"), 1),
            "fromHigh": _safe_number(row.get("from_high_pct"), 1),
            "volRatio": _safe_number(row.get("volume_ratio"), 2),
            "per": _safe_number(row.get("trailing_pe"), 1),
            "pbr": _safe_number(row.get("price_to_book"), 2),
            "roe": _safe_number(row.get("return_on_equity"), 1),
            "revenueGrowth": _safe_number(row.get("revenue_growth"), 1),
            "marketCap": _safe_number(row.get("market_cap"), 0),
            "upside": _safe_number(row.get("upside_pct"), 1),
            "score": _safe_number(row.get("composite_score"), 1),
            "chartScore": _safe_number(row.get("chart_score"), 1),
            "technicalScore": _safe_number(row.get("technical_score"), 1),
            "fundamentalScore": _safe_number(row.get("fundamental_score"), 1),
            "themeScore": _safe_number(row.get("theme_score"), 1),
            "flowScore": _safe_number(row.get("flow_score"), 1),
            "macdState": row.get("macd_state") or "",
            "bollingerWidth": _safe_number(row.get("bollinger_width_pct"), 2),
            "bollingerPercentB": _safe_number(row.get("bollinger_percent_b"), 3),
            "trend": row.get("trend") or "",
            "trendScore": int(row.get("trend_score") or 0),
            "nearCount": int(row.get("near_count") or 0),
        }
        for period in settings.ma_periods:
            payload[f"diff_{period}"] = _safe_number(row.get(f"diff_{period}"), 2)
            payload[f"near_{period}"] = bool(row.get(f"near_{period}", False))
        rows.append(payload)
    return rows


def write_html(frame: pd.DataFrame, market: MarketDefinition, settings: ScanSettings, date_str: str, markdown_text: str, path: Path) -> None:
    frame = enrich_metadata_frame(frame, market)
    sector_labels, sector_bull, sector_neu, sector_bear = _sector_strength_data(frame)
    rsi_labels, rsi_values = _rsi_chart_data(frame)
    display_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}" if len(date_str) == 8 else date_str
    html = _render_html_template(
        {
            "TITLE": escape(f"{market.label} Report {date_str}"),
            "HEADING": escape(f"{market.label} MA Scanner"),
            "META": escape(f"{display_date} | {market.label} | {len(frame)} rows"),
            "UPDATED_AT": escape(_updated_at_text()),
            "STYLE": _read_template("report.css"),
            "SUMMARY_CARDS": _summary_cards_interactive_html(frame, settings),
            "TAB_NAV": _interactive_tab_nav_html(settings),
            "TABLE_HEADERS": _interactive_table_headers_html(settings, market),
            "CURRENCY_JSON": _json_script(market.currency_symbol),
            "PERIODS_JSON": _json_script(list(settings.ma_periods)),
            "DATA_JSON": _json_script(_interactive_table_data(frame, market, settings)),
            "SECTOR_LABELS_JSON": _json_script(sector_labels),
            "SECTOR_BULL_JSON": _json_script(sector_bull),
            "SECTOR_NEU_JSON": _json_script(sector_neu),
            "SECTOR_BEAR_JSON": _json_script(sector_bear),
            "RSI_LABELS_JSON": _json_script(rsi_labels),
            "RSI_VALUES_JSON": _json_script(rsi_values),
            "FEAR_JSON": _json_script(_fear_panel_data(frame, date_str)),
            "NEWS_JSON": _json_script(_news_briefing_data(frame, market, date_str)),
            "ANALYSIS_MD_JSON": _json_script(markdown_text or ""),
            "REPORT_EMPTY_TEXT": escape("No analysis markdown was found. Run the analyze stage or the full pipeline first."),
        }
    )
    path.write_text(html, encoding="utf-8")
