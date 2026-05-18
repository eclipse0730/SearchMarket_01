from __future__ import annotations

import os
from pathlib import Path

import psycopg


DEFAULT_DATABASE_URL = "postgresql://searchmarket:searchmarket@localhost:5433/searchmarket"


def _load_dotenv() -> None:
    env_path = Path(__file__).parents[2] / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        if key and key not in os.environ:
            os.environ[key] = val.strip()


def resolve_database_url(database_url: str | None = None) -> str:
    _load_dotenv()
    return database_url or os.getenv("DATABASE_URL") or DEFAULT_DATABASE_URL


def database_url(database_url: str | None = None) -> str:
    return resolve_database_url(database_url)


def connect(database_url: str | None = None) -> psycopg.Connection:
    return psycopg.connect(resolve_database_url(database_url))
