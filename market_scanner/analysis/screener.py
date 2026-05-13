from __future__ import annotations

import argparse
from datetime import datetime
from dataclasses import dataclass, field
from typing import Iterable

import math
import pandas as pd

from market_scanner.config.markets import MARKETS
from market_scanner.domain.market_policy import price_source_for_market
from market_scanner.domain.snapshots import build_market_snapshot, build_sector_snapshots
from market_scanner.models import ScanSettings
from market_scanner.storage.connection import connect
from market_scanner.storage.runs import create_collection_run, finish_run
from market_scanner.storage.screener import latest_indicator_date, load_screen_frame
from market_scanner.storage.screener_results import (
    upsert_market_snapshot,
    upsert_scan_result,
    upsert_sector_snapshots,
)


# ============================================================
# Advanced Screener Scoring Engine
# ------------------------------------------------------------
# 목적:
# - daily_indicators 테이블의 확장 지표를 최대한 활용
# - 단일 composite_score가 아니라 전략별 점수 산출
# - 눌림목 / 신고가 돌파 / 박스권 돌파 / 과매수 / 과매도 / 수급·거래대금 / 테마 / 리스크 분리
#
# 입력 전제:
# - load_screen_frame() 결과 DataFrame에 daily_indicators 컬럼 + sector/fundamental 컬럼 포함
# - 기존 screener.py의 add_scores(frame) 대체 가능
# ============================================================


@dataclass(frozen=True)
class AdvancedScoreSettings:
    ma_periods: tuple[int, ...] = (5, 20, 60, 120, 240)

    # 유동성 필터. 시장별로 외부에서 override 추천.
    min_value_traded: float = 0.0
    strong_value_ratio: float = 2.0
    extreme_value_ratio: float = 4.0

    # 전략별 최종 가중치
    final_weights: dict[str, float] = field(default_factory=lambda: {
        "pullback_score": 0.22,
        "breakout_score": 0.22,
        "box_breakout_score": 0.12,
        "trend_quality_score": 0.14,
        "theme_score": 0.10,
        "fundamental_score": 0.08,
        "flow_score": 0.07,
        "reversal_score": 0.05,
    })

    # 리스크 패널티 반영 강도
    risk_penalty_weight: float = 0.35

    # 점수 캡 정책
    low_liquidity_score_cap: float = 65.0
    severe_downtrend_score_cap: float = 70.0


_DEFAULT_SETTINGS = AdvancedScoreSettings()


# ============================================================
# Common helpers
# ============================================================


def _num(row: pd.Series, col: str, default: float | None = None) -> float | None:
    value = row.get(col)
    if value is None or pd.isna(value):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _bool(row: pd.Series, col: str, default: bool = False) -> bool:
    value = row.get(col)
    if value is None or pd.isna(value):
        return default
    return bool(value)


def _str(row: pd.Series, col: str, default: str = "") -> str:
    value = row.get(col)
    if value is None or pd.isna(value):
        return default
    return str(value)


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    if value is None or pd.isna(value) or math.isnan(float(value)):
        return 0.0
    return round(max(lo, min(hi, float(value))), 2)


def _score_range(value: float | None, bands: list[tuple[float, float]]) -> float:
    """
    bands: [(threshold, score), ...]
    threshold 이상이면 score. threshold는 내림차순 권장.
    """
    if value is None or pd.isna(value):
        return 50.0
    v = float(value)
    for threshold, score in bands:
        if v >= threshold:
            return score
    return bands[-1][1] if bands else 50.0


def _weighted_average(parts: Iterable[tuple[float | None, float]]) -> float:
    total = 0.0
    weight_sum = 0.0
    for score, weight in parts:
        if score is None or pd.isna(score):
            continue
        total += float(score) * weight
        weight_sum += weight
    if weight_sum <= 0:
        return 50.0
    return _clamp(total / weight_sum)


def _diff(row: pd.Series, period: int) -> float | None:
    # 신규 테이블 기준 diff_20_pct 우선, 과거 diff_20 호환
    return _num(row, f"diff_{period}_pct", _num(row, f"diff_{period}"))


def _near_ma_score(row: pd.Series, periods: Iterable[int]) -> float:
    near_count = sum(1 for p in periods if _bool(row, f"near_{p}"))
    total = len(tuple(periods)) or 1
    return _clamp(near_count / total * 100)


