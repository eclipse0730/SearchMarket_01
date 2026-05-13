from __future__ import annotations

import argparse
import hashlib
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from psycopg.types.json import Jsonb

from market_scanner.config.markets import MARKETS
from market_scanner.domain.market_policy import home_market_key
from market_scanner.models import ScanSettings
from market_scanner.reports.html_report import write_html
from market_scanner.reports.markdown_report import write_markdown
from market_scanner.storage.connection import connect

_DEFAULT_SETTINGS = ScanSettings(output_dir=Path("."))
REPORT_EXPORT_DIR = Path("site") / "reports"


def report_output_paths(scope_key: str, date_str: str) -> dict[str, Path]:
    base_dir = REPORT_EXPORT_DIR / scope_key / date_str
    return {
        "md": base_dir / "analysis.md",
        "html": base_dir / "index.html",
    }


# 전략별 점수/라벨은 이제 scan_results 컬럼에서 직접 SELECT 한다.
# summary_payload(JSONB)는 디버깅/원본 보존용으로만 유지.


def _load_render_frame(
    conn: object,
    market_key: str,
    trade_date: date,
    universe_key: str | None = None,
) -> pd.DataFrame:
    """scan_results + daily_indicators + daily_prices + instrument_fundamentals 통합 조회.

    스크리너가 이미 산출한 점수/태그/전략별 점수를 그대로 사용한다. 렌더 단계에서
    재스코어링은 하지 않는다.
    """
    effective_universe = universe_key or market_key
    rows = conn.execute(
        """
        WITH latest_run AS (
            SELECT COALESCE(
                (
                    SELECT run_id
                    FROM market_snapshots
                    WHERE market_key = %s AND universe_key = %s AND trade_date = %s
                    ORDER BY created_at DESC
                    LIMIT 1
                ),
                (
                    SELECT run_id
                    FROM collection_runs
                    WHERE run_type = 'scan'
                      AND market_key = %s
                      AND universe_key = %s
                      AND trade_date = %s
                      AND status = 'success'
                    ORDER BY finished_at DESC NULLS LAST, started_at DESC
                    LIMIT 1
                )
            ) AS run_id
        )
        SELECT
            sr.rank_no,
            sr.composite_score, sr.chart_score, sr.technical_score,
            sr.fundamental_score, sr.theme_score, sr.flow_score,
            sr.pullback_score, sr.breakout_score, sr.box_breakout_score,
            sr.trend_quality_score, sr.reversal_score, sr.overbought_score,
            sr.risk_score, sr.raw_composite_score,
            sr.action_score, sr.quality_score,
            sr.setup_label, sr.pullback_ma_period,
            sr.setup_tags, sr.risk_flags, sr.summary_payload,
            i.symbol, i.display_symbol, i.name_en, i.name_local, i.sector, i.description,
            di.rsi14         AS rsi,
            di.rsi14,
            di.rsi14_prev,
            di.rsi14_change,
            di.rsi14_ma5,
            di.rsi2,
            di.rsi5,
            di.rsi30,
            di.ma5, di.ma20, di.ma60, di.ma120, di.ma240,
            di.diff_5_pct    AS diff_5,
            di.diff_20_pct   AS diff_20,
            di.diff_60_pct   AS diff_60,
            di.diff_120_pct  AS diff_120,
            di.diff_240_pct  AS diff_240,
            di.near_5, di.near_20, di.near_60, di.near_120, di.near_240,
            di.macd, di.macd_signal, di.macd_hist, di.macd_state,
            di.bollinger_width_pct, di.bollinger_percent_b,
            di.high_52w, di.low_52w, di.from_high_pct, di.from_low_pct,
            di.high_20d, di.low_20d, di.high_60d, di.low_60d,
            di.breakout_20d, di.breakout_60d,
            di.breakout_high_20d, di.breakout_high_60d,
            di.volume_ratio,
            di.value_traded, di.value_ratio_20d,
            di.volume_avg20, di.volume_avg60,
            di.ma_alignment_score, di.is_ma_bullish_alignment,
            di.ma20_slope_pct, di.ma60_slope_pct,
            di.macd_cross, di.macd_hist_change,
            di.close_position_in_range_20d, di.close_position_in_range_60d,
            di.return_5d, di.return_20d, di.return_60d, di.return_120d, di.return_240d,
            di.atr14, di.atr14_pct, di.volatility_20d, di.volatility_60d,
            di.change_pct, di.gap_pct,
            di.candle_body_pct, di.candle_range_pct,
            di.upper_shadow_pct, di.lower_shadow_pct,
            di.candle_type, di.trend, di.trend_score,
            dp.close_price  AS price,
            dp.open_price   AS open,
            dp.high_price   AS high,
            dp.low_price    AS low,
            f.trailing_pe, f.price_to_book,
            f.return_on_equity_pct  AS return_on_equity,
            f.revenue_growth_pct    AS revenue_growth,
            f.market_cap, f.target_price
        FROM scan_results sr
        JOIN latest_run lr ON lr.run_id = sr.run_id
        JOIN instruments i ON i.instrument_id = sr.instrument_id
        LEFT JOIN daily_indicators di
            ON di.instrument_id = sr.instrument_id AND di.trade_date = sr.trade_date
        LEFT JOIN LATERAL (
            SELECT close_price, open_price, high_price, low_price
            FROM daily_prices
            WHERE instrument_id = sr.instrument_id AND trade_date = sr.trade_date
            ORDER BY CASE source_provider WHEN 'fdr' THEN 1 WHEN 'yfinance' THEN 2 ELSE 3 END
            LIMIT 1
        ) dp ON TRUE
        LEFT JOIN LATERAL (
            SELECT trailing_pe, price_to_book, return_on_equity_pct, revenue_growth_pct,
                   market_cap, target_price
            FROM instrument_fundamentals
            WHERE instrument_id = sr.instrument_id
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
        WHERE sr.universe_key = %s AND sr.trade_date = %s
        ORDER BY sr.rank_no
        """,
        (
            home_market_key(market_key),
            effective_universe,
            trade_date,
            home_market_key(market_key),
            effective_universe,
            trade_date,
            effective_universe,
            trade_date,
        ),
    ).fetchall()

    if not rows:
        return pd.DataFrame()

    columns = [
        "rank_no", "composite_score", "chart_score", "technical_score",
        "fundamental_score", "theme_score", "flow_score",
        "pullback_score", "breakout_score", "box_breakout_score",
        "trend_quality_score", "reversal_score", "overbought_score",
        "risk_score", "raw_composite_score",
        "action_score", "quality_score",
        "setup_label", "pullback_ma_period",
        "setup_tags", "risk_flags", "summary_payload",
        "symbol", "display_symbol", "name_en", "name_local", "sector", "description",
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
        "change_pct", "gap_pct", "candle_body_pct", "candle_range_pct",
        "upper_shadow_pct", "lower_shadow_pct", "candle_type", "trend", "trend_score",
        "price", "open", "high", "low",
        "trailing_pe", "price_to_book", "return_on_equity", "revenue_growth",
        "market_cap", "target_price",
    ]
    frame = pd.DataFrame(rows, columns=columns)

    # setup_label은 NULL을 빈 문자열로 정규화해 downstream의 문자열 가정과 맞춘다.
    frame["setup_label"] = frame["setup_label"].fillna("")

    # 태그 배열은 list[str] 로 정규화 (psycopg2/3 모두 list 또는 None 으로 들어옴)
    frame["setup_tags"] = frame["setup_tags"].apply(lambda v: list(v) if v else [])
    frame["risk_flags"] = frame["risk_flags"].apply(lambda v: list(v) if v else [])

    numeric_cols = [c for c in frame.columns if c not in (
        "symbol", "display_symbol", "name_en", "name_local", "sector", "description",
        "macd_state", "macd_cross", "candle_type", "trend", "setup_label",
        "near_5", "near_20", "near_60", "near_120", "near_240",
        "breakout_20d", "breakout_60d", "breakout_high_20d", "breakout_high_60d",
        "is_ma_bullish_alignment",
        "setup_tags", "risk_flags", "summary_payload",
    )]
    frame[numeric_cols] = frame[numeric_cols].apply(pd.to_numeric, errors="coerce")
    return frame


