from __future__ import annotations

import os

import psycopg


DEFAULT_DATABASE_URL = "postgresql://searchmarket:searchmarket@localhost:5433/searchmarket"


def database_url(explicit_url: str | None = None) -> str:
    return explicit_url or os.getenv("DATABASE_URL") or DEFAULT_DATABASE_URL


def connect(explicit_url: str | None = None) -> psycopg.Connection:
    return psycopg.connect(database_url(explicit_url))
