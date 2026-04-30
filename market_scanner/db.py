from __future__ import annotations

import argparse
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import psycopg
from psycopg.types.json import Jsonb

from market_scanner.compat import load_frame
from market_scanner.markets import MARKETS
from market_scanner.models import MarketDefinition


DEFAULT_DATABASE_URL = "postgresql://searchmarket:searchmarket@localhost:5433/searchmarket"
SCHEMA_PATH = Path(__file__).resolve().parent.parent / "docs" / "database_schema_v1.sql"


def database_url(explicit_url: str | None = None) -> str:
    return explicit_url or os.getenv("DATABASE_URL") or DEFAULT_DATABASE_URL


def connect(explicit_url: str | None = None) -> psycopg.Connection:
    return psycopg.connect(database_url(explicit_url))


def init_db(explicit_url: str | None = None) -> None:
    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
    with connect(explicit_url) as conn:
        conn.execute(schema_sql)
        seed_reference_data(conn)


def home_market_key(market_key: str) -> str:
    if market_key in {"nasdaq100", "sp500", "us-all"}:
        return "us"
    if market_key == "kospi-all":
        return "kospi"
    if market_key == "kosdaq-all":
        return "kosdaq"
    return market_key


def default_asset_filter(market_key: str) -> list[str]:
    if market_key in {"global-indices"}:
        return ["index"]
    if market_key in {"theme-proxies"}:
        return ["etf"]
    if market_key in {"commodities"}:
        return ["commodity"]
    return ["common_stock"]


def country_currency_for_market(market_key: str) -> tuple[str | None, str | None, str]:
    home_key = home_market_key(market_key)
    if home_key in {"kospi", "kosdaq"}:
        return "KR", "KRW", "Asia/Seoul"
    if home_key in {"us", "nasdaq100", "sp500"}:
        return "US", "USD", "America/New_York"
    return None, None, "Asia/Seoul"


def price_source_for_market(market_key: str) -> str:
    if home_market_key(market_key) in {"kospi", "kosdaq"}:
        return "fdr"
    return "yfinance"


def seed_reference_data(conn: psycopg.Connection) -> None:
    home_keys = {home_market_key(key) for key in MARKETS}
    for key in sorted(set(MARKETS) | home_keys):
        market = MARKETS.get(key)
        label = market.label if market else key.upper()
        country_code, currency_code, timezone = country_currency_for_market(key)
        conn.execute(
            """
            INSERT INTO markets (
                market_key, label, country_code, currency_code, timezone, description, is_active
            )
            VALUES (%s, %s, %s, %s, %s, %s, TRUE)
            ON CONFLICT (market_key) DO UPDATE SET
                label = EXCLUDED.label,
                country_code = EXCLUDED.country_code,
                currency_code = EXCLUDED.currency_code,
                timezone = EXCLUDED.timezone,
                description = EXCLUDED.description,
                is_active = TRUE
            """,
            (key, label, country_code, currency_code, timezone, market.notes if market else None),
        )

    for universe_key, market in MARKETS.items():
        conn.execute(
            """
            INSERT INTO universe_definitions (
                universe_key, market_key, label, description, source_policy, default_asset_type_filter, is_active
            )
            VALUES (%s, %s, %s, %s, %s, %s, TRUE)
            ON CONFLICT (universe_key) DO UPDATE SET
                market_key = EXCLUDED.market_key,
                label = EXCLUDED.label,
                description = EXCLUDED.description,
                source_policy = EXCLUDED.source_policy,
                default_asset_type_filter = EXCLUDED.default_asset_type_filter,
                is_active = TRUE
            """,
            (
                universe_key,
                home_market_key(universe_key),
                market.label,
                market.notes,
                market.notes,
                default_asset_filter(universe_key),
            ),
        )


def _clean_value(value: Any) -> Any:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(value, "item"):
        return value.item()
    return value


