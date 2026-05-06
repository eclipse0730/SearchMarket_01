from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import psycopg
from psycopg.types.json import Jsonb

from market_scanner.config.markets import MARKETS, REPRESENTATIVE_UNIVERSE_LOADERS
from market_scanner.models import MarketDefinition


DEFAULT_DATABASE_URL = "postgresql://searchmarket:searchmarket@localhost:5433/searchmarket"
SCHEMA_PATH = Path(__file__).resolve().parent.parent.parent / "docs" / "database_schema_v1.sql"
INSTRUMENTS_PATH = Path(__file__).resolve().parent.parent / "assets" / "instruments.json"
REFRESH_LOG_SAMPLE_LIMIT = 30
DEPRECATED_MARKET_KEYS = ["kospi-all", "kosdaq-all", "us-all"]
DEPRECATED_UNIVERSE_KEYS = ["kospi-all", "kosdaq-all", "us-all"]
UNIVERSE_MARKET_ALIASES = {
    "nasdaq": "us",
    "nyse": "us",
    "amex": "us",
    "nasdaq100": "us",
    "sp500": "us",
    "kospi100": "kospi",
    "kospi200": "kospi",
    "kosdaq150": "kosdaq",
}

_MARKET_UNIVERSE_EXPANSION: dict[str, list[str]] = {
    "us": ["nasdaq", "nyse", "amex", "nasdaq100", "sp500"],
    "kospi": ["kospi", "kospi100", "kospi200"],
    "kosdaq": ["kosdaq", "kosdaq150"],
}


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
    if market_key in UNIVERSE_MARKET_ALIASES:
        return UNIVERSE_MARKET_ALIASES[market_key]
    return market_key


def default_asset_filter(market_key: str) -> list[str]:
    if market_key in {"global-indices"}:
        return ["index"]
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


def cleanup_deprecated_reference_data(conn: psycopg.Connection) -> None:
    conn.execute("DELETE FROM generated_reports WHERE market_key = ANY(%s) OR universe_key = ANY(%s)", (DEPRECATED_MARKET_KEYS, DEPRECATED_UNIVERSE_KEYS))
    conn.execute("DELETE FROM sector_snapshots WHERE market_key = ANY(%s) OR universe_key = ANY(%s)", (DEPRECATED_MARKET_KEYS, DEPRECATED_UNIVERSE_KEYS))
    conn.execute("DELETE FROM market_snapshots WHERE market_key = ANY(%s) OR universe_key = ANY(%s)", (DEPRECATED_MARKET_KEYS, DEPRECATED_UNIVERSE_KEYS))
    conn.execute("DELETE FROM scan_results WHERE market_key = ANY(%s) OR universe_key = ANY(%s)", (DEPRECATED_MARKET_KEYS, DEPRECATED_UNIVERSE_KEYS))
    conn.execute("DELETE FROM universe_memberships WHERE universe_key = ANY(%s)", (DEPRECATED_UNIVERSE_KEYS,))
    conn.execute("UPDATE collection_runs SET universe_key = NULL WHERE universe_key = ANY(%s)", (DEPRECATED_UNIVERSE_KEYS,))
    conn.execute("UPDATE collection_runs SET market_key = NULL WHERE market_key = ANY(%s)", (DEPRECATED_MARKET_KEYS,))

    conn.execute(
        """
        DELETE FROM instrument_news
        WHERE instrument_id IN (
            SELECT instrument_id FROM instruments WHERE market_key = ANY(%s)
        )
        """,
        (DEPRECATED_MARKET_KEYS,),
    )
    for table in ["instrument_fundamentals", "daily_indicators", "daily_prices"]:
        conn.execute(
            f"""
            DELETE FROM {table}
            WHERE instrument_id IN (
                SELECT instrument_id FROM instruments WHERE market_key = ANY(%s)
            )
            """,
            (DEPRECATED_MARKET_KEYS,),
        )
    conn.execute("DELETE FROM instruments WHERE market_key = ANY(%s)", (DEPRECATED_MARKET_KEYS,))
    conn.execute("DELETE FROM universe_definitions WHERE universe_key = ANY(%s)", (DEPRECATED_UNIVERSE_KEYS,))
    conn.execute("DELETE FROM markets WHERE market_key = ANY(%s)", (DEPRECATED_MARKET_KEYS,))
    conn.execute(
        """
        DELETE FROM news_items
        WHERE NOT EXISTS (
            SELECT 1 FROM instrument_news
            WHERE instrument_news.news_id = news_items.news_id
        )
        """
    )


