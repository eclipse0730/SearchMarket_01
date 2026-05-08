from __future__ import annotations

from market_scanner.storage.cli import main
from market_scanner.storage.common import (
    UNIVERSE_MARKET_ALIASES,
    clean_bool as _clean_bool,
    clean_int as _clean_int,
    clean_number as _clean_number,
    clean_text as _clean_text,
    clean_value as _clean_value,
    country_currency_for_market,
    default_asset_filter,
    home_market_key,
    price_source_for_market,
    row_payload as _row_payload,
)
from market_scanner.storage.connection import DEFAULT_DATABASE_URL, connect, database_url
from market_scanner.storage.diagnostics import print_counts
from market_scanner.storage.fundamentals import upsert_fundamentals
from market_scanner.storage.indicators import upsert_daily_indicator
from market_scanner.storage.instruments import (
    INSTRUMENTS_PATH,
    _load_master_payload,
    _master_row,
    _source_rank,
    classify_asset_type,
    display_symbol_for_row,
    load_master,
    run_fetch_name,
    upsert_instrument,
)
from market_scanner.storage.prices import upsert_daily_price
from market_scanner.storage.reference import (
    DEPRECATED_MARKET_KEYS,
    DEPRECATED_UNIVERSE_KEYS,
    cleanup_deprecated_reference_data,
    seed_reference_data,
)
from market_scanner.storage.runs import create_run, create_universe_run, finish_run
from market_scanner.storage.scan_loader import load_scan_frame
from market_scanner.storage.schema import SCHEMA_PATH, init_db
from market_scanner.storage.screener_results import (
    regime_for_score,
    risk_for_score,
    upsert_market_snapshot,
    upsert_scan_result,
    upsert_sector_snapshots,
)
from market_scanner.storage.universe import (
    REFRESH_LOG_SAMPLE_LIMIT,
    _MARKET_UNIVERSE_EXPANSION,
    _current_instrument_symbols,
    _current_universe_membership,
    _dedupe_symbols,
    _default_refresh_market_keys,
    _market_universe_keys,
    _membership_compare,
    _master_row_from_universe,
    _print_refresh_log,
    _refresh_log_params,
    _refresh_universe_membership,
    _sample_symbols,
    _universe_market_key,
    refresh_master,
    reset_loaded_data,
    scan_symbols_for_scope,
    upsert_universe_membership,
)


if __name__ == "__main__":
    main()