def _clean_text(value: Any) -> str | None:
    value = _clean_value(value)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _clean_number(value: Any) -> float | None:
    value = _clean_value(value)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _clean_int(value: Any) -> int | None:
    number = _clean_number(value)
    return int(number) if number is not None else None


def _clean_bool(value: Any) -> bool:
    value = _clean_value(value)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return bool(value)


def _row_payload(row: pd.Series, columns: list[str]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for column in columns:
        if column in row:
            payload[column] = _clean_value(row.get(column))
    return payload


def classify_asset_type(row: pd.Series, market_key: str) -> str:
    home_key = home_market_key(market_key)
    if home_key in {"global-indices"}:
        return "index"
    if home_key in {"commodities"}:
        return "commodity"
    if market_key == "theme-proxies":
        return "etf"

    name = (_clean_text(row.get("name_local")) or _clean_text(row.get("name_en")) or "").upper()
    symbol = (_clean_text(row.get("symbol")) or "").upper()
    if "ETN" in name:
        return "etn"
    if "ETF" in name or name.startswith(("KODEX", "TIGER", "ACE", "RISE", "SOL", "KOSEF", "KBSTAR")):
        return "etf"
    if "리츠" in name or "REIT" in name:
        return "reit"
    if "스팩" in name or "SPAC" in name:
        return "spac"
    if symbol.endswith(("5.KS", "7.KS", "9.KS")) and ("우" in name or "PREFERRED" in name):
        return "preferred_stock"
    if "우" in name and home_key in {"kospi", "kosdaq"}:
        return "preferred_stock"
    return "common_stock"


def display_symbol_for_row(row: pd.Series, market: MarketDefinition) -> str | None:
    display_symbol = _clean_text(row.get("display_symbol"))
    symbol = _clean_text(row.get("symbol"))
    if symbol and home_market_key(market.key) in {"kospi", "kosdaq"}:
        code = symbol.replace(".KS", "").replace(".KQ", "")
        return code.zfill(6) if code.isdigit() else display_symbol or code
    return display_symbol or symbol


def upsert_instrument(
    conn: psycopg.Connection,
    market: MarketDefinition,
    row: pd.Series,
) -> int:
    symbol = _clean_text(row.get("symbol"))
    if not symbol:
        raise ValueError("Missing symbol")
    home_key = home_market_key(market.key)
    country_code, currency_code, _ = country_currency_for_market(market.key)
    asset_type = classify_asset_type(row, market.key)
    raw_metadata = _row_payload(
        row,
        ["symbol", "display_symbol", "name_en", "name_local", "sector", "description"],
    )
    result = conn.execute(
        """
        INSERT INTO instruments (
            market_key, symbol, display_symbol, country_code, currency_code, asset_type,
            listing_status, name_en, name_local, sector, description, source_provider,
            source_rank, raw_metadata, is_active
        )
        VALUES (%s, %s, %s, %s, %s, %s, 'active', %s, %s, %s, %s, %s, %s, %s, TRUE)
        ON CONFLICT (market_key, symbol) DO UPDATE SET
            display_symbol = COALESCE(EXCLUDED.display_symbol, instruments.display_symbol),
            country_code = COALESCE(EXCLUDED.country_code, instruments.country_code),
            currency_code = COALESCE(EXCLUDED.currency_code, instruments.currency_code),
            asset_type = EXCLUDED.asset_type,
            name_en = COALESCE(EXCLUDED.name_en, instruments.name_en),
            name_local = COALESCE(EXCLUDED.name_local, instruments.name_local),
            sector = COALESCE(EXCLUDED.sector, instruments.sector),
            description = COALESCE(EXCLUDED.description, instruments.description),
            source_provider = EXCLUDED.source_provider,
            source_rank = EXCLUDED.source_rank,
            raw_metadata = instruments.raw_metadata || EXCLUDED.raw_metadata,
            is_active = TRUE
        RETURNING instrument_id
        """,
        (
            home_key,
            symbol,
            display_symbol_for_row(row, market),
            country_code,
            currency_code,
            asset_type,
            _clean_text(row.get("name_en")),
            _clean_text(row.get("name_local")),
            _clean_text(row.get("sector")),
            _clean_text(row.get("description")),
            "csv",
            80,
            Jsonb(raw_metadata),
        ),
    ).fetchone()
    return int(result[0])


def create_run(
    conn: psycopg.Connection,
    market_key: str,
    universe_key: str,
    trade_date: datetime.date,
    requested_count: int,
) -> str:
    result = conn.execute(
        """
        INSERT INTO collection_runs (
            run_type, market_key, universe_key, trade_date, source_provider, status,
            requested_count, params
        )
        VALUES ('scan', %s, %s, %s, %s, 'running', %s, %s)
        RETURNING run_id
        """,
        (
            home_market_key(market_key),
            universe_key,
            trade_date,
            price_source_for_market(market_key),
            requested_count,
            Jsonb({"loaded_from": "csv", "scan_market_key": market_key}),
        ),
    ).fetchone()
    return str(result[0])


def finish_run(
    conn: psycopg.Connection,
    run_id: str,
    *,
    status: str,
    success_count: int,
    failed_count: int = 0,
    skipped_count: int = 0,
) -> None:
    conn.execute(
        """
        UPDATE collection_runs
        SET status = %s,
            finished_at = now(),
            success_count = %s,
            failed_count = %s,
            skipped_count = %s
        WHERE run_id = %s
        """,
        (status, success_count, failed_count, skipped_count, run_id),
    )


def upsert_universe_membership(
    conn: psycopg.Connection,
    universe_key: str,
    instrument_id: int,
    trade_date: datetime.date,
    rank_no: int,
) -> None:
    conn.execute(
        """
        INSERT INTO universe_memberships (
            universe_key, instrument_id, effective_from, effective_to, rank_no, source_provider
        )
        VALUES (%s, %s, %s, NULL, %s, 'csv')
        ON CONFLICT (universe_key, instrument_id, effective_from) DO UPDATE SET
            effective_to = NULL,
            rank_no = EXCLUDED.rank_no,
            source_provider = EXCLUDED.source_provider
        """,
        (universe_key, instrument_id, trade_date, rank_no),
    )


def upsert_daily_price(
    conn: psycopg.Connection,
    instrument_id: int,
    trade_date: datetime.date,
    source_provider: str,
    row: pd.Series,
    run_id: str,
    currency_code: str | None,
) -> None:
    close_price = _clean_number(row.get("close")) or _clean_number(row.get("price"))
    if close_price is None:
        return
    conn.execute(
        """
        INSERT INTO daily_prices (
            instrument_id, trade_date, source_provider, open_price, high_price, low_price,
            close_price, adj_close_price, volume, currency_code, is_adjusted, run_id, raw_payload
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, NULL, NULL, %s, FALSE, %s, %s)
        ON CONFLICT (instrument_id, trade_date, source_provider) DO UPDATE SET
            open_price = EXCLUDED.open_price,
            high_price = EXCLUDED.high_price,
            low_price = EXCLUDED.low_price,
            close_price = EXCLUDED.close_price,
            currency_code = EXCLUDED.currency_code,
            run_id = EXCLUDED.run_id,
            raw_payload = EXCLUDED.raw_payload,
            collected_at = now()
        """,
        (
            instrument_id,
            trade_date,
            source_provider,
            _clean_number(row.get("open")),
            _clean_number(row.get("high")),
            _clean_number(row.get("low")),
            close_price,
            currency_code,
            run_id,
            Jsonb(_row_payload(row, ["open", "high", "low", "close", "price", "prev_close"])),
        ),
    )


def upsert_daily_indicator(
    conn: psycopg.Connection,
    instrument_id: int,
    trade_date: datetime.date,
    source_provider: str,
    row: pd.Series,
    run_id: str,
) -> None:
    conn.execute(
        """
        INSERT INTO daily_indicators (
            instrument_id, trade_date, price_source_provider, rsi14, ma60, ma120, ma240,
            diff_60_pct, diff_120_pct, diff_240_pct, near_60, near_120, near_240,
            macd, macd_signal, macd_hist, macd_state, bollinger_width_pct,
            bollinger_percent_b, high_52w, low_52w, from_high_pct, volume_ratio,
            change_pct, gap_pct, candle_body_pct, candle_range_pct, upper_shadow_pct,
            lower_shadow_pct, candle_type, trend, trend_score, run_id
        )
        VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
        )
        ON CONFLICT (instrument_id, trade_date) DO UPDATE SET
            price_source_provider = EXCLUDED.price_source_provider,
            rsi14 = EXCLUDED.rsi14,
            ma60 = EXCLUDED.ma60,
            ma120 = EXCLUDED.ma120,
            ma240 = EXCLUDED.ma240,
            diff_60_pct = EXCLUDED.diff_60_pct,
            diff_120_pct = EXCLUDED.diff_120_pct,
            diff_240_pct = EXCLUDED.diff_240_pct,
            near_60 = EXCLUDED.near_60,
            near_120 = EXCLUDED.near_120,
            near_240 = EXCLUDED.near_240,
            macd = EXCLUDED.macd,
            macd_signal = EXCLUDED.macd_signal,
            macd_hist = EXCLUDED.macd_hist,
            macd_state = EXCLUDED.macd_state,
            bollinger_width_pct = EXCLUDED.bollinger_width_pct,
            bollinger_percent_b = EXCLUDED.bollinger_percent_b,
            high_52w = EXCLUDED.high_52w,
            low_52w = EXCLUDED.low_52w,
            from_high_pct = EXCLUDED.from_high_pct,
            volume_ratio = EXCLUDED.volume_ratio,
            change_pct = EXCLUDED.change_pct,
            gap_pct = EXCLUDED.gap_pct,
            candle_body_pct = EXCLUDED.candle_body_pct,
            candle_range_pct = EXCLUDED.candle_range_pct,
            upper_shadow_pct = EXCLUDED.upper_shadow_pct,
            lower_shadow_pct = EXCLUDED.lower_shadow_pct,
            candle_type = EXCLUDED.candle_type,
            trend = EXCLUDED.trend,
            trend_score = EXCLUDED.trend_score,
            run_id = EXCLUDED.run_id,
            calculated_at = now()
        """,
        (
            instrument_id,
            trade_date,
            source_provider,
            _clean_number(row.get("rsi")),
            _clean_number(row.get("ma_60")),
            _clean_number(row.get("ma_120")),
            _clean_number(row.get("ma_240")),
            _clean_number(row.get("diff_60")),
            _clean_number(row.get("diff_120")),
            _clean_number(row.get("diff_240")),
            _clean_bool(row.get("near_60")),
            _clean_bool(row.get("near_120")),
            _clean_bool(row.get("near_240")),
            _clean_number(row.get("macd")),
            _clean_number(row.get("macd_signal")),
            _clean_number(row.get("macd_hist")),
            _clean_text(row.get("macd_state")) or "Unknown",
            _clean_number(row.get("bollinger_width_pct")),
            _clean_number(row.get("bollinger_percent_b")),
            _clean_number(row.get("high_52w")),
            _clean_number(row.get("low_52w")),
            _clean_number(row.get("from_high_pct")),
            _clean_number(row.get("volume_ratio")),
            _clean_number(row.get("change_pct")),
            _clean_number(row.get("gap_pct")),
            _clean_number(row.get("candle_body_pct")),
            _clean_number(row.get("candle_range_pct")),
            _clean_number(row.get("upper_shadow_pct")),
            _clean_number(row.get("lower_shadow_pct")),
            _clean_text(row.get("candle_type")) or "Unknown",
            _clean_text(row.get("trend")),
            _clean_int(row.get("trend_score")),
            run_id,
        ),
    )


def upsert_fundamentals(
    conn: psycopg.Connection,
    instrument_id: int,
    trade_date: datetime.date,
    source_provider: str,
    row: pd.Series,
    run_id: str,
) -> None:
    conn.execute(
        """
        INSERT INTO instrument_fundamentals (
            instrument_id, as_of_date, source_provider, trailing_pe, price_to_book,
            return_on_equity_pct, revenue_growth_pct, market_cap, target_price,
            shares_outstanding, raw_payload, run_id
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NULL, %s, %s)
        ON CONFLICT (instrument_id, as_of_date, source_provider) DO UPDATE SET
            trailing_pe = EXCLUDED.trailing_pe,
            price_to_book = EXCLUDED.price_to_book,
            return_on_equity_pct = EXCLUDED.return_on_equity_pct,
            revenue_growth_pct = EXCLUDED.revenue_growth_pct,
            market_cap = EXCLUDED.market_cap,
            target_price = EXCLUDED.target_price,
            raw_payload = EXCLUDED.raw_payload,
            run_id = EXCLUDED.run_id,
            collected_at = now()
        """,
        (
            instrument_id,
            trade_date,
            source_provider,
            _clean_number(row.get("trailing_pe")),
            _clean_number(row.get("price_to_book")),
            _clean_number(row.get("return_on_equity")),
            _clean_number(row.get("revenue_growth")),
            _clean_number(row.get("market_cap")),
            _clean_number(row.get("target_price")),
            Jsonb(
                _row_payload(
                    row,
                    ["trailing_pe", "price_to_book", "return_on_equity", "revenue_growth", "market_cap", "target_price"],
                )
            ),
            run_id,
        ),
    )


def upsert_scan_result(
    conn: psycopg.Connection,
    run_id: str,
    instrument_id: int,
    market_key: str,
    universe_key: str,
    trade_date: datetime.date,
    row: pd.Series,
    rank_no: int,
) -> None:
    conn.execute(
        """
        INSERT INTO scan_results (
            run_id, instrument_id, market_key, universe_key, trade_date,
            chart_score, technical_score, fundamental_score, theme_score, flow_score,
            composite_score, rank_no, setup_tags, risk_flags, summary_payload
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, ARRAY[]::TEXT[], ARRAY[]::TEXT[], %s)
        ON CONFLICT (run_id, instrument_id) DO UPDATE SET
            chart_score = EXCLUDED.chart_score,
            technical_score = EXCLUDED.technical_score,
            fundamental_score = EXCLUDED.fundamental_score,
            theme_score = EXCLUDED.theme_score,
            flow_score = EXCLUDED.flow_score,
            composite_score = EXCLUDED.composite_score,
            rank_no = EXCLUDED.rank_no,
            summary_payload = EXCLUDED.summary_payload
        """,
        (
            run_id,
            instrument_id,
            home_market_key(market_key),
            universe_key,
            trade_date,
            _clean_number(row.get("chart_score")),
            _clean_number(row.get("technical_score")),
            _clean_number(row.get("fundamental_score")),
            _clean_number(row.get("theme_score")),
            _clean_number(row.get("flow_score")),
            _clean_number(row.get("composite_score")),
            rank_no,
            Jsonb(
                _row_payload(
                    row,
                    ["symbol", "name_local", "sector", "change_pct", "candle_type", "trend", "composite_score"],
                )
            ),
        ),
    )


def upsert_market_snapshot(
    conn: psycopg.Connection,
    market_key: str,
    universe_key: str,
    trade_date: datetime.date,
    frame: pd.DataFrame,
    run_id: str,
) -> None:
    change = pd.to_numeric(frame.get("change_pct"), errors="coerce") if "change_pct" in frame else pd.Series(dtype=float)
    rsi = pd.to_numeric(frame.get("rsi"), errors="coerce") if "rsi" in frame else pd.Series(dtype=float)
    score = pd.to_numeric(frame.get("composite_score"), errors="coerce") if "composite_score" in frame else pd.Series(dtype=float)
    market_score = round(float(score.dropna().mean()), 4) if not score.dropna().empty else None
    conn.execute(
        """
        INSERT INTO market_snapshots (
            market_key, universe_key, trade_date, run_id, total_count, scanned_count,
            success_count, failed_count, advance_count, decline_count, unchanged_count,
            avg_change_pct, median_change_pct, avg_rsi14, bullish_breadth_pct,
            avg_composite_score, market_score, regime, risk_level, macro_payload
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, 0, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (market_key, trade_date, universe_key) DO UPDATE SET
            run_id = EXCLUDED.run_id,
            total_count = EXCLUDED.total_count,
            scanned_count = EXCLUDED.scanned_count,
            success_count = EXCLUDED.success_count,
            advance_count = EXCLUDED.advance_count,
            decline_count = EXCLUDED.decline_count,
            unchanged_count = EXCLUDED.unchanged_count,
            avg_change_pct = EXCLUDED.avg_change_pct,
            median_change_pct = EXCLUDED.median_change_pct,
            avg_rsi14 = EXCLUDED.avg_rsi14,
            bullish_breadth_pct = EXCLUDED.bullish_breadth_pct,
            avg_composite_score = EXCLUDED.avg_composite_score,
            market_score = EXCLUDED.market_score,
            regime = EXCLUDED.regime,
            risk_level = EXCLUDED.risk_level,
            macro_payload = EXCLUDED.macro_payload,
            created_at = now()
        """,
        (
            home_market_key(market_key),
            universe_key,
            trade_date,
            run_id,
            len(frame),
            len(frame),
            len(frame),
            int((change > 0).sum()),
            int((change < 0).sum()),
            int((change == 0).sum()),
            round(float(change.dropna().mean()), 4) if not change.dropna().empty else None,
            round(float(change.dropna().median()), 4) if not change.dropna().empty else None,
            round(float(rsi.dropna().mean()), 4) if not rsi.dropna().empty else None,
            round(float((change > 0).sum() / len(frame) * 100), 4) if len(frame) else None,
            market_score,
            market_score,
            regime_for_score(market_score),
            risk_for_score(market_score),
            Jsonb({}),
        ),
    )


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


def upsert_sector_snapshots(
    conn: psycopg.Connection,
    market_key: str,
    universe_key: str,
    trade_date: datetime.date,
    frame: pd.DataFrame,
    run_id: str,
) -> None:
    if "sector" not in frame.columns or frame.empty:
        return
    for sector, group in frame.groupby("sector", dropna=False):
        sector_name = str(sector or "Unknown")
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
        conn.execute(
            """
            INSERT INTO sector_snapshots (
                market_key, universe_key, trade_date, sector, run_id, instrument_count,
                advance_count, decline_count, avg_change_pct, median_change_pct,
                avg_rsi14, avg_composite_score, top_instruments
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (market_key, trade_date, universe_key, sector) DO UPDATE SET
                run_id = EXCLUDED.run_id,
                instrument_count = EXCLUDED.instrument_count,
                advance_count = EXCLUDED.advance_count,
                decline_count = EXCLUDED.decline_count,
                avg_change_pct = EXCLUDED.avg_change_pct,
                median_change_pct = EXCLUDED.median_change_pct,
                avg_rsi14 = EXCLUDED.avg_rsi14,
                avg_composite_score = EXCLUDED.avg_composite_score,
                top_instruments = EXCLUDED.top_instruments,
                created_at = now()
            """,
            (
                home_market_key(market_key),
                universe_key,
                trade_date,
                sector_name,
                run_id,
                len(group),
                int((change > 0).sum()),
                int((change < 0).sum()),
                round(float(change.dropna().mean()), 4) if not change.dropna().empty else None,
                round(float(change.dropna().median()), 4) if not change.dropna().empty else None,
                round(float(rsi.dropna().mean()), 4) if not rsi.dropna().empty else None,
                round(float(score.dropna().mean()), 4) if not score.dropna().empty else None,
                Jsonb(top),
            ),
        )


def load_scan_frame(
    market_key: str,
    date_str: str,
    frame: pd.DataFrame,
    explicit_url: str | None = None,
    universe_key: str | None = None,
) -> str:
    if frame.empty:
        raise ValueError("Cannot load an empty scan frame")
    market = MARKETS[market_key]
    trade_date = datetime.strptime(date_str, "%Y%m%d").date()
    universe_key = universe_key or market_key
    source_provider = price_source_for_market(market_key)
    _, currency_code, _ = country_currency_for_market(market_key)

    with connect(explicit_url) as conn:
        seed_reference_data(conn)
        run_id = create_run(conn, market_key, universe_key, trade_date, len(frame))
        ranked = frame.copy()
        if "composite_score" in ranked.columns:
            ranked = ranked.sort_values("composite_score", ascending=False, na_position="last")
        instrument_ids: dict[str, int] = {}
        for rank_no, (_, row) in enumerate(ranked.iterrows(), start=1):
            instrument_id = upsert_instrument(conn, market, row)
            symbol = _clean_text(row.get("symbol")) or str(instrument_id)
            instrument_ids[symbol] = instrument_id
            upsert_universe_membership(conn, universe_key, instrument_id, trade_date, rank_no)
            upsert_daily_price(conn, instrument_id, trade_date, source_provider, row, run_id, currency_code)
            upsert_daily_indicator(conn, instrument_id, trade_date, source_provider, row, run_id)
            upsert_fundamentals(conn, instrument_id, trade_date, source_provider, row, run_id)
            upsert_scan_result(conn, run_id, instrument_id, market_key, universe_key, trade_date, row, rank_no)
        upsert_market_snapshot(conn, market_key, universe_key, trade_date, ranked, run_id)
        upsert_sector_snapshots(conn, market_key, universe_key, trade_date, ranked, run_id)
        finish_run(conn, run_id, status="success", success_count=len(instrument_ids))
        return run_id


def load_csv(market_key: str, date_str: str, explicit_url: str | None = None) -> str:
    _, frame, _ = load_frame(market_key, date_str)
    return load_scan_frame(market_key, date_str, frame, explicit_url)


def print_counts(explicit_url: str | None = None) -> None:
    tables = [
        "markets",
        "universe_definitions",
        "instruments",
        "universe_memberships",
        "daily_prices",
        "daily_indicators",
        "instrument_fundamentals",
        "scan_results",
        "market_snapshots",
        "sector_snapshots",
        "collection_runs",
    ]
    with connect(explicit_url) as conn:
        for table in tables:
            count = conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            print(f"{table}: {count}")


def main() -> None:
    parser = argparse.ArgumentParser(description="SearchMarket Postgres utilities.")
    parser.add_argument("--database-url", default=None, help="Postgres DATABASE_URL. Defaults to env or local Docker URL.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init", help="Apply schema and seed reference tables.")

    load_parser = subparsers.add_parser("load-csv", help="Load an existing scan CSV into Postgres.")
    load_parser.add_argument("--market", required=True, choices=sorted(MARKETS.keys()))
    load_parser.add_argument("--date", required=True, help="YYYYMMDD")

    subparsers.add_parser("counts", help="Print core table row counts.")

    args = parser.parse_args()
    if args.command == "init":
        init_db(args.database_url)
        print("database initialized")
    elif args.command == "load-csv":
        run_id = load_csv(args.market, args.date, args.database_url)
        print(f"loaded {args.market} {args.date}: run_id={run_id}")
    elif args.command == "counts":
        print_counts(args.database_url)


if __name__ == "__main__":
    main()

