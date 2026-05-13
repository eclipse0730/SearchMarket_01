from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from market_scanner.config.markets import MARKETS
from market_scanner.domain.instruments import source_rank
from market_scanner.storage.common import clean_text
from market_scanner.storage.connection import connect
from market_scanner.storage.instruments import upsert_instrument
from market_scanner.storage.reference import seed_reference_data


INSTRUMENTS_PATH = Path(__file__).resolve().parent.parent / "assets" / "instruments.json"


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


def load_master(market_key: str | None = None, database_url: str | None = None) -> int:
    from market_scanner.config.markets import clear_db_instrument_meta_cache

    payload = _load_master_payload()
    loaded = 0
    with connect(database_url) as conn:
        seed_reference_data(conn)
        for symbol, values in sorted(payload.items()):
            record_market_key = clean_text(values.get("market_key"))
            if not record_market_key:
                continue
            if market_key and record_market_key != market_key:
                continue
            if record_market_key not in MARKETS:
                continue
            source_provider = clean_text(values.get("source")) or "static"
            upsert_instrument(
                conn,
                MARKETS[record_market_key],
                _master_row(symbol, values),
                source_provider=source_provider,
                source_rank=source_rank(source_provider),
            )
            loaded += 1
    if loaded:
        clear_db_instrument_meta_cache()
    return loaded

