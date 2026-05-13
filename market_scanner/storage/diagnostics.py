from __future__ import annotations

from market_scanner.storage.connection import connect


CORE_TABLES = [
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


def table_counts(database_url: str | None = None) -> dict[str, int]:
    counts: dict[str, int] = {}
    with connect(database_url) as conn:
        for table in CORE_TABLES:
            counts[table] = int(conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0])
    return counts
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
    with connect(database_url) as conn:
        for table in tables:
            count = conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            print(f"{table}: {count}")