def seed_reference_data(conn: psycopg.Connection) -> None:
    home_keys = {home_market_key(key) for key in MARKETS}
    active_market_keys = sorted((set(MARKETS) | home_keys) - set(UNIVERSE_MARKET_ALIASES))
    extra_universes = {
        "nasdaq": ("us", "NASDAQ", "All NASDAQ-listed stocks."),
        "nyse": ("us", "NYSE", "All NYSE-listed stocks."),
        "amex": ("us", "AMEX", "All AMEX-listed stocks."),
        "nasdaq100": ("us", "NASDAQ 100", "NASDAQ 100 component universe."),
        "sp500": ("us", "S&P 500", "S&P 500 component universe."),
        "kospi100": ("kospi", "KOSPI 100", "KOSPI 100 component universe."),
        "kospi200": ("kospi", "KOSPI 200", "KOSPI 200 component universe."),
        "kosdaq150": ("kosdaq", "KOSDAQ 150", "KOSDAQ 150 component universe."),
    }
    active_universe_keys = sorted(set(MARKETS) | set(extra_universes))
    cleanup_deprecated_reference_data(conn)

    conn.execute(
        """
        UPDATE markets
        SET is_active = FALSE
        WHERE NOT (market_key = ANY(%s))
        """,
        (active_market_keys,),
    )
    conn.execute(
        """
        UPDATE universe_definitions
        SET is_active = FALSE
        WHERE NOT (universe_key = ANY(%s))
        """,
        (active_universe_keys,),
    )

    for key in active_market_keys:
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

    for universe_key, (market_key, label, description) in extra_universes.items():
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
                market_key,
                label,
                description,
                description,
                default_asset_filter(universe_key),
            ),
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

    name =(_clean_text(row.get("name_local")) or _clean_text(row.get("name_en")) or "").upper()
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
        return code.zfill(6) if code.isdigit() else (display_symbol or code)
    return display_symbol or symbol


def upsert_instrument(
    conn: psycopg.Connection,
    market: MarketDefinition,
    row: pd.Series,
    *,
    source_provider: str = "csv",
    source_rank: int = 80,
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
            source_provider,
            source_rank,
            Jsonb(raw_metadata),
        ),
    ).fetchone()
    return int(result[0])


def _source_rank(source_provider: str | None) -> int:
    source = (source_provider or "").lower()
    if source == "manual":
        return 10
    if source == "static":
        return 20
    if source in {"fdr", "naver", "yfinance"}:
        return 60
    if source == "csv":
        return 80
    return 100


def _load_master_payload() -> dict[str, dict[str, Any]]:
    if not INSTRUMENTS_PATH.exists():
        return {}
    payload = json.loads(INSTRUMENTS_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected object payload in {INSTRUMENTS_PATH}")
    return {
        str(symbol).strip(): values
        for symbol, values in payload.items()
        if str(symbol).strip() and isinstance(values, dict)
    }


def _master_row(symbol: str, values: dict[str, Any]) -> pd.Series:
    return pd.Series(
        {
            "symbol": symbol,
            "display_symbol": values.get("display_symbol"),
            "name_en": values.get("name_en"),
            "name_local": values.get("name_local"),
            "sector": values.get("sector"),
            "description": values.get("description"),
        }
    )


def load_master(market_key: str | None = None, explicit_url: str | None = None) -> int:
    from market_scanner.config.markets import clear_db_instrument_meta_cache
    payload = _load_master_payload()
    loaded = 0
    with connect(explicit_url) as conn:
        seed_reference_data(conn)
        for symbol, values in sorted(payload.items()):
            record_market_key = _clean_text(values.get("market_key"))
            if not record_market_key:
                continue
            if market_key and record_market_key != market_key:
                continue
            if record_market_key not in MARKETS:
                continue
            source_provider = _clean_text(values.get("source")) or "static"
            upsert_instrument(
                conn,
                MARKETS[record_market_key],
                _master_row(symbol, values),
                source_provider=source_provider,
                source_rank=_source_rank(source_provider),
            )
            loaded += 1
    if loaded:
        clear_db_instrument_meta_cache()
    return loaded


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
    params: dict[str, Any] | None = None,
    error_samples: list[Any] | None = None,
    notes: str | None = None,
) -> None:
    conn.execute(
        """
        UPDATE collection_runs
        SET status = %s,
            finished_at = now(),
            success_count = %s,
            failed_count = %s,
            skipped_count = %s,
            params = params || %s,
            error_samples = %s,
            notes = COALESCE(%s, notes)
        WHERE run_id = %s
        """,
        (
            status,
            success_count,
            failed_count,
            skipped_count,
            Jsonb(params or {}),
            Jsonb(error_samples or []),
            notes,
            run_id,
        ),
    )


