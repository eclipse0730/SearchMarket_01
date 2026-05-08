from __future__ import annotations

from typing import Any

import pandas as pd


def regime_for_score(score: float | None) -> str | None:
    if score is None:
        return None
    if score >= 65:
        return "bullish"
    if score <= 40:
        return "bearish"
    return "neutral"


def risk_for_score(score: float | None) -> str | None:
    if score is None:
        return None
    if score >= 70:
        return "low"
    if score <= 40:
        return "high"
    return "normal"


def build_market_snapshot(frame: pd.DataFrame) -> dict[str, Any]:
    change = pd.to_numeric(frame.get("change_pct"), errors="coerce") if "change_pct" in frame else pd.Series(dtype=float)
    rsi = pd.to_numeric(frame.get("rsi"), errors="coerce") if "rsi" in frame else pd.Series(dtype=float)
    score = pd.to_numeric(frame.get("composite_score"), errors="coerce") if "composite_score" in frame else pd.Series(dtype=float)
    market_score = round(float(score.dropna().mean()), 4) if not score.dropna().empty else None
    return {
        "total_count": len(frame),
        "scanned_count": len(frame),
        "success_count": len(frame),
        "failed_count": 0,
        "advance_count": int((change > 0).sum()),
        "decline_count": int((change < 0).sum()),
        "unchanged_count": int((change == 0).sum()),
        "avg_change_pct": round(float(change.dropna().mean()), 4) if not change.dropna().empty else None,
        "median_change_pct": round(float(change.dropna().median()), 4) if not change.dropna().empty else None,
        "avg_rsi14": round(float(rsi.dropna().mean()), 4) if not rsi.dropna().empty else None,
        "bullish_breadth_pct": round(float((change > 0).sum() / len(frame) * 100), 4) if len(frame) else None,
        "avg_composite_score": market_score,
        "market_score": market_score,
        "regime": regime_for_score(market_score),
        "risk_level": risk_for_score(market_score),
        "macro_payload": {},
    }


def build_sector_snapshots(frame: pd.DataFrame) -> list[dict[str, Any]]:
    if "sector" not in frame.columns or frame.empty:
        return []

    snapshots: list[dict[str, Any]] = []
    for sector, group in frame.groupby("sector", dropna=False):
        change = pd.to_numeric(group.get("change_pct"), errors="coerce") if "change_pct" in group else pd.Series(dtype=float)
        rsi = pd.to_numeric(group.get("rsi"), errors="coerce") if "rsi" in group else pd.Series(dtype=float)
        score = pd.to_numeric(group.get("composite_score"), errors="coerce") if "composite_score" in group else pd.Series(dtype=float)
        top = (
            group.sort_values("composite_score", ascending=False)
            .head(5)[["symbol", "name_local", "composite_score"]]
            .to_dict(orient="records")
            if "composite_score" in group
            else []
        )
        snapshots.append(
            {
                "sector": str(sector or "Unknown"),
                "instrument_count": len(group),
                "advance_count": int((change > 0).sum()),
                "decline_count": int((change < 0).sum()),
                "avg_change_pct": round(float(change.dropna().mean()), 4) if not change.dropna().empty else None,
                "median_change_pct": round(float(change.dropna().median()), 4) if not change.dropna().empty else None,
                "avg_rsi14": round(float(rsi.dropna().mean()), 4) if not rsi.dropna().empty else None,
                "avg_composite_score": round(float(score.dropna().mean()), 4) if not score.dropna().empty else None,
                "top_instruments": top,
            }
        )
    return snapshots

