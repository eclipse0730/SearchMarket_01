from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd
import psycopg

from market_scanner.config.markets import MARKETS, REPRESENTATIVE_UNIVERSE_LOADERS
from market_scanner.domain.market_policy import UNIVERSE_MARKET_ALIASES, home_market_key
from market_scanner.models import MarketDefinition
from market_scanner.progress import progress_line
from market_scanner.storage.common import clean_text
from market_scanner.storage.connection import connect
from market_scanner.storage.instruments import upsert_instrument
from market_scanner.storage.reference import seed_reference_data
from market_scanner.storage.runs import create_universe_run, finish_run
from market_scanner.storage.universe import (
    _current_instrument_symbols,
    _current_universe_membership,
    reset_loaded_data,
    upsert_universe_membership,
)


REFRESH_LOG_SAMPLE_LIMIT = 30

_MARKET_UNIVERSE_EXPANSION: dict[str, list[str]] = {
    "us": ["nasdaq", "nyse", "amex", "nasdaq100", "sp500"],
    "kospi": ["kospi", "kospi100", "kospi200"],
    "kosdaq": ["kosdaq", "kosdaq150"],
}


def _dedupe_symbols(symbols: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for symbol in symbols:
        text = clean_text(symbol)
        if not text or text in seen:
            continue
        deduped.append(text)
        seen.add(text)
    return deduped


def _master_row_from_universe(
    market: MarketDefinition,
    symbol: str,
    metadata: dict[str, Any],
) -> pd.Series:
    meta = metadata.get(symbol)
    return pd.Series(
        {
            "symbol": symbol,
            "display_symbol": market.display_symbol_builder(symbol),
            "name_en": getattr(meta, "name_en", None) or symbol,
            "name_local": getattr(meta, "name_local", None) or getattr(meta, "name_en", None) or symbol,
            "sector": getattr(meta, "sector", None) or "Unknown",
            "description": getattr(meta, "description", None) or "No description",
        }
    )


def _default_refresh_market_keys() -> list[str]:
    return sorted(key for key in MARKETS if key not in UNIVERSE_MARKET_ALIASES)


def _universe_market_key(universe_key: str) -> str:
    return UNIVERSE_MARKET_ALIASES.get(universe_key, home_market_key(universe_key))


def _sample_symbols(symbols: list[str], limit: int = REFRESH_LOG_SAMPLE_LIMIT) -> list[str]:
    return symbols[:limit]


def _membership_compare(current: list[dict[str, Any]], symbols: list[str]) -> dict[str, Any]:
    current_symbols = [str(row["symbol"]) for row in current]
    current_set = set(current_symbols)
    new_set = set(symbols)
    matched = sorted(current_set & new_set)
    added = [symbol for symbol in symbols if symbol not in current_set]
    removed = [symbol for symbol in current_symbols if symbol not in new_set]

    current_rank = {str(row["symbol"]): row.get("rank_no") for row in current}
    new_rank = {symbol: index for index, symbol in enumerate(symbols, start=1)}
    rank_changed = [
        {
            "symbol": symbol,
            "old_rank": current_rank.get(symbol),
            "new_rank": new_rank[symbol],
        }
        for symbol in symbols
        if symbol in current_rank and current_rank.get(symbol) != new_rank[symbol]
    ]

    return {
        "previous_count": len(current_symbols),
        "fetched_count": len(symbols),
        "matched_count": len(matched),
        "mismatch_count": len(added) + len(removed),
        "added_count": len(added),
        "removed_count": len(removed),
        "rank_changed_count": len(rank_changed),
        "membership_unchanged": current_symbols == symbols,
        "added_symbols": added,
        "removed_symbols": removed,
        "rank_changed": rank_changed,
    }


def _refresh_log_params(
    compare: dict[str, Any],
    instrument_added: list[str],
    membership_rewritten: bool,
    instrument_upserted: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "comparison": {
            "previous_count": compare["previous_count"],
            "fetched_count": compare["fetched_count"],
            "matched_count": compare["matched_count"],
            "mismatch_count": compare["mismatch_count"],
            "added_count": compare["added_count"],
            "removed_count": compare["removed_count"],
            "rank_changed_count": compare["rank_changed_count"],
            "membership_unchanged": compare["membership_unchanged"],
            "membership_rewritten": membership_rewritten,
        },
        "samples": {
            "added_symbols": _sample_symbols(compare["added_symbols"]),
            "removed_symbols": _sample_symbols(compare["removed_symbols"]),
            "rank_changed": compare["rank_changed"][:REFRESH_LOG_SAMPLE_LIMIT],
            "instrument_added": _sample_symbols(instrument_added),
            "instrument_upserted": _sample_symbols(instrument_upserted or []),
        },
    }


def _print_refresh_log(universe_key: str, summary: dict[str, Any]) -> None:
    comparison = summary["comparison"]
    print(
        "  refresh-master "
        f"[{universe_key}] previous={comparison['previous_count']} "
        f"fetched={comparison['fetched_count']} "
        f"matched={comparison['matched_count']} "
        f"mismatch={comparison['mismatch_count']} "
        f"added={comparison['added_count']} "
        f"removed={comparison['removed_count']} "
        f"rank_changed={comparison['rank_changed_count']}"
    )
    if comparison["membership_rewritten"]:
        print(f"    membership: rewritten ({summary['membership_upserted_count']} rows)")
    else:
        print("    membership: unchanged, rewrite skipped")
    print(
        f"    instruments: upserted={summary['instrument_upserted_count']} "
        f"new={summary['instrument_added_count']} "
        f"existing={summary['instrument_existing_count']}"
    )

    samples = summary["samples"]
    if samples["added_symbols"]:
        print(f"    added sample: {', '.join(samples['added_symbols'])}")
    if samples["removed_symbols"]:
        print(f"    removed sample: {', '.join(samples['removed_symbols'])}")
    if samples["rank_changed"]:
        rank_sample = ", ".join(
            f"{item['symbol']}:{item['old_rank']}->{item['new_rank']}"
            for item in samples["rank_changed"]
        )
        print(f"    rank changed sample: {rank_sample}")
    if samples["instrument_added"]:
        print(f"    new instrument sample: {', '.join(samples['instrument_added'])}")
    if samples["instrument_upserted"]:
        print(f"    upserted instrument sample: {', '.join(samples['instrument_upserted'])}")


def _refresh_universe_membership(
    conn: psycopg.Connection,
    market_key: str,
    universe_key: str,
    symbols: list[str],
    metadata: dict[str, Any],
    trade_date,
    *,
    current_membership: list[dict[str, Any]] | None = None,
    existing_instruments: set[str] | None = None,
    force_rewrite: bool = False,
) -> dict[str, Any]:
    if not symbols:
        run_id = create_universe_run(conn, market_key, universe_key, trade_date, 0)
        finish_run(conn, run_id, status="failed", success_count=0, notes="universe loader returned 0 symbols")
        print(f"  refresh-master [{universe_key}] FAILED: universe loader returned 0 symbols")
        return {
            "run_id": run_id,
            "comparison": {"fetched_count": 0, "mismatch_count": 0},
            "instrument_added_count": 0,
            "instrument_upserted_count": 0,
            "membership_upserted_count": 0,
            "samples": {},
        }
    market = MARKETS[market_key]
    if current_membership is None:
        current_membership = _current_universe_membership(conn, universe_key)
    comparison = _membership_compare(current_membership, symbols)
    membership_rewritten = force_rewrite or not comparison["membership_unchanged"]
    if existing_instruments is None:
        existing_instruments = _current_instrument_symbols(conn, market_key)
    instrument_added = [symbol for symbol in symbols if symbol not in existing_instruments]
    instrument_upserted_symbols: list[str] = []

    run_id = create_universe_run(
        conn,
        market_key,
        universe_key,
        trade_date,
        len(symbols),
        params=_refresh_log_params(comparison, instrument_added, membership_rewritten),
    )
    if membership_rewritten:
        conn.execute("DELETE FROM universe_memberships WHERE universe_key = %s", (universe_key,))

    instrument_upserted = 0
    membership_upserted = 0
    progress_interval = max(1, len(symbols) // 100)

    def print_progress(force: bool = False) -> None:
        if not force and instrument_upserted % progress_interval != 0:
            return
        print(
            progress_line(
                instrument_upserted,
                len(symbols),
                instruments=instrument_upserted,
                memberships=membership_upserted,
            ),
            end="",
            flush=True,
        )

    print_progress(force=True)
    for rank_no, symbol in enumerate(symbols, start=1):
        instrument_id = upsert_instrument(
            conn,
            market,
            _master_row_from_universe(market, symbol, metadata),
            source_provider="market_scanner",
            source_rank=50,
        )
        instrument_upserted += 1
        instrument_upserted_symbols.append(symbol)
        if membership_rewritten:
            upsert_universe_membership(
                conn,
                universe_key,
                instrument_id,
                trade_date,
                rank_no,
                source_provider="market_scanner",
            )
            membership_upserted += 1
        print_progress()

    print_progress(force=True)
    print()

    summary = {
        **_refresh_log_params(
            comparison,
            instrument_added,
            membership_rewritten,
            instrument_upserted_symbols,
        ),
        "run_id": run_id,
        "instrument_upserted_count": instrument_upserted,
        "instrument_added_count": len(instrument_added),
        "instrument_existing_count": instrument_upserted - len(instrument_added),
        "membership_upserted_count": membership_upserted,
    }
    finish_run(
        conn,
        run_id,
        status="success",
        success_count=membership_upserted,
        skipped_count=len(symbols) - membership_upserted,
        params={
            "samples": summary["samples"],
            "instrument_upserted_count": instrument_upserted,
            "instrument_added_count": len(instrument_added),
            "instrument_existing_count": instrument_upserted - len(instrument_added),
            "membership_upserted_count": membership_upserted,
        },
        notes="membership rewritten" if membership_rewritten else "membership unchanged; rewrite skipped",
    )
    _print_refresh_log(universe_key, summary)
    return summary


def refresh_master(
    market_key: str | None = None,
    universe_key: str | None = None,
    date_str: str | None = None,
    explicit_url: str | None = None,
    *,
    reset: bool = False,
) -> dict[str, dict[str, Any]]:
    from market_scanner.config.markets import clear_db_instrument_meta_cache

    trade_date = datetime.strptime(date_str, "%Y%m%d").date() if date_str else datetime.today().date()
    if universe_key:
        universe_market_key = _universe_market_key(universe_key)
        if market_key and market_key != universe_market_key:
            raise ValueError(f"Universe '{universe_key}' belongs to market '{universe_market_key}', not '{market_key}'")
        if universe_key in REPRESENTATIVE_UNIVERSE_LOADERS:
            refresh_targets = [(universe_market_key, universe_key)]
        elif universe_key in MARKETS and universe_key == universe_market_key:
            refresh_targets = [(universe_market_key, universe_key)]
        else:
            raise ValueError(f"Unsupported refresh universe: {universe_key}")
    else:
        market_keys = [market_key] if market_key else _default_refresh_market_keys()
        refresh_targets = []
        for key in market_keys:
            if key in _MARKET_UNIVERSE_EXPANSION:
                refresh_targets.extend((key, u) for u in _MARKET_UNIVERSE_EXPANSION[key])
            else:
                refresh_targets.append((key, key))
    summaries: dict[str, dict[str, Any]] = {}

    with connect(explicit_url) as conn:
        seed_reference_data(conn)
        universe_keys_by_market: dict[str, list[str]] = {}
        for key, target_universe in refresh_targets:
            universe_keys_by_market.setdefault(key, []).append(target_universe)
        current_memberships: dict[str, list[dict[str, Any]]] = {}
        existing_instruments: dict[str, set[str]] = {}
        if reset:
            for key, universe_keys in universe_keys_by_market.items():
                existing_instruments[key] = _current_instrument_symbols(conn, key)
                for universe_key in universe_keys:
                    current_memberships[universe_key] = _current_universe_membership(conn, universe_key)
            if universe_key:
                for key, target_universes in universe_keys_by_market.items():
                    print(
                        "  reset scope: membership only, "
                        f"market={home_market_key(key)}, universes={', '.join(target_universes)}"
                    )
                    reset_loaded_data(conn, key, target_universes)
            else:
                if market_key:
                    print(f"  reset scope: membership only, market={home_market_key(market_key)}")
                else:
                    print("  reset scope: membership only, all universes; collection_runs retained")
                reset_loaded_data(conn, market_key if market_key else None)
        for key, target_universe in refresh_targets:
            market = MARKETS[key]
            if target_universe in REPRESENTATIVE_UNIVERSE_LOADERS:
                symbols = _dedupe_symbols(REPRESENTATIVE_UNIVERSE_LOADERS[target_universe]())
            else:
                symbols = _dedupe_symbols(market.universe_loader())
            metadata = market.metadata_loader()
            summaries[target_universe] = _refresh_universe_membership(
                conn,
                key,
                target_universe,
                symbols,
                metadata,
                trade_date,
                current_membership=current_memberships.get(target_universe),
                existing_instruments=existing_instruments.get(key),
                force_rewrite=reset,
            )
    if summaries:
        clear_db_instrument_meta_cache()
    return summaries