def upsert_universe_membership(
    conn: psycopg.Connection,
    universe_key: str,
    instrument_id: int,
    trade_date: datetime.date,
    rank_no: int,
    *,
    source_provider: str = "csv",
) -> None:
    conn.execute(
        """
        INSERT INTO universe_memberships (
            universe_key, instrument_id, effective_from, effective_to, rank_no, source_provider
        )
        VALUES (%s, %s, %s, NULL, %s, %s)
        ON CONFLICT (universe_key, instrument_id, effective_from) DO UPDATE SET
            effective_to = NULL,
            rank_no = EXCLUDED.rank_no,
            source_provider = EXCLUDED.source_provider
        """,
        (universe_key, instrument_id, trade_date, rank_no, source_provider),
    )


def create_universe_run(
    conn: psycopg.Connection,
    market_key: str,
    universe_key: str,
    trade_date: datetime.date,
    requested_count: int,
    *,
    params: dict[str, Any] | None = None,
) -> str:
    run_params = {"loaded_from": "universe_loader", "scan_market_key": market_key}
    if params:
        run_params.update(params)
    result = conn.execute(
        """
        INSERT INTO collection_runs (
            run_type, market_key, universe_key, trade_date, source_provider, status,
            requested_count, params
        )
        VALUES ('universe', %s, %s, %s, 'market_scanner', 'running', %s, %s)
        RETURNING run_id
        """,
        (
            home_market_key(market_key),
            universe_key,
            trade_date,
            requested_count,
            Jsonb(run_params),
        ),
    ).fetchone()
    return str(result[0])


def _market_universe_keys(conn: psycopg.Connection, market_key: str) -> list[str]:
    home_key = home_market_key(market_key)
    rows = conn.execute(
        "SELECT universe_key FROM universe_definitions WHERE market_key = %s ORDER BY universe_key",
        (home_key,),
    ).fetchall()
    keys = [str(row[0]) for row in rows]
    return keys or [home_key]


def reset_loaded_data(
    conn: psycopg.Connection,
    market_key: str | None = None,
    universe_keys: list[str] | None = None,
) -> None:
    if market_key:
        home_key = home_market_key(market_key)
        universe_keys = universe_keys or _market_universe_keys(conn, home_key)
        print(f"  reset scope: membership only, market={home_key}, universes={', '.join(universe_keys)}")
        conn.execute("DELETE FROM universe_memberships WHERE universe_key = ANY(%s)", (universe_keys,))
        return

    print("  reset scope: membership only, all universes; collection_runs retained")
    conn.execute("DELETE FROM universe_memberships")