def _rsi_zone_score(rsi: float | None, mode: str) -> float:
    if rsi is None:
        return 50.0
    v = float(rsi)

    if mode == "pullback":
        if 42 <= v <= 58:
            return 95
        if 35 <= v < 42 or 58 < v <= 65:
            return 78
        if 30 <= v < 35 or 65 < v <= 72:
            return 60
        if v < 30:
            return 48
        return 30

    if mode == "breakout":
        if 55 <= v <= 72:
            return 95
        if 48 <= v < 55 or 72 < v <= 78:
            return 75
        if 40 <= v < 48:
            return 58
        if v > 82:
            return 35
        return 45

    if mode == "oversold":
        if v <= 25:
            return 95
        if v <= 30:
            return 85
        if v <= 35:
            return 70
        if v <= 45:
            return 55
        return 30

    if mode == "overbought":
        if v >= 85:
            return 95
        if v >= 78:
            return 85
        if v >= 72:
            return 70
        if v >= 65:
            return 55
        return 25

    return 50.0


# ============================================================
# Strategy Scores
# ============================================================


def score_trend_quality(row: pd.Series) -> float:
    """추세 품질: 정배열, 이평선 기울기, 장기 수익률, 52주 위치."""
    ma_align = _num(row, "ma_alignment_score")
    if ma_align is not None and ma_align <= 5:
        ma_align_score = ma_align * 20
    elif ma_align is not None:
        ma_align_score = ma_align
    else:
        ma_align_score = 50

    bullish_align = 100 if _bool(row, "is_ma_bullish_alignment") else 45

    ma20_slope = _num(row, "ma20_slope_pct")
    ma60_slope = _num(row, "ma60_slope_pct")
    slope_score = 50
    if ma20_slope is not None:
        slope_score += 18 if ma20_slope > 0 else -18
        if ma20_slope > 0.5:
            slope_score += 8
    if ma60_slope is not None:
        slope_score += 14 if ma60_slope > 0 else -14
    if ma20_slope is not None and ma60_slope is not None and ma20_slope > ma60_slope:
        slope_score += 8

    r60 = _num(row, "return_60d")
    r120 = _num(row, "return_120d")
    r240 = _num(row, "return_240d")
    return_score = _weighted_average([
        (_score_range(r60, [(30, 95), (15, 82), (5, 68), (0, 55), (-10, 40), (-999, 25)]), 0.30),
        (_score_range(r120, [(50, 95), (25, 82), (8, 68), (0, 55), (-15, 40), (-999, 25)]), 0.35),
        (_score_range(r240, [(80, 95), (40, 82), (15, 68), (0, 55), (-20, 40), (-999, 25)]), 0.35),
    ])

    from_high = _num(row, "from_high_pct")
    from_low = _num(row, "from_low_pct")
    position_score = 50
    if from_high is not None:
        if -25 <= from_high <= -3:
            position_score += 18
        elif from_high > -3:
            position_score += 10
        elif from_high < -50:
            position_score -= 20
    if from_low is not None:
        if from_low >= 40:
            position_score += 12
        elif from_low < 10:
            position_score -= 10

    return _weighted_average([
        (ma_align_score, 0.30),
        (bullish_align, 0.15),
        (_clamp(slope_score), 0.25),
        (return_score, 0.20),
        (_clamp(position_score), 0.10),
    ])


def score_pullback(row: pd.Series) -> float:
    """이평선 눌림: 상승 추세 안에서 20/60선 근처로 조정받는 종목."""
    trend = score_trend_quality(row)

    near20 = 100 if _bool(row, "near_20") else 45
    near60 = 85 if _bool(row, "near_60") else 45
    diff20 = _diff(row, 20)
    diff60 = _diff(row, 60)

    ma_distance_score = 50
    if diff20 is not None:
        if -2.5 <= diff20 <= 3.0:
            ma_distance_score += 35
        elif -5 <= diff20 < -2.5 or 3 < diff20 <= 6:
            ma_distance_score += 18
        elif diff20 < -8:
            ma_distance_score -= 18
    if diff60 is not None:
        if -3.5 <= diff60 <= 5:
            ma_distance_score += 12
        elif diff60 < -8:
            ma_distance_score -= 12

    rsi_score = _weighted_average([
        (_rsi_zone_score(_num(row, "rsi14"), "pullback"), 0.60),
        (_rsi_zone_score(_num(row, "rsi5"), "pullback"), 0.25),
        (_rsi_zone_score(_num(row, "rsi30"), "pullback"), 0.15),
    ])

    # 눌림에서는 거래량이 과하게 죽지 않으면서도 폭증하지 않는 것이 좋음
    vol = _num(row, "volume_ratio")
    val_ratio = _num(row, "value_ratio_20d")
    volume_score = 50
    if vol is not None:
        if 0.65 <= vol <= 1.5:
            volume_score += 28
        elif 1.5 < vol <= 3.0:
            volume_score += 15
        elif vol > 5:
            volume_score -= 15
        elif vol < 0.4:
            volume_score -= 10
    if val_ratio is not None:
        if 0.7 <= val_ratio <= 1.8:
            volume_score += 14
        elif val_ratio > 4:
            volume_score -= 8

    candle = _str(row, "candle_type")
    candle_score = {
        "Bullish Reversal": 90,
        "Long Lower Doji": 82,
        "Bullish": 75,
        "Doji": 60,
        "Bearish": 42,
        "Bearish Rejection": 30,
        "Strong Bearish": 22,
    }.get(candle, 50)

    return _weighted_average([
        (trend, 0.30),
        (_clamp(ma_distance_score), 0.25),
        (max(near20, near60), 0.10),
        (rsi_score, 0.18),
        (_clamp(volume_score), 0.10),
        (candle_score, 0.07),
    ])


