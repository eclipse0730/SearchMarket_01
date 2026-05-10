-- SearchMarket PostgreSQL schema draft v1
-- Target: PostgreSQL 16+
-- Purpose: make Postgres the canonical store while keeping CSV as an export/compatibility artifact.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS markets (
    market_key TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    country_code CHAR(2),
    currency_code CHAR(3),
    timezone TEXT NOT NULL DEFAULT 'Asia/Seoul',
    description TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS instruments (
    instrument_id BIGSERIAL PRIMARY KEY,
    market_key TEXT NOT NULL REFERENCES markets(market_key),
    symbol TEXT NOT NULL,
    display_symbol TEXT,
    exchange_code TEXT,
    country_code CHAR(2),
    currency_code CHAR(3),
    asset_type TEXT NOT NULL DEFAULT 'common_stock',
    listing_status TEXT NOT NULL DEFAULT 'active',
    name_en TEXT,
    name_local TEXT,
    sector TEXT,
    industry TEXT,
    description TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    source_provider TEXT NOT NULL,
    source_rank INTEGER NOT NULL DEFAULT 100,
    raw_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT instruments_asset_type_check CHECK (
        asset_type IN (
            'common_stock',
            'preferred_stock',
            'etf',
            'etn',
            'reit',
            'spac',
            'fund',
            'index',
            'commodity',
            'other'
        )
    ),
    CONSTRAINT instruments_listing_status_check CHECK (
        listing_status IN ('active', 'suspended', 'delisted', 'unknown')
    ),
    CONSTRAINT instruments_unique_symbol UNIQUE (market_key, symbol)
);

CREATE INDEX IF NOT EXISTS idx_instruments_market_asset
    ON instruments (market_key, asset_type, is_active);

CREATE INDEX IF NOT EXISTS idx_instruments_name_local
    ON instruments (name_local);

CREATE TABLE IF NOT EXISTS universe_definitions (
    universe_key TEXT PRIMARY KEY,
    market_key TEXT NOT NULL REFERENCES markets(market_key),
    label TEXT NOT NULL,
    description TEXT,
    source_policy TEXT,
    default_asset_type_filter TEXT[] NOT NULL DEFAULT ARRAY['common_stock'],
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS universe_memberships (
    universe_key TEXT NOT NULL REFERENCES universe_definitions(universe_key),
    instrument_id BIGINT NOT NULL REFERENCES instruments(instrument_id),
    effective_from DATE NOT NULL,
    effective_to DATE,
    rank_no INTEGER,
    weight NUMERIC(14, 8),
    source_provider TEXT NOT NULL,
    raw_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (universe_key, instrument_id, effective_from),
    CONSTRAINT universe_memberships_date_check CHECK (
        effective_to IS NULL OR effective_to >= effective_from
    )
);

CREATE INDEX IF NOT EXISTS idx_universe_memberships_current
    ON universe_memberships (universe_key, effective_to, rank_no);

CREATE TABLE IF NOT EXISTS collection_runs (
    run_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_type TEXT NOT NULL,
    market_key TEXT REFERENCES markets(market_key),
    universe_key TEXT REFERENCES universe_definitions(universe_key),
    trade_date DATE,
    source_provider TEXT,
    status TEXT NOT NULL DEFAULT 'running',
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ,
    requested_count INTEGER NOT NULL DEFAULT 0,
    success_count INTEGER NOT NULL DEFAULT 0,
    failed_count INTEGER NOT NULL DEFAULT 0,
    skipped_count INTEGER NOT NULL DEFAULT 0,
    params JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_samples JSONB NOT NULL DEFAULT '[]'::jsonb,
    notes TEXT,
    git_sha TEXT,
    CONSTRAINT collection_runs_type_check CHECK (
        run_type IN ('universe', 'prices', 'indicators', 'scan', 'news', 'render', 'backfill', 'fundamentals')
    ),
    CONSTRAINT collection_runs_status_check CHECK (
        status IN ('running', 'success', 'partial', 'failed', 'cancelled')
    )
);

CREATE INDEX IF NOT EXISTS idx_collection_runs_lookup
    ON collection_runs (market_key, universe_key, trade_date, run_type, started_at DESC);

-- migrate: add 'fundamentals' to run_type check (idempotent)
DO $$
BEGIN
    ALTER TABLE collection_runs DROP CONSTRAINT IF EXISTS collection_runs_type_check;
    ALTER TABLE collection_runs ADD CONSTRAINT collection_runs_type_check CHECK (
        run_type IN ('universe', 'prices', 'indicators', 'scan', 'news', 'render', 'backfill', 'fundamentals')
    );
END $$;

CREATE TABLE IF NOT EXISTS daily_prices (
    instrument_id BIGINT NOT NULL REFERENCES instruments(instrument_id),
    trade_date DATE NOT NULL,
    source_provider TEXT NOT NULL,
    open_price NUMERIC(20, 6),
    high_price NUMERIC(20, 6),
    low_price NUMERIC(20, 6),
    close_price NUMERIC(20, 6) NOT NULL,
    adj_close_price NUMERIC(20, 6),
    volume BIGINT,
    currency_code CHAR(3),
    is_adjusted BOOLEAN NOT NULL DEFAULT FALSE,
    run_id UUID REFERENCES collection_runs(run_id),
    raw_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    collected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (instrument_id, trade_date, source_provider),
    CONSTRAINT daily_prices_ohlc_check CHECK (
        high_price IS NULL
        OR low_price IS NULL
        OR high_price >= low_price
    )
);

CREATE INDEX IF NOT EXISTS idx_daily_prices_date
    ON daily_prices (trade_date DESC);

CREATE INDEX IF NOT EXISTS idx_daily_prices_instrument_date
    ON daily_prices (instrument_id, trade_date DESC);

CREATE INDEX IF NOT EXISTS idx_daily_prices_source_date
    ON daily_prices (source_provider, trade_date DESC);

CREATE TABLE IF NOT EXISTS daily_indicators (
    instrument_id BIGINT NOT NULL REFERENCES instruments(instrument_id),
    trade_date DATE NOT NULL,
    price_source_provider TEXT NOT NULL,
    rsi14 NUMERIC(8, 4),
    rsi14_prev NUMERIC(8, 4),
    rsi14_change NUMERIC(10, 4),
    rsi14_ma5 NUMERIC(8, 4),
    rsi2 NUMERIC(8, 4),
    rsi5 NUMERIC(8, 4),
    rsi30 NUMERIC(8, 4),
    ma5 NUMERIC(20, 6),
    ma20 NUMERIC(20, 6),
    ma60 NUMERIC(20, 6),
    ma120 NUMERIC(20, 6),
    ma240 NUMERIC(20, 6),
    diff_5_pct NUMERIC(10, 4),
    diff_20_pct NUMERIC(10, 4),
    diff_60_pct NUMERIC(10, 4),
    diff_120_pct NUMERIC(10, 4),
    diff_240_pct NUMERIC(10, 4),
    near_5 BOOLEAN NOT NULL DEFAULT FALSE,
    near_20 BOOLEAN NOT NULL DEFAULT FALSE,
    near_60 BOOLEAN NOT NULL DEFAULT FALSE,
    near_120 BOOLEAN NOT NULL DEFAULT FALSE,
    near_240 BOOLEAN NOT NULL DEFAULT FALSE,
    macd NUMERIC(20, 6),
    macd_signal NUMERIC(20, 6),
    macd_hist NUMERIC(20, 6),
    macd_state TEXT,
    bollinger_width_pct NUMERIC(10, 4),
    bollinger_percent_b NUMERIC(10, 4),
    high_52w NUMERIC(20, 6),
    low_52w NUMERIC(20, 6),
    from_high_pct NUMERIC(10, 4),
    from_low_pct NUMERIC(10, 4),
    high_20d NUMERIC(20, 6),
    low_20d NUMERIC(20, 6),
    high_60d NUMERIC(20, 6),
    low_60d NUMERIC(20, 6),
    breakout_20d BOOLEAN NOT NULL DEFAULT FALSE,
    breakout_60d BOOLEAN NOT NULL DEFAULT FALSE,
    breakout_high_20d BOOLEAN NOT NULL DEFAULT FALSE,
    breakout_high_60d BOOLEAN NOT NULL DEFAULT FALSE,
    volume_ratio NUMERIC(12, 4),
    value_traded NUMERIC(28, 6),
    value_ratio_20d NUMERIC(12, 4),
    volume_avg20 NUMERIC(20, 4),
    volume_avg60 NUMERIC(20, 4),
    ma_alignment_score INTEGER,
    is_ma_bullish_alignment BOOLEAN NOT NULL DEFAULT FALSE,
    ma20_slope_pct NUMERIC(10, 4),
    ma60_slope_pct NUMERIC(10, 4),
    rsi_prev NUMERIC(8, 4),
    rsi_change NUMERIC(10, 4),
    macd_cross TEXT,
    macd_hist_change NUMERIC(20, 6),
    new_high_20d_close BOOLEAN NOT NULL DEFAULT FALSE,
    new_high_20d_high BOOLEAN NOT NULL DEFAULT FALSE,
    new_high_60d_close BOOLEAN NOT NULL DEFAULT FALSE,
    new_high_60d_high BOOLEAN NOT NULL DEFAULT FALSE,
    close_position_in_range_20d NUMERIC(10, 4),
    close_position_in_range_60d NUMERIC(10, 4),
    return_5d NUMERIC(10, 4),
    return_20d NUMERIC(10, 4),
    return_60d NUMERIC(10, 4),
    return_120d NUMERIC(10, 4),
    return_240d NUMERIC(10, 4),
    atr14 NUMERIC(20, 6),
    atr14_pct NUMERIC(10, 4),
    volatility_20d NUMERIC(10, 4),
    volatility_60d NUMERIC(10, 4),
    change_pct NUMERIC(10, 4),
    gap_pct NUMERIC(10, 4),
    candle_body_pct NUMERIC(10, 4),
    candle_range_pct NUMERIC(10, 4),
    upper_shadow_pct NUMERIC(10, 4),
    lower_shadow_pct NUMERIC(10, 4),
    candle_type TEXT,
    trend TEXT,
    trend_score INTEGER,
    calculated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    run_id UUID REFERENCES collection_runs(run_id),
    PRIMARY KEY (instrument_id, trade_date),
    CONSTRAINT daily_indicators_macd_state_check CHECK (
        macd_state IS NULL OR macd_state IN ('Bullish', 'Positive', 'Improving', 'Bearish', 'Unknown')
    ),
    CONSTRAINT daily_indicators_candle_type_check CHECK (
        candle_type IS NULL OR candle_type IN (
            'Unknown',
            'Flat',
            'Long Lower Doji',
            'Long Upper Doji',
            'Doji',
            'Bullish Reversal',
            'Bearish Rejection',
            'Strong Bullish',
            'Strong Bearish',
            'Bullish',
            'Bearish'
        )
    )
);

CREATE INDEX IF NOT EXISTS idx_daily_indicators_date
    ON daily_indicators (trade_date DESC);

CREATE INDEX IF NOT EXISTS idx_daily_indicators_rsi_date
    ON daily_indicators (trade_date DESC, rsi14);

ALTER TABLE IF EXISTS daily_indicators
    ADD COLUMN IF NOT EXISTS ma5 NUMERIC(20, 6),
    ADD COLUMN IF NOT EXISTS rsi14_prev NUMERIC(8, 4),
    ADD COLUMN IF NOT EXISTS rsi14_change NUMERIC(10, 4),
    ADD COLUMN IF NOT EXISTS rsi14_ma5 NUMERIC(8, 4),
    ADD COLUMN IF NOT EXISTS rsi2 NUMERIC(8, 4),
    ADD COLUMN IF NOT EXISTS rsi5 NUMERIC(8, 4),
    ADD COLUMN IF NOT EXISTS rsi30 NUMERIC(8, 4),
    ADD COLUMN IF NOT EXISTS ma20 NUMERIC(20, 6),
    ADD COLUMN IF NOT EXISTS diff_5_pct NUMERIC(10, 4),
    ADD COLUMN IF NOT EXISTS diff_20_pct NUMERIC(10, 4),
    ADD COLUMN IF NOT EXISTS near_5 BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS near_20 BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS from_low_pct NUMERIC(10, 4),
    ADD COLUMN IF NOT EXISTS high_20d NUMERIC(20, 6),
    ADD COLUMN IF NOT EXISTS low_20d NUMERIC(20, 6),
    ADD COLUMN IF NOT EXISTS high_60d NUMERIC(20, 6),
    ADD COLUMN IF NOT EXISTS low_60d NUMERIC(20, 6),
    ADD COLUMN IF NOT EXISTS breakout_20d BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS breakout_60d BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS breakout_high_20d BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS breakout_high_60d BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS value_traded NUMERIC(28, 6),
    ADD COLUMN IF NOT EXISTS value_ratio_20d NUMERIC(12, 4),
    ADD COLUMN IF NOT EXISTS volume_avg20 NUMERIC(20, 4),
    ADD COLUMN IF NOT EXISTS volume_avg60 NUMERIC(20, 4),
    ADD COLUMN IF NOT EXISTS ma_alignment_score INTEGER,
    ADD COLUMN IF NOT EXISTS is_ma_bullish_alignment BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS ma20_slope_pct NUMERIC(10, 4),
    ADD COLUMN IF NOT EXISTS ma60_slope_pct NUMERIC(10, 4),
    ADD COLUMN IF NOT EXISTS rsi_prev NUMERIC(8, 4),
    ADD COLUMN IF NOT EXISTS rsi_change NUMERIC(10, 4),
    ADD COLUMN IF NOT EXISTS macd_cross TEXT,
    ADD COLUMN IF NOT EXISTS macd_hist_change NUMERIC(20, 6),
    ADD COLUMN IF NOT EXISTS new_high_20d_close BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS new_high_20d_high BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS new_high_60d_close BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS new_high_60d_high BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS close_position_in_range_20d NUMERIC(10, 4),
    ADD COLUMN IF NOT EXISTS close_position_in_range_60d NUMERIC(10, 4),
    ADD COLUMN IF NOT EXISTS return_5d NUMERIC(10, 4),
    ADD COLUMN IF NOT EXISTS return_20d NUMERIC(10, 4),
    ADD COLUMN IF NOT EXISTS return_60d NUMERIC(10, 4),
    ADD COLUMN IF NOT EXISTS return_120d NUMERIC(10, 4),
    ADD COLUMN IF NOT EXISTS return_240d NUMERIC(10, 4),
    ADD COLUMN IF NOT EXISTS atr14 NUMERIC(20, 6),
    ADD COLUMN IF NOT EXISTS atr14_pct NUMERIC(10, 4),
    ADD COLUMN IF NOT EXISTS volatility_20d NUMERIC(10, 4),
    ADD COLUMN IF NOT EXISTS volatility_60d NUMERIC(10, 4);

CREATE TABLE IF NOT EXISTS instrument_fundamentals (
    instrument_id BIGINT NOT NULL REFERENCES instruments(instrument_id),
    as_of_date DATE NOT NULL,
    source_provider TEXT NOT NULL,
    trailing_pe NUMERIC(16, 6),
    price_to_book NUMERIC(16, 6),
    return_on_equity_pct NUMERIC(10, 4),
    revenue_growth_pct NUMERIC(10, 4),
    market_cap NUMERIC(24, 2),
    target_price NUMERIC(20, 6),
    shares_outstanding NUMERIC(24, 2),
    raw_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    collected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    run_id UUID REFERENCES collection_runs(run_id),
    PRIMARY KEY (instrument_id, as_of_date, source_provider)
);

CREATE INDEX IF NOT EXISTS idx_instrument_fundamentals_date
    ON instrument_fundamentals (as_of_date DESC);

CREATE INDEX IF NOT EXISTS idx_instrument_fundamentals_instrument_date
    ON instrument_fundamentals (instrument_id, as_of_date DESC);

CREATE TABLE IF NOT EXISTS scan_results (
    run_id UUID NOT NULL REFERENCES collection_runs(run_id),
    instrument_id BIGINT NOT NULL REFERENCES instruments(instrument_id),
    market_key TEXT NOT NULL REFERENCES markets(market_key),
    universe_key TEXT REFERENCES universe_definitions(universe_key),
    trade_date DATE NOT NULL,
    chart_score NUMERIC(8, 4),
    technical_score NUMERIC(8, 4),
    fundamental_score NUMERIC(8, 4),
    theme_score NUMERIC(8, 4),
    flow_score NUMERIC(8, 4),
    composite_score NUMERIC(8, 4),
    rank_no INTEGER,
    setup_tags TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    risk_flags TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    summary_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, instrument_id)
);

CREATE INDEX IF NOT EXISTS idx_scan_results_market_date_score
    ON scan_results (market_key, trade_date DESC, composite_score DESC);

CREATE INDEX IF NOT EXISTS idx_scan_results_universe_rank
    ON scan_results (universe_key, trade_date DESC, rank_no);

CREATE INDEX IF NOT EXISTS idx_scan_results_instrument_date
    ON scan_results (instrument_id, trade_date DESC);

CREATE TABLE IF NOT EXISTS market_snapshots (
    market_key TEXT NOT NULL REFERENCES markets(market_key),
    universe_key TEXT NOT NULL REFERENCES universe_definitions(universe_key),
    trade_date DATE NOT NULL,
    run_id UUID REFERENCES collection_runs(run_id),
    total_count INTEGER NOT NULL DEFAULT 0,
    scanned_count INTEGER NOT NULL DEFAULT 0,
    success_count INTEGER NOT NULL DEFAULT 0,
    failed_count INTEGER NOT NULL DEFAULT 0,
    advance_count INTEGER NOT NULL DEFAULT 0,
    decline_count INTEGER NOT NULL DEFAULT 0,
    unchanged_count INTEGER NOT NULL DEFAULT 0,
    avg_change_pct NUMERIC(10, 4),
    median_change_pct NUMERIC(10, 4),
    avg_rsi14 NUMERIC(10, 4),
    bullish_breadth_pct NUMERIC(10, 4),
    avg_composite_score NUMERIC(10, 4),
    market_score NUMERIC(10, 4),
    regime TEXT,
    risk_level TEXT,
    macro_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    ai_summary TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (market_key, trade_date, universe_key)
);

CREATE TABLE IF NOT EXISTS sector_snapshots (
    market_key TEXT NOT NULL REFERENCES markets(market_key),
    universe_key TEXT NOT NULL REFERENCES universe_definitions(universe_key),
    trade_date DATE NOT NULL,
    sector TEXT NOT NULL,
    run_id UUID REFERENCES collection_runs(run_id),
    instrument_count INTEGER NOT NULL DEFAULT 0,
    advance_count INTEGER NOT NULL DEFAULT 0,
    decline_count INTEGER NOT NULL DEFAULT 0,
    avg_change_pct NUMERIC(10, 4),
    median_change_pct NUMERIC(10, 4),
    avg_rsi14 NUMERIC(10, 4),
    avg_composite_score NUMERIC(10, 4),
    top_instruments JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (market_key, trade_date, universe_key, sector)
);

CREATE INDEX IF NOT EXISTS idx_market_snapshots_date
    ON market_snapshots (trade_date DESC, market_key, universe_key);

CREATE INDEX IF NOT EXISTS idx_sector_snapshots_date_sector
    ON sector_snapshots (trade_date DESC, market_key, universe_key, sector);

CREATE TABLE IF NOT EXISTS news_items (
    news_id BIGSERIAL PRIMARY KEY,
    source_provider TEXT NOT NULL,
    external_id TEXT,
    url TEXT NOT NULL,
    title TEXT NOT NULL,
    publisher TEXT,
    published_at TIMESTAMPTZ,
    summary TEXT,
    language_code TEXT,
    raw_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    collected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT news_items_unique_url UNIQUE (url)
);

CREATE TABLE IF NOT EXISTS instrument_news (
    instrument_id BIGINT NOT NULL REFERENCES instruments(instrument_id),
    news_id BIGINT NOT NULL REFERENCES news_items(news_id),
    relevance_score NUMERIC(8, 4),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (instrument_id, news_id)
);

CREATE INDEX IF NOT EXISTS idx_news_items_published
    ON news_items (published_at DESC);

CREATE TABLE IF NOT EXISTS generated_reports (
    report_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    market_key TEXT REFERENCES markets(market_key),
    universe_key TEXT REFERENCES universe_definitions(universe_key),
    trade_date DATE NOT NULL,
    run_id UUID REFERENCES collection_runs(run_id),
    report_type TEXT NOT NULL,
    format TEXT NOT NULL,
    file_path TEXT,
    content_hash TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    generated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT generated_reports_type_check CHECK (
        report_type IN ('analysis', 'detail_page', 'site_page', 'export')
    ),
    CONSTRAINT generated_reports_format_check CHECK (
        format IN ('markdown', 'html', 'csv', 'json')
    )
);

CREATE INDEX IF NOT EXISTS idx_generated_reports_lookup
    ON generated_reports (market_key, universe_key, trade_date DESC, report_type);

CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_markets_updated_at ON markets;
CREATE TRIGGER trg_markets_updated_at
BEFORE UPDATE ON markets
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_instruments_updated_at ON instruments;
CREATE TRIGGER trg_instruments_updated_at
BEFORE UPDATE ON instruments
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_universe_definitions_updated_at ON universe_definitions;
CREATE TRIGGER trg_universe_definitions_updated_at
BEFORE UPDATE ON universe_definitions
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
