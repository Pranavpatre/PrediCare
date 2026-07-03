-- SmartHealth — Real District OPD/IPD Footfall (HMIS via data.gov.in)
-- Source: HMIS "Item-wise HMIS report of <State>" resources (district-monthly).
-- Real government footfall data — grounds the (otherwise synthetic) per-facility
-- footfall with actual district outpatient volumes. Run after 001_core.sql.

CREATE TABLE IF NOT EXISTS district_footfall (
    id              SERIAL PRIMARY KEY,
    state_ut        VARCHAR(100) NOT NULL,
    district        VARCHAR(150) NOT NULL,
    period          VARCHAR(20)  NOT NULL,        -- HMIS reporting year, e.g. 2018-19
    opd_annual      BIGINT,                       -- Allopathic outpatient attendance, annual
    opd_monthly_avg INT,                          -- opd_annual / 12
    source          VARCHAR(50)  NOT NULL DEFAULT 'HMIS/data.gov.in',
    resource_id     VARCHAR(64)  NOT NULL,
    ingested_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    UNIQUE (state_ut, district, period)
);

CREATE INDEX IF NOT EXISTS district_footfall_district_lc
    ON district_footfall (lower(district));

COMMENT ON TABLE district_footfall IS
    'Real district-level OPD footfall from HMIS (data.gov.in). Grounds synthetic per-facility footfall.';