def score_breakout(row: pd.Series) -> float:
    """신고가/고점 돌파: 20/60일 돌파 + 거래대금 + 추세 품질."""
    trend = score_trend_quality(row)

    breakout_score = 35
    if _bool(row, "breakout_20d"):
        breakout_score += 22
    if _bool(row, "breakout_60d"):
        breakout_score += 25
    if _bool(row, "breakout_high_20d"):
        breakout_score += 10
    if _bool(row, "breakout_high_60d"):
        breakout_score += 12

    close_pos20 = _num(row, "close_position_in_range_20d")
    close_pos60 = _num(row, "close_position_in_range_60d")
    close_position_score = _weighted_average([
        (_score_range(close_pos20, [(0.90, 95), (0.80, 84), (0.65, 68), (0.50, 55), (0.0, 35), (-999, 30)]), 0.55),
        (_score_range(close_pos60, [(0.90, 95), (0.80, 84), (0.65, 68), (0.50, 55), (0.0, 35), (-999, 30)]), 0.45),
    ])

    volume_score = _weighted_average([
        (_score_range(_num(row, "volume_ratio"), [(5, 78), (3, 95), (1.8, 82), (1.2, 68), (0.8, 50), (-999, 32)]), 0.45),
        (_score_range(_num(row, "value_ratio_20d"), [(5, 82), (3, 96), (1.8, 84), (1.2, 68), (0.8, 50), (-999, 32)]), 0.55),
    ])

    macd_state = _str(row, "macd_state")
    macd_cross = _str(row, "macd_cross")
    macd_hist_change = _num(row, "macd_hist_change")
    macd_score = {
        "Bullish": 92,
        "Positive": 78,
        "Improving": 70,
        "Bearish": 25,
    }.get(macd_state, 50)
    if macd_cross == "golden":
        macd_score += 12
    elif macd_cross == "dead":
        macd_score -= 18
    if macd_hist_change is not None:
        macd_score += 8 if macd_hist_change > 0 else -8

    rsi_score = _rsi_zone_score(_num(row, "rsi14"), "breakout")

    return _weighted_average([
        (_clamp(breakout_score), 0.25),
        (close_position_score, 0.18),
        (volume_score, 0.22),
        (trend, 0.18),
        (_clamp(macd_score), 0.10),
        (rsi_score, 0.07),
    ])


def score_box_breakout(row: pd.Series) -> float:
    """박스권 돌파: 변동성 수축 후 상단 돌파 후보."""
    width = _num(row, "bollinger_width_pct")
    atr_pct = _num(row, "atr14_pct")
    vol20 = _num(row, "volatility_20d")
    vol60 = _num(row, "volatility_60d")

    # 낮은 변동성/수축을 긍정적으로 평가. 단위는 데이터마다 달라서 넓은 기준 사용.
    contraction_score = 50
    if width is not None:
        if width <= 8:
            contraction_score += 25
        elif width <= 15:
            contraction_score += 15
        elif width >= 35:
            contraction_score -= 15
    if atr_pct is not None:
        if atr_pct <= 3:
            contraction_score += 18
        elif atr_pct <= 5:
            contraction_score += 8
        elif atr_pct >= 10:
            contraction_score -= 15
    if vol20 is not None and vol60 is not None:
        contraction_score += 12 if vol20 < vol60 else -8

    close_pos20 = _num(row, "close_position_in_range_20d")
    close_pos60 = _num(row, "close_position_in_range_60d")
    upper_range_score = _weighted_average([
        (_score_range(close_pos20, [(0.85, 92), (0.70, 76), (0.55, 60), (0.30, 45), (-999, 25)]), 0.6),
        (_score_range(close_pos60, [(0.80, 88), (0.65, 72), (0.50, 58), (0.30, 45), (-999, 25)]), 0.4),
    ])

    trigger_score = 45
    if _bool(row, "breakout_high_20d"):
        trigger_score += 25
    if _bool(row, "breakout_20d"):
        trigger_score += 20
    if _num(row, "value_ratio_20d") is not None and _num(row, "value_ratio_20d") >= 1.5:
        trigger_score += 12

    return _weighted_average([
        (_clamp(contraction_score), 0.32),
        (upper_range_score, 0.28),
        (_clamp(trigger_score), 0.25),
        (score_trend_quality(row), 0.15),
    ])


