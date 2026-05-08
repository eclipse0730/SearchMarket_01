from __future__ import annotations

from market_scanner.storage.connection import connect


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
