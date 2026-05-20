"""Pipeline stage orchestrator.

This module owns only the order in which stages run. Collection,
indicator calculation, scoring, storage, and report rendering live in their
own packages.
"""
from __future__ import annotations

import pandas as pd

from market_scanner.analysis.indicators import run_compute as compute_indicators
from market_scanner.analysis.screener import run_screen
from market_scanner.collectors.fundamentals import run_fetch as fetch_fundamentals
from market_scanner.collectors.news import run_fetch as fetch_news
from market_scanner.collectors.prices import run_fetch as fetch_prices
from market_scanner.models import MarketDefinition, ScanSettings
from market_scanner.storage.universe import scan_symbols_for_scope


def run_scan_stage_with_settings(
    market_key: str,
    date_str: str,
    settings: ScanSettings,
    *,
    symbols: list[str] | None = None,
    path_key: str | None = None,
) -> tuple[MarketDefinition, pd.DataFrame]:
    from market_scanner.config.markets import MARKETS

    universe_key = path_key if path_key and path_key != market_key else None
    if universe_key:
        scope_symbols, effective_universe = scan_symbols_for_scope(market_key, universe_key)
        print(f"  scan scope: {market_key}/{effective_universe} ({len(scope_symbols)} symbols from DB)")
    elif symbols is not None:
        print(f"  scan scope: {market_key}:all ({len(symbols)} symbols requested)")
    limit = settings.symbol_limit
    fetch_prices(market_key, date_str=date_str, limit=limit, workers=max(1, settings.max_workers))
    compute_indicators(market_key, date_str=date_str, limit=limit)
    frame = run_screen(market_key, date_str=date_str, universe_key=universe_key)
    market = MARKETS[market_key]
    return market, frame


def run_fundamentals_stage(
    market_key: str,
    date_str: str,
    *,
    limit: int | None = None,
) -> None:
    fetch_fundamentals(market_key, date_str=date_str, limit=limit)


def run_news_stage(
    market_key: str,
    date_str: str,
    *,
    path_key: str | None = None,
    max_symbols: int = 50,
    items_per_symbol: int = 3,
    max_workers: int = 4,
    provider: str = "all",
) -> int:
    universe_key = path_key if path_key and path_key != market_key else None
    return fetch_news(
        market_key,
        date_str,
        universe_key,
        max_symbols=max_symbols,
        items_per_symbol=items_per_symbol,
        workers=max_workers,
        provider=provider,
    )