def score_reversal(row: pd.Series) -> float:
    """과매도 반등: 단기 RSI 과매도 + 아래꼬리/반등 캔들 + 거래대금."""
    rsi2 = _num(row, "rsi2")
    rsi5 = _num(row, "rsi5")
    rsi14 = _num(row, "rsi14")
    rsi_score = _weighted_average([
        (_rsi_zone_score(rsi2, "oversold"), 0.45),
        (_rsi_zone_score(rsi5, "oversold"), 0.35),
        (_rsi_zone_score(rsi14, "oversold"), 0.20),
    ])

    from_low = _num(row, "from_low_pct")
    from_high = _num(row, "from_high_pct")
    position_score = 50
    if from_low is not None:
        if from_low <= 8:
            position_score += 20
        elif from_low <= 20:
            position_score += 10
        elif from_low > 80:
            position_score -= 10
    if from_high is not None and from_high < -45:
        position_score += 8

    candle = _str(row, "candle_type")
    candle_score = {
        "Bullish Reversal": 94,
        "Long Lower Doji": 88,
        "Doji": 62,
        "Bullish": 70,
        "Strong Bullish": 75,
        "Bearish": 35,
        "Strong Bearish": 20,
    }.get(candle, 50)

    volume_score = _weighted_average([
        (_score_range(_num(row, "volume_ratio"), [(3, 90), (1.5, 78), (1.0, 60), (0.6, 48), (-999, 35)]), 0.45),
        (_score_range(_num(row, "value_ratio_20d"), [(3, 92), (1.5, 78), (1.0, 60), (0.6, 48), (-999, 35)]), 0.55),
    ])

    return _weighted_average([
        (rsi_score, 0.35),
        (_clamp(position_score), 0.20),
        (candle_score, 0.20),
        (volume_score, 0.15),
        (100 - score_trend_quality(row), 0.10),
    ])


def score_overbought(row: pd.Series) -> float:
    """과매수/과열 점수. 높을수록 과열 경고."""
    rsi_score = _weighted_average([
        (_rsi_zone_score(_num(row, "rsi14"), "overbought"), 0.55),
        (_rsi_zone_score(_num(row, "rsi5"), "overbought"), 0.30),
        (_rsi_zone_score(_num(row, "rsi2"), "overbought"), 0.15),
    ])

    dist_score = 35
    diff20 = _diff(row, 20)
    diff60 = _diff(row, 60)
    if diff20 is not None:
        if diff20 >= 20:
            dist_score += 35
        elif diff20 >= 12:
            dist_score += 25
        elif diff20 >= 7:
            dist_score += 12
    if diff60 is not None:
        if diff60 >= 35:
            dist_score += 25
        elif diff60 >= 20:
            dist_score += 15

    upper_tail = _num(row, "candle_upper_shadow_pct", _num(row, "upper_shadow_pct"))
    candle = _str(row, "candle_type")
    rejection_score = 45
    if candle in {"Bearish Rejection", "Long Upper Doji"}:
        rejection_score += 35
    if upper_tail is not None and upper_tail >= 40:
        rejection_score += 18

    return _weighted_average([
        (rsi_score, 0.40),
        (_clamp(dist_score), 0.35),
        (_clamp(rejection_score), 0.25),
    ])


def score_flow(row: pd.Series, settings: AdvancedScoreSettings = _DEFAULT_SETTINGS) -> float:
    """수급 대체 점수: 현재 테이블 기준 실제 외인/기관이 없으므로 거래대금/거래량 기반 흐름 점수."""
    value_traded = _num(row, "value_traded")
    value_ratio = _num(row, "value_ratio_20d")
    volume_ratio = _num(row, "volume_ratio")
    change = _num(row, "change_pct")
    close_pos = _num(row, "close_position_in_range_20d")

    liquidity_score = 50
    if value_traded is not None and settings.min_value_traded > 0:
        if value_traded >= settings.min_value_traded * 3:
            liquidity_score = 92
        elif value_traded >= settings.min_value_traded:
            liquidity_score = 75
        elif value_traded >= settings.min_value_traded * 0.5:
            liquidity_score = 55
        else:
            liquidity_score = 25

    activity_score = _weighted_average([
        (_score_range(value_ratio, [(settings.extreme_value_ratio, 86), (settings.strong_value_ratio, 94), (1.3, 75), (0.8, 55), (-999, 35)]), 0.60),
        (_score_range(volume_ratio, [(5, 82), (3, 92), (1.5, 76), (1.0, 58), (-999, 36)]), 0.40),
    ])

    quality_score = 50
    if change is not None:
        quality_score += 18 if change > 0 else -12
    if close_pos is not None:
        quality_score += 18 if close_pos >= 0.75 else -8 if close_pos <= 0.35 else 5

    return _weighted_average([
        (liquidity_score, 0.25),
        (activity_score, 0.45),
        (_clamp(quality_score), 0.30),
    ])


