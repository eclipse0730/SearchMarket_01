from __future__ import annotations

from pathlib import Path

from market_scanner.storage.connection import connect
from market_scanner.storage.reference import seed_reference_data


SCHEMA_PATH = Path(__file__).resolve().parent.parent.parent / "docs" / "database_schema_v1.sql"


def init_db(database_url: str | None = None) -> None:
    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
    with connect(database_url) as conn:
        conn.execute(schema_sql)
        seed_reference_data(conn)
