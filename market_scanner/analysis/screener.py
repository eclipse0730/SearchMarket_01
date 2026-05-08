from __future__ import annotations

import argparse
from datetime import date, datetime
from typing import Any

import pandas as pd
from psycopg.types.json import Jsonb

from market_scanner.config.markets import MARKETS
from market_scanner.models import ScanSettings
from market_scanner.storage.common import home_market_key, price_source_for_market
from market_scanner.storage.connection import connect
from market_scanner.storage.screener_results import (
    upsert_market_snapshot,
    upsert_scan_result,
    upsert_sector_snapshots,
)

_DEFAULT_SETTINGS = ScanSettings()


# ── DB에서 screener용 DataFrame 구성 ─────────────────────────────────────────

def _load_screen_frame(
    conn: Any,
    market_key: str,
    trade_date: date,
    universe_key: str | None = None,
) -> pd.DataFrame:
    base_market = home_market_key(market_key)
    params: list[Any] = [trade_date, trade_date, base_market]
    universe_filter = ""
    if universe_key:
        universe_filter = """
        JOIN universe_memberships um
            ON um.instrument_id = i.instrument_id
            AND um.universe_key = %s
            AND um.effective_to IS NULL
        """
        params = [universe_key, trade_date, trade_date, base_market]

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
            di.volume_ratio,
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
            f.target_price
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
        "rsi", "ma_5", "ma_20", "ma_60", "ma_120", "ma_240",
        "diff_5", "diff_20", "diff_60", "diff_120", "diff_240",
        "near_5", "near_20", "near_60", "near_120", "near_240",
        "macd", "macd_signal", "macd_hist", "macd_state",
        "bollinger_width_pct", "bollinger_percent_b",
        "high_52w", "low_52w", "from_high_pct", "from_low_pct",
        "high_20d", "low_20d", "high_60d", "low_60d",
        "breakout_20d", "breakout_60d", "volume_ratio",
        "return_5d", "return_20d", "return_60d", "return_120d", "return_240d",
        "atr14", "atr14_pct", "volatility_20d", "volatility_60d",
        "change_pct", "gap_pct",
        "candle_body_pct", "candle_range_pct", "upper_shadow_pct", "lower_shadow_pct",
        "candle_type", "trend", "trend_score",
        "close", "open", "high", "low", "volume",
        "trailing_pe", "price_to_book", "return_on_equity", "revenue_growth",
        "market_cap", "target_price",
    ]
    frame = pd.DataFrame(rows, columns=columns)

    numeric_cols = [c for c in frame.columns if c not in (
        "instrument_id", "symbol", "display_symbol", "name_en", "name_local",
        "sector", "description", "macd_state", "candle_type", "trend",
        "near_5", "near_20", "near_60", "near_120", "near_240",
        "breakout_20d", "breakout_60d",
    )]
    frame[numeric_cols] = frame[numeric_cols].apply(pd.to_numeric, errors="coerce")

    # target_price 기반 upside_pct 계산
    close_num = pd.to_numeric(frame["close"], errors="coerce")
    target_num = pd.to_numeric(frame["target_price"], errors="coerce")
    frame["upside_pct"] = ((target_num - close_num) / close_num * 100).round(1)

    return frame


# ── 점수화 (pipeline.py 로직 재사용) ─────────────────────────────────────────

def _clamp(v: float) -> float:
    if pd.isna(v):
        return 0.0
    return round(max(0.0, min(100.0, float(v))), 2)


def _is_true(value: Any) -> bool:
    return bool(value) if pd.notna(value) else False


def _score_chart(row: pd.Series, settings: ScanSettings = _DEFAULT_SETTINGS) -> float:
    trend_value = row.get("trend_score")
    trend_score = float(trend_value) if pd.notna(trend_value) else 0.0
    near_count = sum(1 for p in settings.ma_periods if _is_true(row.get(f"near_{p}", False)))
    near_ratio = near_count / max(len(settings.ma_periods), 1)
    diffs = [abs(float(row.get(f"diff_{p}"))) for p in settings.ma_periods if pd.notna(row.get(f"diff_{p}"))]
    closest = min(diffs) if diffs else None
    from_high = row.get("from_high_pct")

    score = trend_score * 12 + near_ratio * 20
    if closest is not None:
        score += 12 if closest <= 2 else (7 if closest <= 5 else 0)
    if pd.notna(from_high):
        v = float(from_high)
        if -30 <= v <= -5:
            score += 8
        elif v > -5:
            score += 5
        elif v < -45:
            score -= 8
    return _clamp(score)


