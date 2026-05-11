-- 2026-05-11: Expand scan_results with strategy scores, setup label, pullback MA period,
-- and price/indicator snapshot columns. Adds three supporting indexes.

ALTER TABLE scan_results
    ADD COLUMN IF NOT EXISTS pullback_score NUMERIC(8, 4),
    ADD COLUMN IF NOT EXISTS breakout_score NUMERIC(8, 4),
    ADD COLUMN IF NOT EXISTS box_breakout_score NUMERIC(8, 4),
    ADD COLUMN IF NOT EXISTS trend_quality_score NUMERIC(8, 4),
    ADD COLUMN IF NOT EXISTS reversal_score NUMERIC(8, 4),
    ADD COLUMN IF NOT EXISTS overbought_score NUMERIC(8, 4),
    ADD COLUMN IF NOT EXISTS risk_score NUMERIC(8, 4),
    ADD COLUMN IF NOT EXISTS raw_composite_score NUMERIC(8, 4),
    ADD COLUMN IF NOT EXISTS action_score NUMERIC(8, 4),
    ADD COLUMN IF NOT EXISTS quality_score NUMERIC(8, 4),
    ADD COLUMN IF NOT EXISTS setup_label TEXT,
    ADD COLUMN IF NOT EXISTS pullback_ma_period SMALLINT,
    ADD COLUMN IF NOT EXISTS close_price NUMERIC(18, 6),
    ADD COLUMN IF NOT EXISTS change_pct NUMERIC(10, 4),
    ADD COLUMN IF NOT EXISTS value_traded NUMERIC(20, 4),
    ADD COLUMN IF NOT EXISTS rsi14 NUMERIC(8, 4);

-- Backfill from summary_payload for historical rows so legacy data remains usable.
UPDATE scan_results
SET
    pullback_score      = COALESCE(pullback_score,      (summary_payload->>'pullback_score')::NUMERIC),
    breakout_score      = COALESCE(breakout_score,      (summary_payload->>'breakout_score')::NUMERIC),
    box_breakout_score  = COALESCE(box_breakout_score,  (summary_payload->>'box_breakout_score')::NUMERIC),
    trend_quality_score = COALESCE(trend_quality_score, (summary_payload->>'trend_quality_score')::NUMERIC),
    reversal_score      = COALESCE(reversal_score,      (summary_payload->>'reversal_score')::NUMERIC),
    overbought_score    = COALESCE(overbought_score,    (summary_payload->>'overbought_score')::NUMERIC),
    risk_score          = COALESCE(risk_score,          (summary_payload->>'risk_score')::NUMERIC),
    raw_composite_score = COALESCE(raw_composite_score, (summary_payload->>'raw_composite_score')::NUMERIC),
    action_score        = COALESCE(action_score,        (summary_payload->>'action_score')::NUMERIC),
    quality_score       = COALESCE(quality_score,       (summary_payload->>'quality_score')::NUMERIC),
    setup_label         = COALESCE(setup_label,          summary_payload->>'setup_label'),
    change_pct          = COALESCE(change_pct,          (summary_payload->>'change_pct')::NUMERIC)
WHERE summary_payload <> '{}'::jsonb;

CREATE INDEX IF NOT EXISTS idx_scan_results_pullback
    ON scan_results (market_key, trade_date DESC, pullback_score DESC);

CREATE INDEX IF NOT EXISTS idx_scan_results_breakout
    ON scan_results (market_key, trade_date DESC, breakout_score DESC);

CREATE INDEX IF NOT EXISTS idx_scan_results_pullback_period
    ON scan_results (market_key, trade_date DESC, pullback_ma_period)
    WHERE pullback_ma_period IS NOT NULL;
