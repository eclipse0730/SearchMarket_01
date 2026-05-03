from __future__ import annotations

import argparse
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from market_scanner.compat import compat_paths
from market_scanner.db import connect
from market_scanner.markets import MARKETS
from market_scanner.models import ScanSettings
from market_scanner.pipeline import write_html, write_markdown
from market_scanner.screener import _load_screen_frame, add_scores

_DEFAULT_SETTINGS = ScanSettings(output_dir=Path("."))


def _load_render_frame(
    conn: object,
    market_key: str,
    trade_date: date,
    universe_key: str | None = None,
) -> pd.DataFrame:
    """DB의 scan_results에서 이미 저장된 scored frame을 불러옵니다."""
    effective_universe = universe_key or market_key
    rows = conn.execute(
        """
        SELECT
            sr.rank_no,
            sr.composite_score, sr.chart_score, sr.technical_score,
            sr.fundamental_score, sr.theme_score, sr.flow_score,
            i.symbol, i.display_symbol, i.name_en, i.name_local, i.sector, i.description,
            di.rsi14         AS rsi,
            di.ma60, di.ma120, di.ma240,
            di.diff_60_pct   AS diff_60,
            di.diff_120_pct  AS diff_120,
            di.diff_240_pct  AS diff_240,
            di.near_60, di.near_120, di.near_240,
            di.macd, di.macd_signal, di.macd_hist, di.macd_state,
            di.bollinger_width_pct, di.bollinger_percent_b,
            di.high_52w, di.low_52w, di.from_high_pct, di.volume_ratio,
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
            ORDER BY as_of_date DESC
            LIMIT 1
        ) f ON TRUE
        WHERE sr.universe_key = %s AND sr.trade_date = %s
        ORDER BY sr.rank_no
        """,
        (effective_universe, trade_date),
    ).fetchall()

    if not rows:
        return pd.DataFrame()

    columns = [
        "rank_no", "composite_score", "chart_score", "technical_score",
        "fundamental_score", "theme_score", "flow_score",
        "symbol", "display_symbol", "name_en", "name_local", "sector", "description",
        "rsi", "ma_60", "ma_120", "ma_240",
        "diff_60", "diff_120", "diff_240",
        "near_60", "near_120", "near_240",
        "macd", "macd_signal", "macd_hist", "macd_state",
        "bollinger_width_pct", "bollinger_percent_b",
        "high_52w", "low_52w", "from_high_pct", "volume_ratio",
        "change_pct", "gap_pct", "candle_body_pct", "candle_range_pct",
        "upper_shadow_pct", "lower_shadow_pct", "candle_type", "trend", "trend_score",
        "price", "open", "high", "low",
        "trailing_pe", "price_to_book", "return_on_equity", "revenue_growth",
        "market_cap", "target_price",
    ]
    frame = pd.DataFrame(rows, columns=columns)
    numeric_cols = [c for c in frame.columns if c not in (
        "symbol", "display_symbol", "name_en", "name_local", "sector", "description",
        "macd_state", "candle_type", "trend", "near_60", "near_120", "near_240",
    )]
    frame[numeric_cols] = frame[numeric_cols].apply(pd.to_numeric, errors="coerce")
    return frame


def run_build(
    market_key: str,
    date_str: str | None = None,
    universe_key: str | None = None,
    explicit_url: str | None = None,
    frame: pd.DataFrame | None = None,
) -> dict[str, Path]:
    trade_date = date.today() if not date_str else datetime.strptime(date_str, "%Y%m%d").date()
    date_str_fmt = trade_date.strftime("%Y%m%d")
    effective_universe = universe_key or market_key
    market = MARKETS[market_key]
    settings = _DEFAULT_SETTINGS
    paths = compat_paths(effective_universe, date_str_fmt)

    if frame is None:
        with connect(explicit_url) as conn:
            frame = _load_render_frame(conn, market_key, trade_date, universe_key)
            if frame.empty:
                # scan_results가 없으면 indicators에서 재계산
                frame = _load_screen_frame(conn, market_key, trade_date, universe_key)
                if not frame.empty:
                    frame = add_scores(frame)
                    if "price" not in frame.columns and "close" in frame.columns:
                        frame["price"] = frame["close"]

    if frame is None or frame.empty:
        print(
            f"  render [{market_key}/{effective_universe}]: no data for {trade_date}. "
            "Run 'prices fetch', 'indicators compute', 'screener run' first."
        )
        return paths

    if "price" not in frame.columns and "close" in frame.columns:
        frame = frame.copy()
        frame["price"] = frame["close"]

    paths["md"].parent.mkdir(parents=True, exist_ok=True)
    paths["html"].parent.mkdir(parents=True, exist_ok=True)

    markdown = write_markdown(frame, market, settings, date_str_fmt, paths["md"])
    print(f"  render: {paths['md']}")

    write_html(frame, market, settings, date_str_fmt, markdown, paths["html"])
    print(f"  render: {paths['html']}")

    return paths


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Render MD and HTML from DB (no CSV).")
    parser.add_argument("--database-url", default=None)
    sub = parser.add_subparsers(dest="command", required=True)

    build_p = sub.add_parser("build", help="Build MD + HTML from scan_results / daily_indicators.")
    build_p.add_argument("--market", required=True, choices=sorted(MARKETS))
    build_p.add_argument("--date", default=None, help="Trade date YYYYMMDD (default: today).")
    build_p.add_argument("--universe", default=None)

    args = parser.parse_args()
    if args.command == "build":
        run_build(args.market, args.date, args.universe, args.database_url)


if __name__ == "__main__":
    main()
