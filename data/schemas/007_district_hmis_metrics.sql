-- SmartHealth — Real District HMIS Metrics (data.gov.in), generic long-format.
-- Source: the SAME "Item-wise HMIS report of <State>" resources already used for
-- OPD footfall (005). Those resources carry ~260 district-monthly indicators;
-- this table lets us ingest any of them (IPD head count, medicine stock-out
-- rate, lab tests, immunisation, deliveries, …) keyed by metric name.
-- Grounds otherwise-synthetic operational data with real government figures.
-- Run after 001_core.sql and 005_district_footfall.sql.

CREATE TABLE IF NOT EXISTS district_hmis_metrics (
    id            SERIAL PRIMARY KEY,
    state_ut      VARCHAR(100) NOT NULL,
    district      VARCHAR(150) NOT NULL,
    period        VARCHAR(20)  NOT NULL,        -- HMIS reporting year, e.g. 2016-17
    metric        VARCHAR(40)  NOT NULL,        -- 'ipd_headcount' | 'stockout_rate' | …
    annual_value  NUMERIC,                      -- HMIS 'Total' column (sum of months)
    monthly_avg   NUMERIC,                      -- mean of available monthly values
    source        VARCHAR(50)  NOT NULL DEFAULT 'HMIS/data.gov.in',
    resource_id   VARCHAR(64)  NOT NULL,
    ingested_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    UNIQUE (state_ut, district, period, metric)
);

-- Facility detail matches on lower(district); metric narrows the lookup.
CREATE INDEX IF NOT EXISTS district_hmis_metrics_district_metric
    ON district_hmis_metrics (lower(district), metric);

COMMENT ON TABLE district_hmis_metrics IS
    'Real district-level HMIS indicators (data.gov.in), long format keyed by metric. '
    'annual_value = raw HMIS Total (a count for e.g. IPD; a summed rate for stock-out — '
    'use monthly_avg for rate-type metrics).';
