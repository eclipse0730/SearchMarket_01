from __future__ import annotations

import psycopg

from market_scanner.config.markets import MARKETS
from market_scanner.storage.common import (
    UNIVERSE_MARKET_ALIASES,
    country_currency_for_market,
    default_asset_filter,
    home_market_key,
)


DEPRECATED_MARKET_KEYS = ["kospi-all", "kosdaq-all", "us-all"]
DEPRECATED_UNIVERSE_KEYS = ["kospi-all", "kosdaq-all", "us-all"]


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
