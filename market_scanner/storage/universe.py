from __future__ import annotations

from datetime import date
from typing import Any

import psycopg

from market_scanner.domain.market_policy import home_market_key
from market_scanner.storage.connection import connect


def upsert_universe_membership(
    conn: psycopg.Connection,
    universe_key: str,
    instrument_id: int,
    trade_date: date,
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
        conn.execute("DELETE FROM universe_memberships WHERE universe_key = ANY(%s)", (universe_keys,))
        return

    conn.execute("DELETE FROM universe_memberships")


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