# ============================================================
# Fundamentals / Theme
# ============================================================


def score_fundamental_absolute(row: pd.Series) -> float:
    pe = _num(row, "trailing_pe")
    pbr = _num(row, "price_to_book")
    roe = _num(row, "return_on_equity")
    growth = _num(row, "revenue_growth")

    pe_score = None
    if pe is not None and pe > 0:
        pe_score = 92 if pe < 10 else 82 if pe < 20 else 65 if pe < 30 else 45 if pe < 50 else 25

    pbr_score = None
    if pbr is not None and pbr > 0:
        pbr_score = 88 if pbr < 1 else 75 if pbr < 3 else 58 if pbr < 6 else 35

    roe_score = None
    if roe is not None:
        roe_score = 92 if roe >= 20 else 78 if roe >= 10 else 58 if roe > 0 else 25

    growth_score = None
    if growth is not None:
        growth_score = 90 if growth >= 20 else 75 if growth >= 5 else 55 if growth >= 0 else 30

    return _weighted_average([
        (pe_score, 0.22),
        (pbr_score, 0.18),
        (roe_score, 0.30),
        (growth_score, 0.30),
    ])


def sector_relative_fundamental_scores(frame: pd.DataFrame) -> pd.Series:
    if frame.empty or "sector" not in frame.columns:
        return pd.Series(50.0, index=frame.index)

    work = frame.copy()
    for col in ["trailing_pe", "price_to_book", "return_on_equity", "revenue_growth"]:
        work[col] = pd.to_numeric(work[col], errors="coerce") if col in work.columns else pd.NA

    def rel(column: str, higher_is_better: bool, positive_only: bool = False) -> pd.Series:
        scores = pd.Series(float("nan"), index=work.index, dtype="float64")
        values = work[column]
        valid = work["sector"].notna() & values.notna()
        if positive_only:
            valid &= values > 0
        for _, sector_values in values[valid].groupby(work.loc[valid, "sector"]):
            count = len(sector_values)
            if count == 1:
                scores.loc[sector_values.index] = 50.0
            else:
                ranks = sector_values.rank(method="average", ascending=not higher_is_better)
                scores.loc[sector_values.index] = ((ranks - 1) / (count - 1) * 100).clip(0, 100)
        return scores

    components = pd.DataFrame(index=work.index)
    components["pe"] = rel("trailing_pe", higher_is_better=False, positive_only=True)
    components["pbr"] = rel("price_to_book", higher_is_better=False, positive_only=True)
    components["roe"] = rel("return_on_equity", higher_is_better=True)
    components["growth"] = rel("revenue_growth", higher_is_better=True)

    weights = {"pe": 0.20, "pbr": 0.15, "roe": 0.35, "growth": 0.30}
    weighted_sum = pd.Series(0.0, index=work.index, dtype="float64")
    available_weight = pd.Series(0.0, index=work.index, dtype="float64")
    for col, weight in weights.items():
        valid = components[col].notna()
        weighted_sum.loc[valid] += components.loc[valid, col] * weight
        available_weight.loc[valid] += weight

    raw = (weighted_sum / available_weight).where(available_weight > 0, 50.0)
    valid_counts = components.notna().any(axis=1).groupby(work["sector"]).transform("sum").fillna(0)
    confidence = (valid_counts / 10).clip(upper=1.0)
    return (50 + (raw - 50) * confidence).fillna(50).round(2)