def _score_technical(row: pd.Series) -> float:
    parts: list[float] = []
    rsi = row.get("rsi")
    if pd.notna(rsi):
        v = float(rsi)
        parts.append(100 if 40 <= v <= 60 else 75 if (30 <= v < 40 or 60 < v <= 68) else 45 if v < 30 else 25)
    macd_state = str(row.get("macd_state") or "")
    if macd_state:
        parts.append({"Bullish": 100, "Positive": 78, "Improving": 68, "Bearish": 25}.get(macd_state, 50))
    pct_b = row.get("bollinger_percent_b")
    if pd.notna(pct_b):
        v = float(pct_b)
        parts.append(85 if 0.2 <= v <= 0.8 else 70 if 0 <= v < 0.2 else 55 if 0.8 < v <= 1.0 else 30)
    vol = row.get("volume_ratio")
    if pd.notna(vol):
        v = float(vol)
        parts.append(85 if 1.2 <= v <= 4.0 else 65 if v > 4.0 else 55 if v >= 0.8 else 40)
    ct = str(row.get("candle_type") or "")
    if ct:
        parts.append({
            "Strong Bullish": 90, "Bullish Reversal": 88, "Bullish": 72,
            "Long Lower Doji": 68, "Doji": 55, "Long Upper Doji": 38,
            "Bearish": 35, "Bearish Rejection": 25, "Strong Bearish": 20,
        }.get(ct, 50))
    return _clamp(sum(parts) / len(parts) if parts else 50)


def _score_fundamental(row: pd.Series) -> float:
    parts: list[float] = []
    pe = row.get("trailing_pe")
    if pd.notna(pe) and float(pe) > 0:
        v = float(pe)
        parts.append(92 if v < 10 else 82 if v < 20 else 65 if v < 30 else 45 if v < 50 else 25)
    pbr = row.get("price_to_book")
    if pd.notna(pbr) and float(pbr) > 0:
        v = float(pbr)
        parts.append(88 if v < 1 else 75 if v < 3 else 58 if v < 6 else 35)
    roe = row.get("return_on_equity")
    if pd.notna(roe):
        v = float(roe)
        parts.append(92 if v >= 20 else 78 if v >= 10 else 58 if v > 0 else 25)
    growth = row.get("revenue_growth")
    if pd.notna(growth):
        v = float(growth)
        parts.append(90 if v >= 20 else 75 if v >= 5 else 55 if v >= 0 else 30)
    return _clamp(sum(parts) / len(parts) if parts else 50)


def _sector_relative_fundamental_scores(frame: pd.DataFrame) -> pd.Series:
    if frame.empty or "sector" not in frame.columns:
        return pd.Series(50.0, index=frame.index)
    work = frame.copy()

    def numeric_col(column: str) -> pd.Series:
        if column not in work.columns:
            return pd.Series(float("nan"), index=work.index, dtype="float64")
        return pd.to_numeric(work[column], errors="coerce")

    work["trailing_pe"] = numeric_col("trailing_pe")
    work["price_to_book"] = numeric_col("price_to_book")
    work["return_on_equity"] = numeric_col("return_on_equity")
    work["revenue_growth"] = numeric_col("revenue_growth")

    component_weights = {
        "pe": 0.25,
        "pbr": 0.20,
        "roe": 0.30,
        "growth": 0.25,
    }

    def relative_component(
        column: str,
        *,
        higher_is_better: bool,
        positive_only: bool = False,
    ) -> pd.Series:
        scores = pd.Series(float("nan"), index=work.index, dtype="float64")
        values = work[column]
        valid = work["sector"].notna() & values.notna()
        if positive_only:
            valid &= values > 0

        for _, sector_values in values[valid].groupby(work.loc[valid, "sector"]):
            count = len(sector_values)
            if count == 1:
                scores.loc[sector_values.index] = 50.0
                continue
            ranks = sector_values.rank(method="average", ascending=higher_is_better)
            scores.loc[sector_values.index] = ((ranks - 1) / (count - 1) * 100).clip(0, 100)
        return scores

    components = pd.DataFrame(index=work.index)
    components["pe"] = relative_component("trailing_pe", higher_is_better=False, positive_only=True)
    components["pbr"] = relative_component("price_to_book", higher_is_better=False, positive_only=True)
    components["roe"] = relative_component("return_on_equity", higher_is_better=True)
    components["growth"] = relative_component("revenue_growth", higher_is_better=True)

    weighted_sum = pd.Series(0.0, index=work.index, dtype="float64")
    available_weight = pd.Series(0.0, index=work.index, dtype="float64")
    for column, weight in component_weights.items():
        valid = components[column].notna()
        weighted_sum.loc[valid] += components.loc[valid, column] * weight
        available_weight.loc[valid] += weight

    relative_score = (weighted_sum / available_weight).where(available_weight > 0, 50.0)
    has_any_fundamental = components.notna().any(axis=1)
    valid_counts = has_any_fundamental.groupby(work["sector"]).transform("sum").fillna(0)
    confidence = (valid_counts / 10).clip(upper=1.0)
    return (50 + (relative_score - 50) * confidence).fillna(50).round(2)


