"""v2 pipeline stage orchestrator.

This module owns only the order in which v2 stages run. Collection,
indicator calculation, scoring, storage, and report rendering live in their
own packages.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from market_scanner.analysis.indicators import run_compute as compute_indicators
from market_scanner.analysis.screener import run_screen
from market_scanner.collectors.fundamentals import run_fetch as fetch_fundamentals
from market_scanner.collectors.news import run_fetch as fetch_news
from market_scanner.collectors.prices import run_fetch as fetch_prices
from market_scanner.models import MarketDefinition, ScanSettings
from market_scanner.reports.render import report_output_paths
from market_scanner.reports.markdown_report import write_markdown
from market_scanner.storage.universe import scan_symbols_for_scope


def run_scan_stage_with_settings(
    market_key: str,
    date_str: str,
    settings: ScanSettings,
    *,
    symbols: list[str] | None = None,
    path_key: str | None = None,
) -> tuple[MarketDefinition, pd.DataFrame, dict[str, Path]]:
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
    paths = report_output_paths(path_key or market_key, date_str)
    return market, frame, paths


def run_fundamentals_stage(
    market_key: str,
    date_str: str,
    *,
    limit: int | None = None,
) -> None:
    fetch_fundamentals(market_key, date_str=date_str, limit=limit)


def run_analysis_stage(
    market_key: str,
    date_str: str,
    frame: pd.DataFrame | None = None,
    *,
    path_key: str | None = None,
) -> tuple[str, dict[str, Path]]:
    if frame is None:
        from market_scanner.config.markets import MARKETS

        universe_key = path_key if path_key and path_key != market_key else None
        frame = run_screen(market_key, date_str=date_str, universe_key=universe_key)
        market = MARKETS[market_key]
    else:
        from market_scanner.config.markets import MARKETS
        market = MARKETS[market_key]
    paths = report_output_paths(path_key or market_key, date_str)
    settings = ScanSettings(output_dir=Path("."))
    paths["md"].parent.mkdir(parents=True, exist_ok=True)
    markdown = write_markdown(frame, market, settings, date_str, paths["md"])
    return markdown, paths


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