def theme_scores(frame: pd.DataFrame) -> pd.Series:
    if frame.empty or "sector" not in frame.columns:
        return pd.Series(50.0, index=frame.index)

    work = frame.copy()
    numeric_cols = [
        "return_5d", "return_20d", "return_60d", "volume_ratio", "value_ratio_20d",
        "ma_alignment_score", "close_position_in_range_20d", "trend_score",
    ]
    for col in numeric_cols:
        work[col] = pd.to_numeric(work[col], errors="coerce") if col in work.columns else pd.NA

    if "diff_20_pct" in work.columns:
        diff20 = work["diff_20_pct"]
    elif "diff_20" in work.columns:
        diff20 = work["diff_20"]
    else:
        diff20 = pd.Series(pd.NA, index=work.index, dtype="float64")
    work["above_ma20"] = pd.to_numeric(diff20, errors="coerce") > 0
    work["breakout_20d_num"] = work["breakout_20d"].apply(lambda v: 1.0 if bool(v) and pd.notna(v) else 0.0) if "breakout_20d" in work.columns else pd.NA
    work["breakout_60d_num"] = work["breakout_60d"].apply(lambda v: 1.0 if bool(v) and pd.notna(v) else 0.0) if "breakout_60d" in work.columns else pd.NA

    grouped = (
        work.dropna(subset=["sector"])
        .groupby("sector")
        .agg(
            sector_count=("sector", "size"),
            avg_return_5d=("return_5d", "mean"),
            avg_return_20d=("return_20d", "mean"),
            avg_return_60d=("return_60d", "mean"),
            avg_volume_ratio=("volume_ratio", "mean"),
            avg_value_ratio=("value_ratio_20d", "mean"),
            above_ma20_ratio=("above_ma20", "mean"),
            breakout20_ratio=("breakout_20d_num", "mean"),
            breakout60_ratio=("breakout_60d_num", "mean"),
            avg_close_position=("close_position_in_range_20d", "mean"),
            avg_trend=("trend_score", "mean"),
        )
    )
    if grouped.empty:
        return pd.Series(50.0, index=frame.index)
    for column in grouped.columns:
        if column != "sector_count":
            grouped[column] = pd.to_numeric(grouped[column], errors="coerce")

    m5 = work["return_5d"].mean()
    m20 = work["return_20d"].mean()
    m60 = work["return_60d"].mean()

    s5 = (50 + (grouped["avg_return_5d"] - (0 if pd.isna(m5) else m5)).fillna(0) * 4.0).clip(0, 100)
    s20 = (50 + (grouped["avg_return_20d"] - (0 if pd.isna(m20) else m20)).fillna(0) * 2.5).clip(0, 100)
    s60 = (50 + (grouped["avg_return_60d"] - (0 if pd.isna(m60) else m60)).fillna(0) * 1.5).clip(0, 100)
    breadth = (grouped["above_ma20_ratio"].fillna(0.5) * 100).clip(0, 100)
    activity = (50 + (grouped["avg_value_ratio"].fillna(grouped["avg_volume_ratio"]).fillna(1.0) - 1.0) * 28).clip(0, 100)
    breakout = (45 + grouped["breakout20_ratio"].fillna(0) * 85 + grouped["breakout60_ratio"].fillna(0) * 65).clip(0, 100)
    position = (grouped["avg_close_position"].fillna(0.5) * 100).clip(0, 100)
    trend = (grouped["avg_trend"].fillna(2.5) * 20).clip(0, 100)

    raw = s20 * 0.22 + s5 * 0.16 + s60 * 0.14 + breadth * 0.16 + activity * 0.16 + breakout * 0.10 + position * 0.04 + trend * 0.02
    confidence = (grouped["sector_count"] / 10).clip(upper=1.0)
    grouped["theme_score"] = (50 + (raw - 50) * confidence).clip(0, 100)
    return pd.to_numeric(work["sector"].map(grouped["theme_score"]), errors="coerce").fillna(50).round(2)


# ============================================================
# Risk / Labels / Final
# ============================================================


def score_risk(row: pd.Series, settings: AdvancedScoreSettings = _DEFAULT_SETTINGS) -> float:
    """높을수록 위험. 최종점수에서 차감."""
    risk = 0.0

    # 유동성 리스크
    value_traded = _num(row, "value_traded")
    if settings.min_value_traded > 0 and value_traded is not None and value_traded < settings.min_value_traded:
        risk += 18

    # 과열 리스크
    overbought = score_overbought(row)
    if overbought >= 80:
        risk += 18
    elif overbought >= 70:
        risk += 10

    # 추세 훼손
    diff20 = _diff(row, 20)
    diff60 = _diff(row, 60)
    diff240 = _diff(row, 240)
    if diff20 is not None and diff20 < -5:
        risk += 10
    if diff60 is not None and diff60 < -8:
        risk += 12
    if diff240 is not None and diff240 < -10:
        risk += 12

    # MACD 악화
    if _str(row, "macd_cross") == "dead":
        risk += 10
    if _str(row, "macd_state") == "Bearish":
        risk += 8
    hist_change = _num(row, "macd_hist_change")
    if hist_change is not None and hist_change < 0:
        risk += 4

    # 캔들 리스크
    candle = _str(row, "candle_type")
    if candle in {"Bearish Rejection", "Strong Bearish"}:
        risk += 14
    elif candle in {"Long Upper Doji", "Bearish"}:
        risk += 8

    # 변동성 과열
    atr_pct = _num(row, "atr14_pct")
    if atr_pct is not None:
        if atr_pct >= 12:
            risk += 12
        elif atr_pct >= 8:
            risk += 6

    # 갭상승 실패 가능성
    gap = _num(row, "gap_pct")
    change = _num(row, "change_pct")
    close_pos = _num(row, "close_position_in_range_20d")
    if gap is not None and change is not None and close_pos is not None:
        if gap > 2 and change < 0 and close_pos < 0.5:
            risk += 14

    return _clamp(risk)