def _score_momentum(row: pd.Series) -> float:
    parts: list[float] = []
    vol = row.get("volume_ratio")
    if pd.notna(vol):
        v = float(vol)
        parts.append(88 if 1.5 <= v <= 5.0 else 65 if v > 5.0 else 58 if v >= 1.0 else 42)
    from_high = row.get("from_high_pct")
    if pd.notna(from_high):
        v = float(from_high)
        parts.append(85 if -30 <= v <= -10 else 62 if -10 < v <= 0 else 58 if -50 <= v < -30 else 35)
    upside = row.get("upside_pct")
    if pd.notna(upside):
        v = float(upside)
        parts.append(92 if v >= 25 else 78 if v >= 15 else 60 if v >= 5 else 45 if v >= 0 else 20)
    change = row.get("change_pct")
    if pd.notna(change):
        v = float(change)
        parts.append(75 if v >= 2 else 65 if v > 0 else 50 if v >= -2 else 32)
    gap = row.get("gap_pct")
    ct = str(row.get("candle_type") or "")
    if pd.notna(gap):
        v = float(gap)
        if v > 0 and ct in {"Strong Bullish", "Bullish", "Bullish Reversal"}:
            parts.append(78)
        elif v < 0 and ct in {"Bullish Reversal", "Long Lower Doji"}:
            parts.append(72)
        elif v > 1.5 and ct in {"Bearish Rejection", "Long Upper Doji"}:
            parts.append(35)
        else:
            parts.append(52)
    return _clamp(sum(parts) / len(parts) if parts else 50)


def _theme_scores(frame: pd.DataFrame) -> pd.Series:
    if frame.empty or "sector" not in frame.columns:
        return pd.Series(50.0, index=frame.index)
    work = frame.copy()

    def numeric_col(column: str) -> pd.Series:
        if column not in work.columns:
            return pd.Series(float("nan"), index=work.index, dtype="float64")
        return pd.to_numeric(work[column], errors="coerce")

    work["trend_score"] = numeric_col("trend_score")
    work["return_5d"] = numeric_col("return_5d")
    work["return_20d"] = numeric_col("return_20d")
    work["volume_ratio"] = numeric_col("volume_ratio")
    work["diff_20"] = numeric_col("diff_20")
    work["above_ma20"] = (work["diff_20"] > 0).where(work["diff_20"].notna(), pd.NA)
    if "breakout_20d" in work.columns:
        work["breakout_20d_num"] = work["breakout_20d"].apply(
            lambda value: 1.0 if _is_true(value) else 0.0 if pd.notna(value) else pd.NA
        )
    else:
        work["breakout_20d_num"] = pd.Series(float("nan"), index=work.index, dtype="float64")

    grouped = (
        work.dropna(subset=["sector"])
        .groupby("sector")
        .agg(
            sector_count=("sector", "size"),
            avg_return_5d=("return_5d", "mean"),
            avg_return_20d=("return_20d", "mean"),
            avg_volume_ratio=("volume_ratio", "mean"),
            above_ma20_ratio=("above_ma20", "mean"),
            breakout_ratio=("breakout_20d_num", "mean"),
            avg_trend=("trend_score", "mean"),
        )
    )
    if grouped.empty:
        return pd.Series(50.0, index=frame.index)

    market_return_5d = work["return_5d"].mean()
    market_return_20d = work["return_20d"].mean()
    rel_return_5d = grouped["avg_return_5d"] - (0.0 if pd.isna(market_return_5d) else market_return_5d)
    rel_return_20d = grouped["avg_return_20d"] - (0.0 if pd.isna(market_return_20d) else market_return_20d)

    return_5d_score = (50 + rel_return_5d.fillna(0) * 4.0).clip(0, 100)
    return_20d_score = (50 + rel_return_20d.fillna(0) * 2.5).clip(0, 100)
    above_ma20_score = (grouped["above_ma20_ratio"] * 100).where(grouped["above_ma20_ratio"].notna(), 50).clip(0, 100)
    volume_score = (50 + (grouped["avg_volume_ratio"].fillna(1.0) - 1.0) * 35).clip(0, 100)
    breakout_score = (45 + grouped["breakout_ratio"] * 125).where(grouped["breakout_ratio"].notna(), 50).clip(0, 100)
    trend_score = (grouped["avg_trend"].fillna(2.5) * 20).clip(0, 100)

    raw_theme = (
        return_20d_score * 0.25
        + return_5d_score * 0.20
        + above_ma20_score * 0.20
        + volume_score * 0.15
        + breakout_score * 0.15
        + trend_score * 0.05
    )
    confidence = (grouped["sector_count"] / 10).clip(upper=1.0)
    grouped["theme_score"] = (50 + (raw_theme - 50) * confidence).clip(0, 100)
    mapped = pd.to_numeric(work["sector"].map(grouped["theme_score"]), errors="coerce")
    return mapped.fillna(50).round(2)


