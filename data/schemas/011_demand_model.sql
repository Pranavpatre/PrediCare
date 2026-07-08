-- SmartHealth — District-Customized Demand & Dynamic Reorder Model
-- Run after 001_core.sql (needs medicines, facilities, daily_snapshots).
--
-- WHY
-- ---
-- Until now every medicine used ONE global reorder_level (medicines.reorder_level,
-- district-wide default 50) and the health score compared stock against that fixed
-- number with absolute status bands (GREEN>=70 / YELLOW>=45). That treats a
-- 400-visit/day CHC and a 20-visit/day PHC identically, which is wrong: a "safe"
-- stock at a quiet PHC is a stockout waiting to happen at a busy CHC.
--
-- This model derives each facility's requirement from ITS OWN patient inflow:
--     required_stock = worst_case_daily_footfall (P95)
--                      x per-patient usage (by medicine category)
--                      x supplier lead-time (days)
--                      x safety factor
-- and a dynamic reorder level = enough buffer to survive one lead-time at the
-- facility's own worst-case demand. run_demand_model (weekly) computes these; the
-- health scorer then measures coverage against the dynamic level, not the constant.
--
-- PROXIES (be explicit — these are the levers to refine as real data arrives)
-- -------------------------------------------------------------------------
--  * Catchment population: NOT stored anywhere in the dataset. Observed daily
--    footfall (daily_snapshots.opd_count + ipd_count) is used directly as the
--    demand signal — footfall is the realised expression of catchment population,
--    so we measure it rather than a noisy population proxy. population_factor
--    below is a facility's footfall relative to its DISTRICT peers, kept for
--    context / relative bands only (it is NOT multiplied into required_stock, which
--    already uses the facility's own P95 — that would double-count).
--  * Per-patient medicine usage: there is no dispensing/consumption table
--    (stock_batches records receipts, not issues), so real "historical drawdown"
--    cannot be measured yet. medicine_usage_rates below is a tunable per-category
--    proxy (units consumed per 100 OPD/IPD visits). When a dispensing feed exists,
--    replace these rows with measured drawdown ÷ footfall per facility×category.

-- ---------------------------------------------------------------------------
-- 1) Per-category usage rate — the per-patient consumption proxy (tunable)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS medicine_usage_rates (
    category               medicine_category PRIMARY KEY,
    units_per_100_patients NUMERIC(8,2) NOT NULL,   -- expected units consumed per 100 visits
    safety_factor          NUMERIC(4,2) NOT NULL DEFAULT 1.25,
    notes                  TEXT,
    updated_at             TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE medicine_usage_rates IS
    'Per-patient medicine-usage proxy by category (units per 100 visits). Placeholder '
    'clinical defaults — replace with measured drawdown ÷ footfall once a dispensing feed exists.';

-- Seed sensible clinical defaults (idempotent).
INSERT INTO medicine_usage_rates (category, units_per_100_patients, safety_factor, notes) VALUES
    ('ESSENTIAL',        80, 1.25, 'Broad essential drugs — high per-visit issue rate'),
    ('ANALGESIC',        60, 1.20, 'Pain/fever — very common at OPD'),
    ('ANTIBIOTIC',       30, 1.30, 'Course-based; higher safety buffer'),
    ('ANTIHYPERTENSIVE', 25, 1.25, 'Chronic — steady monthly refills'),
    ('ORS',              25, 1.20, 'Diarrhoeal load, seasonal'),
    ('ANTIDIABETIC',     20, 1.25, 'Chronic — steady refills'),
    ('OTHER',            20, 1.25, 'Catch-all'),
    ('VACCINE',          15, 1.30, 'Cold-chain; protect against stockout'),
    ('DIAGNOSTICS_KIT',  10, 1.20, 'Per-test consumable'),
    ('REAGENT',          10, 1.20, 'Lab reagent per test'),
    ('ANTIMALARIAL',      8, 1.30, 'Seasonal / endemic pockets'),
    ('EQUIPMENT',         1, 1.10, 'Durable — low reorder cadence')
ON CONFLICT (category) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 2) Per-facility demand profile — computed weekly by run_demand_model
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS facility_demand_profiles (
    facility_id             UUID PRIMARY KEY REFERENCES facilities(id) ON DELETE CASCADE,
    sample_days             INT          NOT NULL DEFAULT 0,   -- # of days of data used
    mean_daily_footfall     NUMERIC(10,2) NOT NULL DEFAULT 0,
    p95_daily_footfall      NUMERIC(10,2) NOT NULL DEFAULT 0,  -- worst-case design load
    district_footfall_share NUMERIC(6,4)  NOT NULL DEFAULT 0,  -- facility mean / district total mean
    population_factor       NUMERIC(6,3)  NOT NULL DEFAULT 1,  -- facility mean / district avg-facility mean (context only)
    basis                   VARCHAR(20)  NOT NULL DEFAULT 'facility', -- facility | district_fallback | default
    computed_at             TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE facility_demand_profiles IS
    'Weekly per-facility demand profile derived from its own daily_snapshots footfall. '
    'basis=facility when enough data; district_fallback when the facility is too new '
    '(uses district_footfall monthly avg); default when neither is available.';

-- ---------------------------------------------------------------------------
-- 3) Per-facility × medicine dynamic requirement — replaces the global constant
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS facility_medicine_requirements (
    facility_id           UUID NOT NULL REFERENCES facilities(id) ON DELETE CASCADE,
    medicine_id           INT  NOT NULL REFERENCES medicines(id) ON DELETE CASCADE,
    expected_daily_demand NUMERIC(10,2) NOT NULL DEFAULT 0,  -- P95 footfall x per-patient usage
    dynamic_reorder_level INT           NOT NULL DEFAULT 0,  -- cover one lead-time at worst-case demand
    required_stock        INT           NOT NULL DEFAULT 0,  -- reorder level x safety factor (target on-hand)
    computed_at           TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    PRIMARY KEY (facility_id, medicine_id)
);

CREATE INDEX IF NOT EXISTS fmr_facility_idx
    ON facility_medicine_requirements (facility_id);

COMMENT ON TABLE facility_medicine_requirements IS
    'Dynamic per-facility reorder levels derived from local demand. The health scorer '
    'measures medicine coverage against dynamic_reorder_level (falling back to '
    'medicines.reorder_level when a row is absent).';