def score_setup_label(row: pd.Series) -> str:
    scores = {
        "이평선 눌림": _num(row, "pullback_score", 0),
        "신고가/고점 돌파": _num(row, "breakout_score", 0),
        "박스권 돌파": _num(row, "box_breakout_score", 0),
        "과매도 반등": _num(row, "reversal_score", 0),
        "추세 우량": _num(row, "trend_quality_score", 0),
    }
    label, value = max(scores.items(), key=lambda kv: kv[1])
    if value < 55:
        return "중립/관망"
    return label


_PULLBACK_MA_PERIODS: tuple[int, ...] = (20, 60, 120, 240)


def _pullback_period_hits(row: pd.Series) -> list[int]:
    """Return MA periods (20/60/120/240) where the price is currently near the MA."""
    return [p for p in _PULLBACK_MA_PERIODS if _bool(row, f"near_{p}")]


def compute_pullback_ma_period(row: pd.Series) -> int | None:
    """가장 짧은 눌림 MA 기간. pullback_score가 충분히 높을 때만 의미가 있음."""
    if _num(row, "pullback_score", 0) < 75:
        return None
    hits = _pullback_period_hits(row)
    return hits[0] if hits else None


def make_signal_tags(row: pd.Series) -> str:
    tags: list[str] = []
    if _num(row, "pullback_score", 0) >= 75:
        hits = _pullback_period_hits(row)
        if hits:
            tags.extend(f"눌림{p}" for p in hits)
        else:
            tags.append("눌림")
    if _num(row, "breakout_score", 0) >= 75:
        tags.append("돌파")
    if _num(row, "box_breakout_score", 0) >= 72:
        tags.append("박스권")
    if _num(row, "theme_score", 0) >= 72:
        tags.append("테마강세")
    if _num(row, "flow_score", 0) >= 75:
        tags.append("거래대금")
    if _num(row, "reversal_score", 0) >= 75:
        tags.append("과매도반등")
    if _num(row, "overbought_score", 0) >= 75:
        tags.append("과열주의")
    if _num(row, "risk_score", 0) >= 55:
        tags.append("리스크")
    return ",".join(tags)


def apply_score_caps(row: pd.Series, raw_score: float, settings: AdvancedScoreSettings) -> float:
    score = raw_score

    value_traded = _num(row, "value_traded")
    if settings.min_value_traded > 0 and value_traded is not None and value_traded < settings.min_value_traded:
        score = min(score, settings.low_liquidity_score_cap)

    trend_quality = _num(row, "trend_quality_score")
    diff240 = _diff(row, 240)
    if trend_quality is not None and trend_quality < 35 and diff240 is not None and diff240 < -10:
        score = min(score, settings.severe_downtrend_score_cap)

    return _clamp(score)


def add_advanced_scores(frame: pd.DataFrame, settings: AdvancedScoreSettings = _DEFAULT_SETTINGS) -> pd.DataFrame:
    if frame.empty:
        return frame

    scored = frame.copy()

    # 개별 전략 점수
    scored["trend_quality_score"] = scored.apply(score_trend_quality, axis=1)
    scored["pullback_score"] = scored.apply(score_pullback, axis=1)
    scored["breakout_score"] = scored.apply(score_breakout, axis=1)
    scored["box_breakout_score"] = scored.apply(score_box_breakout, axis=1)
    scored["reversal_score"] = scored.apply(score_reversal, axis=1)
    scored["overbought_score"] = scored.apply(score_overbought, axis=1)
    scored["flow_score"] = scored.apply(score_flow, axis=1, settings=settings)

    # 재무/테마
    abs_fund = scored.apply(score_fundamental_absolute, axis=1)
    rel_fund = sector_relative_fundamental_scores(scored)
    scored["fundamental_score"] = (abs_fund * 0.40 + rel_fund * 0.60).round(2)
    scored["theme_score"] = theme_scores(scored)

    # 리스크
    scored["risk_score"] = scored.apply(score_risk, axis=1, settings=settings)

    # 원점수
    raw = pd.Series(0.0, index=scored.index, dtype="float64")
    weight_sum = 0.0
    for col, weight in settings.final_weights.items():
        if col in scored.columns:
            raw += pd.to_numeric(scored[col], errors="coerce").fillna(50) * weight
            weight_sum += weight
    if weight_sum <= 0:
        scored["raw_composite_score"] = 50.0
    else:
        scored["raw_composite_score"] = (raw / weight_sum).round(2)

    # 과열은 무조건 나쁜 것은 아니므로 직접 차감하지 않고, risk를 통해 제한적으로 반영
    scored["composite_score"] = (
        scored["raw_composite_score"]
        - scored["risk_score"] * settings.risk_penalty_weight
    ).round(2)

    scored["composite_score"] = scored.apply(
        lambda row: apply_score_caps(row, _num(row, "composite_score", 0) or 0, settings),
        axis=1,
    )

    scored["setup_label"] = scored.apply(score_setup_label, axis=1)
    scored["pullback_ma_period"] = scored.apply(compute_pullback_ma_period, axis=1)
    scored["signal_tags"] = scored.apply(make_signal_tags, axis=1)

    # 실전 랭킹 보조 컬럼
    scored["action_score"] = scored[[
        "pullback_score",
        "breakout_score",
        "box_breakout_score",
        "reversal_score",
    ]].max(axis=1).round(2)

    scored["quality_score"] = scored[[
        "trend_quality_score",
        "fundamental_score",
        "theme_score",
        "flow_score",
    ]].mean(axis=1).round(2)

    return scored