def run_build(
    market_key: str,
    date_str: str | None = None,
    universe_key: str | None = None,
    database_url: str | None = None,
) -> dict[str, Path]:
    trade_date = date.today() if not date_str else datetime.strptime(date_str, "%Y%m%d").date()
    date_str_fmt = trade_date.strftime("%Y%m%d")
    effective_universe = universe_key or market_key
    market = MARKETS[market_key]
    settings = _DEFAULT_SETTINGS
    paths = report_output_paths(effective_universe, date_str_fmt)

    with connect(database_url) as conn:
        frame = _load_render_frame(conn, market_key, trade_date, universe_key)

    if frame.empty:
        print(
            f"  render [{market_key}/{effective_universe}]: no data for {trade_date}. "
            "Run 'prices fetch', 'indicators compute', and 'screener run' first."
        )
        return paths

    if "price" not in frame.columns and "close" in frame.columns:
        frame = frame.copy()
        frame["price"] = frame["close"]

    paths["md"].parent.mkdir(parents=True, exist_ok=True)
    paths["html"].parent.mkdir(parents=True, exist_ok=True)

    with connect(database_url) as conn:
        run_result = conn.execute(
            """
            INSERT INTO collection_runs (
                run_type, market_key, universe_key, trade_date, source_provider, status,
                requested_count, params
            )
            VALUES ('render', %s, %s, %s, 'db', 'running', %s, %s)
            RETURNING run_id
            """,
            (
                home_market_key(market_key),
                effective_universe,
                trade_date,
                len(frame),
                Jsonb({"universe_key": effective_universe}),
            ),
        ).fetchone()
        run_id = str(run_result[0])

        markdown = write_markdown(frame, market, settings, date_str_fmt, paths["md"])
        print(f"  render: {paths['md']}")

        write_html(frame, market, settings, date_str_fmt, markdown, paths["html"])
        print(f"  render: {paths['html']}")
        html_text = paths["html"].read_text(encoding="utf-8")

        for report_type, fmt, path, content in (
            ("analysis", "markdown", paths["md"], markdown),
            ("detail_page", "html", paths["html"], html_text),
        ):
            conn.execute(
                """
                INSERT INTO generated_reports (
                    market_key, universe_key, trade_date, run_id, report_type,
                    format, file_path, content_hash, metadata
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    home_market_key(market_key),
                    effective_universe,
                    trade_date,
                    run_id,
                    report_type,
                    fmt,
                    str(path),
                    hashlib.sha256(content.encode("utf-8")).hexdigest(),
                    Jsonb({"row_count": len(frame)}),
                ),
            )

        conn.execute(
            """
            UPDATE collection_runs
            SET status = 'success', finished_at = now(), success_count = %s
            WHERE run_id = %s
            """,
            (len(frame), run_id),
        )

    return paths


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Render MD and HTML from DB (no CSV).")
    parser.add_argument("--database-url", default=None)
    sub = parser.add_subparsers(dest="command", required=True)

    build_p = sub.add_parser("build", help="Build MD + HTML from scan_results.")
    build_p.add_argument("--market", required=True, choices=sorted(MARKETS))
    build_p.add_argument("--date", default=None, help="Trade date YYYYMMDD (default: today).")
    build_p.add_argument("--universe", default=None)

    args = parser.parse_args()
    if args.command == "build":
        run_build(args.market, args.date, args.universe, args.database_url)


if __name__ == "__main__":
    main()