def _dedupe_symbols(symbols: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for symbol in symbols:
        text = _clean_text(symbol)
        if not text or text in seen:
            continue
        deduped.append(text)
        seen.add(text)
    return deduped


def _master_row_from_universe(
    market: MarketDefinition,
    symbol: str,
    metadata: dict[str, Any],
) -> pd.Series:
    meta = metadata.get(symbol)
    return pd.Series(
        {
            "symbol": symbol,
            "display_symbol": market.display_symbol_builder(symbol),
            "name_en": getattr(meta, "name_en", None) or symbol,
            "name_local": getattr(meta, "name_local", None) or getattr(meta, "name_en", None) or symbol,
            "sector": getattr(meta, "sector", None) or "Unknown",
            "description": getattr(meta, "description", None) or "No description",
        }
    )


def _default_refresh_market_keys() -> list[str]:
    return sorted(key for key in MARKETS if key not in UNIVERSE_MARKET_ALIASES)


def _universe_market_key(universe_key: str) -> str:
    return UNIVERSE_MARKET_ALIASES.get(universe_key, home_market_key(universe_key))


def _sample_symbols(symbols: list[str], limit: int = REFRESH_LOG_SAMPLE_LIMIT) -> list[str]:
    return symbols[:limit]


def _current_universe_membership(conn: psycopg.Connection, universe_key: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT i.symbol, um.rank_no
        FROM universe_memberships um
        JOIN instruments i ON i.instrument_id = um.instrument_id
        WHERE um.universe_key = %s
          AND um.effective_to IS NULL
          AND i.is_active = TRUE
        ORDER BY um.rank_no NULLS LAST, i.symbol
        """,
        (universe_key,),
    ).fetchall()
    return [{"symbol": str(row[0]), "rank_no": row[1]} for row in rows]


def _current_instrument_symbols(conn: psycopg.Connection, market_key: str) -> set[str]:
    rows = conn.execute(
        """
        SELECT symbol
        FROM instruments
        WHERE market_key = %s
          AND is_active = TRUE
        """,
        (home_market_key(market_key),),
    ).fetchall()
    return {str(row[0]) for row in rows}


def _membership_compare(current: list[dict[str, Any]], symbols: list[str]) -> dict[str, Any]:
    current_symbols = [str(row["symbol"]) for row in current]
    current_set = set(current_symbols)
    new_set = set(symbols)
    matched = sorted(current_set & new_set)
    added = [symbol for symbol in symbols if symbol not in current_set]
    removed = [symbol for symbol in current_symbols if symbol not in new_set]

    current_rank = {str(row["symbol"]): row.get("rank_no") for row in current}
    new_rank = {symbol: index for index, symbol in enumerate(symbols, start=1)}
    rank_changed = [
        {
            "symbol": symbol,
            "old_rank": current_rank.get(symbol),
            "new_rank": new_rank[symbol],
        }
        for symbol in symbols
        if symbol in current_rank and current_rank.get(symbol) != new_rank[symbol]
    ]

    return {
        "previous_count": len(current_symbols),
        "fetched_count": len(symbols),
        "matched_count": len(matched),
        "mismatch_count": len(added) + len(removed),
        "added_count": len(added),
        "removed_count": len(removed),
        "rank_changed_count": len(rank_changed),
        "membership_unchanged": current_symbols == symbols,
        "added_symbols": added,
        "removed_symbols": removed,
        "rank_changed": rank_changed,
    }


def _refresh_log_params(
    compare: dict[str, Any],
    instrument_added: list[str],
    membership_rewritten: bool,
    instrument_upserted: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "comparison": {
            "previous_count": compare["previous_count"],
            "fetched_count": compare["fetched_count"],
            "matched_count": compare["matched_count"],
            "mismatch_count": compare["mismatch_count"],
            "added_count": compare["added_count"],
            "removed_count": compare["removed_count"],
            "rank_changed_count": compare["rank_changed_count"],
            "membership_unchanged": compare["membership_unchanged"],
            "membership_rewritten": membership_rewritten,
        },
        "samples": {
            "added_symbols": _sample_symbols(compare["added_symbols"]),
            "removed_symbols": _sample_symbols(compare["removed_symbols"]),
            "rank_changed": compare["rank_changed"][:REFRESH_LOG_SAMPLE_LIMIT],
            "instrument_added": _sample_symbols(instrument_added),
            "instrument_upserted": _sample_symbols(instrument_upserted or []),
        },
    }


def _print_refresh_log(universe_key: str, summary: dict[str, Any]) -> None:
    comparison = summary["comparison"]
    print(
        "  refresh-master "
        f"[{universe_key}] previous={comparison['previous_count']} "
        f"fetched={comparison['fetched_count']} "
        f"matched={comparison['matched_count']} "
        f"mismatch={comparison['mismatch_count']} "
        f"added={comparison['added_count']} "
        f"removed={comparison['removed_count']} "
        f"rank_changed={comparison['rank_changed_count']}"
    )
    if comparison["membership_rewritten"]:
        print(f"    membership: rewritten ({summary['membership_upserted_count']} rows)")
    else:
        print("    membership: unchanged, rewrite skipped")
    print(
        f"    instruments: upserted={summary['instrument_upserted_count']} "
        f"new={summary['instrument_added_count']} "
        f"existing={summary['instrument_existing_count']}"
    )

    samples = summary["samples"]
    if samples["added_symbols"]:
        print(f"    added sample: {', '.join(samples['added_symbols'])}")
    if samples["removed_symbols"]:
        print(f"    removed sample: {', '.join(samples['removed_symbols'])}")
    if samples["rank_changed"]:
        rank_sample = ", ".join(
            f"{item['symbol']}:{item['old_rank']}->{item['new_rank']}"
            for item in samples["rank_changed"]
        )
        print(f"    rank changed sample: {rank_sample}")
    if samples["instrument_added"]:
        print(f"    new instrument sample: {', '.join(samples['instrument_added'])}")
    if samples["instrument_upserted"]:
        print(f"    upserted instrument sample: {', '.join(samples['instrument_upserted'])}")


def _refresh_universe_membership(
    conn: psycopg.Connection,
    market_key: str,
    universe_key: str,
    symbols: list[str],
    metadata: dict[str, Any],
    trade_date,
    *,
    current_membership: list[dict[str, Any]] | None = None,
    existing_instruments: set[str] | None = None,
    force_rewrite: bool = False,
) -> dict[str, Any]:
    if not symbols:
        run_id = create_universe_run(conn, market_key, universe_key, trade_date, 0)
        finish_run(conn, run_id, status="failed", success_count=0, notes="universe loader returned 0 symbols")
        print(f"  refresh-master [{universe_key}] FAILED: universe loader returned 0 symbols")
        return {"run_id": run_id, "comparison": {"fetched_count": 0, "mismatch_count": 0}, "instrument_added_count": 0, "instrument_upserted_count": 0, "membership_upserted_count": 0, "samples": {}}
    market = MARKETS[market_key]
    if current_membership is None:
        current_membership = _current_universe_membership(conn, universe_key)
    comparison = _membership_compare(current_membership, symbols)
    membership_rewritten = force_rewrite or not comparison["membership_unchanged"]
    if existing_instruments is None:
        existing_instruments = _current_instrument_symbols(conn, market_key)
    instrument_added = [symbol for symbol in symbols if symbol not in existing_instruments]
    instrument_upserted_symbols: list[str] = []

    run_id = create_universe_run(
        conn,
        market_key,
        universe_key,
        trade_date,
        len(symbols),
        params=_refresh_log_params(comparison, instrument_added, membership_rewritten),
    )
    if membership_rewritten:
        conn.execute("DELETE FROM universe_memberships WHERE universe_key = %s", (universe_key,))

    instrument_upserted = 0
    membership_upserted = 0
    for rank_no, symbol in enumerate(symbols, start=1):
        instrument_id = upsert_instrument(
            conn,
            market,
            _master_row_from_universe(market, symbol, metadata),
            source_provider="market_scanner",
            source_rank=50,
        )
        instrument_upserted += 1
        instrument_upserted_symbols.append(symbol)
        if membership_rewritten:
            upsert_universe_membership(
                conn,
                universe_key,
                instrument_id,
                trade_date,
                rank_no,
                source_provider="market_scanner",
            )
            membership_upserted += 1

    summary = {
        **_refresh_log_params(
            comparison,
            instrument_added,
            membership_rewritten,
            instrument_upserted_symbols,
        ),
        "run_id": run_id,
        "instrument_upserted_count": instrument_upserted,
        "instrument_added_count": len(instrument_added),
        "instrument_existing_count": instrument_upserted - len(instrument_added),
        "membership_upserted_count": membership_upserted,
    }
    finish_run(
        conn,
        run_id,
        status="success",
        success_count=membership_upserted,
        skipped_count=len(symbols) - membership_upserted,
        params={
            "samples": summary["samples"],
            "instrument_upserted_count": instrument_upserted,
            "instrument_added_count": len(instrument_added),
            "instrument_existing_count": instrument_upserted - len(instrument_added),
            "membership_upserted_count": membership_upserted,
        },
        notes="membership rewritten" if membership_rewritten else "membership unchanged; rewrite skipped",
    )
    _print_refresh_log(universe_key, summary)
    return summary


def refresh_master(
    market_key: str | None = None,
    universe_key: str | None = None,
    date_str: str | None = None,
    explicit_url: str | None = None,
    *,
    reset: bool = False,
) -> dict[str, dict[str, Any]]:
    from market_scanner.config.markets import clear_db_instrument_meta_cache
    trade_date = datetime.strptime(date_str, "%Y%m%d").date() if date_str else datetime.today().date()
    if universe_key:
        universe_market_key = _universe_market_key(universe_key)
        if market_key and market_key != universe_market_key:
            raise ValueError(f"Universe '{universe_key}' belongs to market '{universe_market_key}', not '{market_key}'")
        if universe_key in REPRESENTATIVE_UNIVERSE_LOADERS:
            refresh_targets = [(universe_market_key, universe_key)]
        elif universe_key in MARKETS and universe_key == universe_market_key:
            refresh_targets = [(universe_market_key, universe_key)]
        else:
            raise ValueError(f"Unsupported refresh universe: {universe_key}")
    else:
        market_keys = [market_key] if market_key else _default_refresh_market_keys()
        refresh_targets = []
        for key in market_keys:
            if key in _MARKET_UNIVERSE_EXPANSION:
                refresh_targets.extend((key, u) for u in _MARKET_UNIVERSE_EXPANSION[key])
            else:
                refresh_targets.append((key, key))
    summaries: dict[str, dict[str, Any]] = {}

    with connect(explicit_url) as conn:
        seed_reference_data(conn)
        market_keys = sorted({key for key, _ in refresh_targets})
        universe_keys_by_market: dict[str, list[str]] = {}
        for key, target_universe in refresh_targets:
            universe_keys_by_market.setdefault(key, []).append(target_universe)
        current_memberships: dict[str, list[dict[str, Any]]] = {}
        existing_instruments: dict[str, set[str]] = {}
        if reset:
            for key, universe_keys in universe_keys_by_market.items():
                existing_instruments[key] = _current_instrument_symbols(conn, key)
                for universe_key in universe_keys:
                    current_memberships[universe_key] = _current_universe_membership(conn, universe_key)
            if universe_key:
                for key, target_universes in universe_keys_by_market.items():
                    reset_loaded_data(conn, key, target_universes)
            else:
                reset_loaded_data(conn, market_key if market_key else None)
        for key, target_universe in refresh_targets:
            market = MARKETS[key]
            if target_universe in REPRESENTATIVE_UNIVERSE_LOADERS:
                symbols = _dedupe_symbols(REPRESENTATIVE_UNIVERSE_LOADERS[target_universe]())
            else:
                symbols = _dedupe_symbols(market.universe_loader())
            metadata = market.metadata_loader()
            summaries[target_universe] = _refresh_universe_membership(
                conn,
                key,
                target_universe,
                symbols,
                metadata,
                trade_date,
                current_membership=current_memberships.get(target_universe),
                existing_instruments=existing_instruments.get(key),
                force_rewrite=reset,
            )
    if summaries:
        clear_db_instrument_meta_cache()
    return summaries


def scan_symbols_for_scope(
    market_key: str,
    universe_key: str | None = None,
    explicit_url: str | None = None,
) -> tuple[list[str], str | None]:
    base_market_key = home_market_key(market_key)
    effective_universe_key = universe_key
    if effective_universe_key is None and base_market_key != market_key:
        effective_universe_key = market_key

    with connect(explicit_url) as conn:
        if effective_universe_key:
            row = conn.execute(
                "SELECT market_key FROM universe_definitions WHERE universe_key = %s",
                (effective_universe_key,),
            ).fetchone()
            if row is None:
                raise ValueError(f"Unknown universe: {effective_universe_key}")
            universe_market_key = str(row[0])
            if universe_market_key != base_market_key:
                raise ValueError(
                    f"Universe '{effective_universe_key}' belongs to market '{universe_market_key}', "
                    f"not '{base_market_key}'"
                )
            rows = conn.execute(
                """
                SELECT i.symbol
                FROM universe_memberships um
                JOIN instruments i ON i.instrument_id = um.instrument_id
                WHERE um.universe_key = %s
                  AND um.effective_to IS NULL
                  AND i.market_key = %s
                  AND i.is_active = TRUE
                ORDER BY um.rank_no NULLS LAST, i.symbol
                """,
                (effective_universe_key, base_market_key),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT symbol
                FROM instruments
                WHERE market_key = %s
                  AND is_active = TRUE
                ORDER BY symbol
                """,
                (base_market_key,),
            ).fetchall()
    return [str(row[0]) for row in rows], effective_universe_key


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
        VALUES (%s, %s, %s, %s, %s, %s, %s, NULL, %s, %s, FALSE, %s, %s)
        ON CONFLICT (instrument_id, trade_date, source_provider) DO UPDATE SET
            open_price = EXCLUDED.open_price,
            high_price = EXCLUDED.high_price,
            low_price = EXCLUDED.low_price,
            close_price = EXCLUDED.close_price,
            volume = EXCLUDED.volume,
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
            _clean_int(row.get("volume")),
            currency_code,
            run_id,
            Jsonb(_row_payload(row, ["open", "high", "low", "close", "price", "prev_close", "volume"])),
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
    values = {
        "instrument_id": instrument_id,
        "trade_date": trade_date,
        "price_source_provider": source_provider,
        "rsi14": _clean_number(row.get("rsi")),
        "ma5": _clean_number(row.get("ma_5")),
        "ma20": _clean_number(row.get("ma_20")),
        "ma60": _clean_number(row.get("ma_60")),
        "ma120": _clean_number(row.get("ma_120")),
        "ma240": _clean_number(row.get("ma_240")),
        "diff_5_pct": _clean_number(row.get("diff_5")),
        "diff_20_pct": _clean_number(row.get("diff_20")),
        "diff_60_pct": _clean_number(row.get("diff_60")),
        "diff_120_pct": _clean_number(row.get("diff_120")),
        "diff_240_pct": _clean_number(row.get("diff_240")),
        "near_5": _clean_bool(row.get("near_5")),
        "near_20": _clean_bool(row.get("near_20")),
        "near_60": _clean_bool(row.get("near_60")),
        "near_120": _clean_bool(row.get("near_120")),
        "near_240": _clean_bool(row.get("near_240")),
        "macd": _clean_number(row.get("macd")),
        "macd_signal": _clean_number(row.get("macd_signal")),
        "macd_hist": _clean_number(row.get("macd_hist")),
        "macd_state": _clean_text(row.get("macd_state")) or "Unknown",
        "bollinger_width_pct": _clean_number(row.get("bollinger_width_pct")),
        "bollinger_percent_b": _clean_number(row.get("bollinger_percent_b")),
        "high_52w": _clean_number(row.get("high_52w")),
        "low_52w": _clean_number(row.get("low_52w")),
        "from_high_pct": _clean_number(row.get("from_high_pct")),
        "from_low_pct": _clean_number(row.get("from_low_pct")),
        "high_20d": _clean_number(row.get("high_20d")),
        "low_20d": _clean_number(row.get("low_20d")),
        "high_60d": _clean_number(row.get("high_60d")),
        "low_60d": _clean_number(row.get("low_60d")),
        "breakout_20d": _clean_bool(row.get("breakout_20d")),
        "breakout_60d": _clean_bool(row.get("breakout_60d")),
        "volume_ratio": _clean_number(row.get("volume_ratio")),
        "return_5d": _clean_number(row.get("return_5d")),
        "return_20d": _clean_number(row.get("return_20d")),
        "return_60d": _clean_number(row.get("return_60d")),
        "return_120d": _clean_number(row.get("return_120d")),
        "return_240d": _clean_number(row.get("return_240d")),
        "atr14": _clean_number(row.get("atr14")),
        "atr14_pct": _clean_number(row.get("atr14_pct")),
        "volatility_20d": _clean_number(row.get("volatility_20d")),
        "volatility_60d": _clean_number(row.get("volatility_60d")),
        "change_pct": _clean_number(row.get("change_pct")),
        "gap_pct": _clean_number(row.get("gap_pct")),
        "candle_body_pct": _clean_number(row.get("candle_body_pct")),
        "candle_range_pct": _clean_number(row.get("candle_range_pct")),
        "upper_shadow_pct": _clean_number(row.get("upper_shadow_pct")),
        "lower_shadow_pct": _clean_number(row.get("lower_shadow_pct")),
        "candle_type": _clean_text(row.get("candle_type")) or "Unknown",
        "trend": _clean_text(row.get("trend")),
        "trend_score": _clean_int(row.get("trend_score")),
        "run_id": run_id,
    }
    columns = list(values)
    placeholders = ", ".join(["%s"] * len(columns))
    update_assignments = ",\n            ".join(
        f"{column} = EXCLUDED.{column}"
        for column in columns
        if column not in {"instrument_id", "trade_date"}
    )
    conn.execute(
        f"""
        INSERT INTO daily_indicators ({", ".join(columns)})
        VALUES ({placeholders})
        ON CONFLICT (instrument_id, trade_date) DO UPDATE SET
            {update_assignments},
            calculated_at = now()
        """,
        tuple(values[column] for column in columns),
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


def run_fetch_name(
    market_key: str,
    stale_only: bool = True,
    limit: int | None = None,
    explicit_url: str | None = None,
    delay: float = 0.3,
) -> None:
    """Naver Finance 개별 종목 페이지에서 name_local, sector를 가져와 instruments 업데이트."""
    import time

    from market_scanner.config.markets import clear_db_instrument_meta_cache, fetch_naver_item_meta

    base_key = home_market_key(market_key)

    with connect(explicit_url) as conn:
        if stale_only:
            rows = conn.execute(
                """
                SELECT instrument_id, symbol, name_local, name_en, sector
                FROM instruments
                WHERE market_key = %s
                  AND is_active = TRUE
                  AND (
                      name_local IS NULL
                      OR name_local = symbol
                      OR name_local = display_symbol
                      OR sector = 'Unknown'
                      OR sector IS NULL
                  )
                ORDER BY symbol
                """,
                (base_key,),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT instrument_id, symbol, name_local, name_en, sector
                FROM instruments
                WHERE market_key = %s AND is_active = TRUE
                ORDER BY symbol
                """,
                (base_key,),
            ).fetchall()

        if limit:
            rows = rows[:limit]

        total = len(rows)
        if not total:
            print(f"  fetch_name [{market_key}]: 업데이트 대상 없음 (이미 모두 채워져 있음)")
            return

        print(f"  fetch_name [{market_key}]: {total} 종목 처리 시작")

        success, failed, skipped = 0, 0, 0
        for instrument_id, symbol, curr_name, curr_name_en, curr_sector in rows:
            suffix = ".KS" if base_key == "kospi" else ".KQ"
            code = str(symbol).replace(suffix, "").strip().zfill(6)

            name, sector = fetch_naver_item_meta(code)

            if not name and not sector:
                failed += 1
                if failed <= 10:
                    print(f"    FAIL: {symbol} ({code})")
                time.sleep(delay)
                continue

            # name_local: Naver에서 가져온 값 우선, 없으면 기존 유지
            new_name_local = name or curr_name
            # name_en: placeholder(symbol 그대로)인 경우만 한국어 이름으로 교체
            new_name_en = curr_name_en
            if name and (not curr_name_en or curr_name_en == symbol or curr_name_en == code):
                new_name_en = name
            # sector
            new_sector = sector or curr_sector
            # description
            label = "KOSPI" if base_key == "kospi" else "KOSDAQ"
            new_desc = f"{new_name_local} ({label})" if new_name_local else None

            conn.execute(
                """
                UPDATE instruments
                SET name_local = %s,
                    name_en    = %s,
                    sector     = %s,
                    description = COALESCE(%s, description)
                WHERE instrument_id = %s
                """,
                (new_name_local, new_name_en, new_sector, new_desc, instrument_id),
            )
            success += 1

            if success % 100 == 0:
                print(f"    {success + failed}/{total} 완료 ...")

            time.sleep(delay)

        if success:
            clear_db_instrument_meta_cache()

        print(
            f"  fetch_name [{market_key}] 완료: "
            f"success={success}  failed={failed}  skipped={skipped}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="SearchMarket Postgres utilities.")
    parser.add_argument("--database-url", default=None, help="Postgres DATABASE_URL. Defaults to env or local Docker URL.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init", help="Apply schema and seed reference tables.")

    master_parser = subparsers.add_parser("load-master", help="Load assets/instruments.json into instruments.")
    master_parser.add_argument("--market", choices=sorted(MARKETS.keys()), help="Only load one market's instrument master.")

    refresh_parser = subparsers.add_parser("refresh-master", help="Refresh instruments and universe memberships from market loaders.")
    refresh_parser.add_argument("--market", help="Only refresh one base market, for example us, kospi, kosdaq.")
    refresh_parser.add_argument("--universe", help="Only refresh one universe membership, for example kospi200 or sp500.")
    refresh_parser.add_argument("--date", default=None, help="Membership effective date YYYYMMDD (default: today).")
    refresh_parser.add_argument(
        "--reset",
        action="store_true",
        help="Clear only universe_memberships in the requested scope before refreshing. Instruments, prices, scan results, news, reports, and run logs are retained.",
    )

    subparsers.add_parser("counts", help="Print core table row counts.")

    fetch_name_parser = subparsers.add_parser(
        "fetch-name",
        help="Naver Finance 개별 종목 페이지에서 name_local, sector를 가져와 instruments 업데이트.",
    )
    fetch_name_parser.add_argument(
        "--market", required=True, choices=["kospi", "kosdaq"],
        help="대상 시장 (kospi or kosdaq)",
    )
    fetch_name_parser.add_argument(
        "--all", action="store_true", dest="fetch_all",
        help="sector='Unknown' 또는 name_local 미설정 종목만이 아닌 전체 종목 업데이트",
    )
    fetch_name_parser.add_argument(
        "--limit", type=int, default=None, help="처리할 최대 종목 수 (테스트용)",
    )
    fetch_name_parser.add_argument(
        "--delay", type=float, default=0.3, help="종목 간 요청 딜레이(초, 기본 0.3)",
    )

    args = parser.parse_args()
    if args.command == "init":
        init_db(args.database_url)
        print("database initialized")
    elif args.command == "load-master":
        count = load_master(args.market, args.database_url)
        scope = args.market or "all markets"
        print(f"loaded instrument master for {scope}: {count}")
    elif args.command == "refresh-master":
        if args.market and args.market not in MARKETS:
            parser.error(f"unsupported market '{args.market}'. Supported markets: {', '.join(_default_refresh_market_keys())}")
        try:
            summaries = refresh_master(args.market, args.universe, args.date, args.database_url, reset=args.reset)
        except ValueError as exc:
            parser.error(str(exc))
        total_fetched = sum(summary["comparison"]["fetched_count"] for summary in summaries.values())
        total_mismatch = sum(summary["comparison"]["mismatch_count"] for summary in summaries.values())
        total_new_instruments = sum(summary["instrument_added_count"] for summary in summaries.values())
        failed = [u for u, s in summaries.items() if s["comparison"]["fetched_count"] == 0]
        status_str = f" FAILED={','.join(failed)}" if failed else ""
        print(
            "refresh-master completed: "
            f"universes={len(summaries)} fetched={total_fetched} "
            f"mismatch={total_mismatch} new_instruments={total_new_instruments}{status_str}"
        )
    elif args.command == "counts":
        print_counts(args.database_url)
    elif args.command == "fetch-name":
        run_fetch_name(
            args.market,
            stale_only=not args.fetch_all,
            limit=args.limit,
            explicit_url=args.database_url,
            delay=args.delay,
        )


if __name__ == "__main__":
    main()