def add_scores(
    frame: pd.DataFrame,
    settings: ScanSettings | AdvancedScoreSettings = _DEFAULT_SETTINGS,
) -> pd.DataFrame:
    if frame.empty:
        return frame
    advanced_settings = settings if isinstance(settings, AdvancedScoreSettings) else _DEFAULT_SETTINGS
    scored = add_advanced_scores(frame, settings=advanced_settings)

    # scan_results and reports still expose the legacy score columns.
    # Map the advanced engine's strategy scores into those columns for compatibility.
    scored["chart_score"] = scored["trend_quality_score"]
    scored["technical_score"] = scored["action_score"]
    scored["momentum_score"] = scored["flow_score"]
    return scored


def rank_advanced(frame: pd.DataFrame, settings: AdvancedScoreSettings = _DEFAULT_SETTINGS) -> pd.DataFrame:
    scored = add_scores(frame, settings=settings)
    if scored.empty:
        return scored
    return scored.sort_values(
        ["composite_score", "action_score", "quality_score"],
        ascending=[False, False, False],
        na_position="last",
    ).reset_index(drop=True)


def run_screen(
    market_key: str,
    date_str: str | None = None,
    universe_key: str | None = None,
    database_url: str | None = None,
) -> pd.DataFrame:
    effective_universe = universe_key or market_key
    source_provider = price_source_for_market(market_key)

    with connect(database_url) as conn:
        if date_str:
            trade_date = datetime.strptime(date_str, "%Y%m%d").date()
        else:
            latest_date = latest_indicator_date(conn, market_key, universe_key)
            if latest_date is None:
                print(
                    f"  screener [{market_key}/{effective_universe}]: no indicator data. "
                    "Run 'prices fetch' and 'indicators compute' first."
                )
                return pd.DataFrame()
            trade_date = latest_date
            print(f"  screener [{market_key}/{effective_universe}]: using latest indicator date {trade_date}")

        frame = load_screen_frame(conn, market_key, trade_date, universe_key)
        if frame.empty:
            print(
                f"  screener [{market_key}]: no data for {trade_date}. "
                "Run 'prices fetch' and 'indicators compute' first."
            )
            return pd.DataFrame()

        ranked = rank_advanced(frame)

        run_id = create_collection_run(
            conn, "scan", market_key, trade_date, source_provider, len(ranked),
            universe_key=effective_universe,
            params={"mode": "advanced_screener", "universe": effective_universe},
        )

        print(
            f"  screener [{market_key}/{effective_universe}] {len(ranked)} symbols  "
            f"trade_date={trade_date}  run_id={run_id}"
        )

        for rank_no, (_, row) in enumerate(ranked.iterrows(), start=1):
            upsert_scan_result(
                conn,
                run_id,
                int(row["instrument_id"]),
                market_key,
                effective_universe,
                trade_date,
                row,
                rank_no,
            )

        upsert_market_snapshot(
            conn, market_key, effective_universe, trade_date, build_market_snapshot(ranked), run_id
        )
        upsert_sector_snapshots(
            conn, market_key, effective_universe, trade_date, build_sector_snapshots(ranked), run_id
        )

        finish_run(conn, run_id, status="success", success_count=len(ranked))
        print(f"  screener [{market_key}/{effective_universe}] done: {len(ranked)} results stored")
        return ranked


def main() -> None:
    parser = argparse.ArgumentParser(description="DB-based screener: score & rank instruments.")
    parser.add_argument("--database-url", default=None)
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="Score and rank instruments for a given trade date.")
    run_p.add_argument("--market", required=True, choices=sorted(MARKETS))
    run_p.add_argument("--date", default=None, help="Trade date YYYYMMDD (default: today).")
    run_p.add_argument("--universe", default=None, help="Optional universe filter.")

    args = parser.parse_args()
    if args.command == "run":
        run_screen(args.market, args.date, args.universe, args.database_url)


if __name__ == "__main__":
    main()
