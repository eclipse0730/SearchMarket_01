from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pandas as pd
import psycopg
from psycopg.types.json import Jsonb

from market_scanner.config.markets import MARKETS
from market_scanner.models import MarketDefinition
from market_scanner.storage.common import (
    clean_text,
    country_currency_for_market,
    home_market_key,
    row_payload,
)
from market_scanner.storage.connection import connect
from market_scanner.storage.reference import seed_reference_data


INSTRUMENTS_PATH = Path(__file__).resolve().parent.parent / "assets" / "instruments.json"


def classify_asset_type(row: pd.Series, market_key: str) -> str:
    home_key = home_market_key(market_key)
    if home_key in {"global-indices"}:
        return "index"
    if home_key in {"commodities"}:
        return "commodity"

    name = (clean_text(row.get("name_local")) or clean_text(row.get("name_en")) or "").upper()
    symbol = (clean_text(row.get("symbol")) or "").upper()
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
    display_symbol = clean_text(row.get("display_symbol"))
    symbol = clean_text(row.get("symbol"))
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
    symbol = clean_text(row.get("symbol"))
    if not symbol:
        raise ValueError("Missing symbol")
    home_key = home_market_key(market.key)
    country_code, currency_code, _ = country_currency_for_market(market.key)
    asset_type = classify_asset_type(row, market.key)
    raw_metadata = row_payload(
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
            clean_text(row.get("name_en")),
            clean_text(row.get("name_local")),
            clean_text(row.get("sector")),
            clean_text(row.get("description")),
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
                source_rank=_source_rank(source_provider),
            )
            loaded += 1
    if loaded:
        clear_db_instrument_meta_cache()
    return loaded


def run_fetch_name(
    market_key: str,
    stale_only: bool = True,
    limit: int | None = None,
    explicit_url: str | None = None,
    delay: float = 0.3,
) -> None:
    """Naver Finance 개별 종목 페이지에서 name_local, sector를 가져와 instruments 업데이트."""
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

            new_name_local = name or curr_name
            new_name_en = curr_name_en
            if name and (not curr_name_en or curr_name_en == symbol or curr_name_en == code):
                new_name_en = name
            new_sector = sector or curr_sector
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