def add_scores(frame: pd.DataFrame, settings: ScanSettings = _DEFAULT_SETTINGS) -> pd.DataFrame:
    if frame.empty:
        return frame
    scored = frame.copy()
    scored["chart_score"] = scored.apply(_score_chart, axis=1, settings=settings)
    scored["technical_score"] = scored.apply(_score_technical, axis=1)
    absolute_fundamental = scored.apply(_score_fundamental, axis=1)
    relative_fundamental = _sector_relative_fundamental_scores(scored)
    scored["fundamental_score"] = (absolute_fundamental * 0.55 + relative_fundamental * 0.45).round(2)
    scored["theme_score"] = _theme_scores(scored)
    momentum_score = scored.apply(_score_momentum, axis=1)
    scored["momentum_score"] = momentum_score
    scored["flow_score"] = momentum_score
    scored["composite_score"] = (
        scored["chart_score"] * 0.30
        + scored["technical_score"] * 0.25
        + scored["fundamental_score"] * 0.20
        + scored["theme_score"] * 0.15
        + scored["flow_score"] * 0.10
    ).round(2)
    return scored


# ── run ───────────────────────────────────────────────────────────────────────

def _latest_indicator_date(
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

def run_screen(
    market_key: str,
    date_str: str | None = None,
    universe_key: str | None = None,
    explicit_url: str | None = None,
) -> pd.DataFrame:
    effective_universe = universe_key or market_key
    source_provider = price_source_for_market(market_key)

    with connect(explicit_url) as conn:
        if date_str:
            trade_date = datetime.strptime(date_str, "%Y%m%d").date()
        else:
            latest_date = _latest_indicator_date(conn, market_key, universe_key)
            if latest_date is None:
                print(
                    f"  screener [{market_key}/{effective_universe}]: no indicator data. "
                    "Run 'prices fetch' and 'indicators compute' first."
                )
                return pd.DataFrame()
            trade_date = latest_date
            print(f"  screener [{market_key}/{effective_universe}]: using latest indicator date {trade_date}")

        frame = _load_screen_frame(conn, market_key, trade_date, universe_key)
        if frame.empty:
            print(
                f"  screener [{market_key}]: no data for {trade_date}. "
                "Run 'prices fetch' and 'indicators compute' first."
            )
            return pd.DataFrame()

        scored = add_scores(frame)
        ranked = scored.sort_values("composite_score", ascending=False, na_position="last").reset_index(drop=True)

        run_result = conn.execute(
            """
            INSERT INTO collection_runs (
                run_type, market_key, universe_key, trade_date, source_provider,
                status, requested_count, params
            )
            VALUES ('scan', %s, %s, %s, %s, 'running', %s, %s)
            RETURNING run_id
            """,
            (
                home_market_key(market_key),
                effective_universe,
                trade_date,
                source_provider,
                len(ranked),
                Jsonb({"mode": "screener", "universe": effective_universe}),
            ),
        ).fetchone()
        run_id = str(run_result[0])

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

        upsert_market_snapshot(conn, market_key, effective_universe, trade_date, ranked, run_id)
        upsert_sector_snapshots(conn, market_key, effective_universe, trade_date, ranked, run_id)

        conn.execute(
            """
            UPDATE collection_runs
            SET status = 'success', finished_at = now(), success_count = %s
            WHERE run_id = %s
            """,
            (len(ranked), run_id),
        )
        print(f"  screener [{market_key}/{effective_universe}] done: {len(ranked)} results stored")
        return ranked


# ── CLI ───────────────────────────────────────────────────────────────────────

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
