from __future__ import annotations

from datetime import datetime

import pandas as pd

from market_scanner.config.markets import MARKETS
from market_scanner.storage.common import clean_text, country_currency_for_market, price_source_for_market
from market_scanner.storage.connection import connect
from market_scanner.storage.fundamentals import upsert_fundamentals
from market_scanner.storage.indicators import upsert_daily_indicator
from market_scanner.storage.instruments import upsert_instrument
from market_scanner.storage.prices import upsert_daily_price
from market_scanner.storage.reference import seed_reference_data
from market_scanner.storage.runs import create_run, finish_run
from market_scanner.storage.screener_results import (
    upsert_market_snapshot,
    upsert_scan_result,
    upsert_sector_snapshots,
)
from market_scanner.storage.universe import upsert_universe_membership


def load_scan_frame(
    market_key: str,
    date_str: str,
    frame: pd.DataFrame,
    explicit_url: str | None = None,
    universe_key: str | None = None,
) -> str:
    if frame.empty:
        raise ValueError("Cannot load an empty scan frame")
    market = MARKETS[market_key]
    trade_date = datetime.strptime(date_str, "%Y%m%d").date()
    universe_key = universe_key or market_key
    source_provider = price_source_for_market(market_key)
    _, currency_code, _ = country_currency_for_market(market_key)

    with connect(explicit_url) as conn:
        seed_reference_data(conn)
        run_id = create_run(conn, market_key, universe_key, trade_date, len(frame))
        ranked = frame.copy()
        if "composite_score" in ranked.columns:
            ranked = ranked.sort_values("composite_score", ascending=False, na_position="last")
        instrument_ids: dict[str, int] = {}
        for rank_no, (_, row) in enumerate(ranked.iterrows(), start=1):
            instrument_id = upsert_instrument(conn, market, row)
            symbol = clean_text(row.get("symbol")) or str(instrument_id)
            instrument_ids[symbol] = instrument_id
            upsert_universe_membership(conn, universe_key, instrument_id, trade_date, rank_no)
            upsert_daily_price(conn, instrument_id, trade_date, source_provider, row, run_id, currency_code)
            upsert_daily_indicator(conn, instrument_id, trade_date, source_provider, row, run_id)
            upsert_fundamentals(conn, instrument_id, trade_date, source_provider, row, run_id)
            upsert_scan_result(conn, run_id, instrument_id, market_key, universe_key, trade_date, row, rank_no)
        upsert_market_snapshot(conn, market_key, universe_key, trade_date, ranked, run_id)
        upsert_sector_snapshots(conn, market_key, universe_key, trade_date, ranked, run_id)
        finish_run(conn, run_id, status="success", success_count=len(instrument_ids))
        return run_id
