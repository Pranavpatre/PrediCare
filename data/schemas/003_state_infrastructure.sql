-- SmartHealth — Real State-Level Health Infrastructure
-- Source: data.gov.in resource d133eac1-143f-4c1d-bdc4-b9dfd73ab78c
--   "State/UT-wise Number of Beds at PHC, CHC, SDH, DH and Medical Colleges
--    in India (Rural + Urban) as on 31-03-2023"
--
-- This is REAL government open data, ingested by
-- scripts/ingest_state_infrastructure.py. Values are BED COUNTS aggregated to
-- the State/UT level (not individual facilities). It grounds the national
-- context / overview layer of the dashboard alongside the operational
-- (synthetic, per-facility) demo data.
--
-- Run after 001_core.sql.

CREATE TABLE IF NOT EXISTS state_infrastructure (
    id                      SERIAL PRIMARY KEY,
    state_ut                VARCHAR(100) NOT NULL UNIQUE,   -- e.g. "Maharashtra"
    -- Bed counts. NULL where the source reports "NA".
    phc_beds                INT,
    chc_beds                INT,
    sub_district_beds       INT,   -- SUB DISTRICT / SUB DIVISIONAL HOSPITAL
    district_hospital_beds  INT,
    medical_college_beds    INT,
    total_beds              INT,
    source                  VARCHAR(50)  NOT NULL DEFAULT 'data.gov.in',
    source_resource_id      VARCHAR(64)  NOT NULL,
    as_on_date              DATE,                            -- reporting date of the dataset
    ingested_at             TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE  state_infrastructure IS
    'Real state/UT-level public-health bed capacity from data.gov.in. Aggregate, not per-facility.';
COMMENT ON COLUMN state_infrastructure.phc_beds IS 'Total beds across all PHCs in the state/UT.';
