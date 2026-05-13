from __future__ import annotations

import os

import psycopg


DEFAULT_DATABASE_URL = "postgresql://searchmarket:searchmarket@localhost:5433/searchmarket"


def resolve_database_url(database_url: str | None = None) -> str:
    return database_url or os.getenv("DATABASE_URL") or DEFAULT_DATABASE_URL


def database_url(database_url: str | None = None) -> str:
    return resolve_database_url(database_url)


def connect(database_url: str | None = None) -> psycopg.Connection:
    return psycopg.connect(resolve_database_url(database_url))
