-- SmartHealth — Per-bed "occupied until" dates
-- Run after 006_beds_and_tests.sql / 013_bed_occupied_until.sql.
--
-- Supersedes the single per-type occupied_until (013): each occupied bed can have
-- its own expected free-up date. Stored as a JSON array of ISO dates (one entry
-- per occupied bed of that type), e.g. ["2026-07-20","2026-07-22"].

ALTER TABLE facility_beds
    ADD COLUMN IF NOT EXISTS occupied_until_dates JSONB NOT NULL DEFAULT '[]'::jsonb;

COMMENT ON COLUMN facility_beds.occupied_until_dates IS
    'Per-occupied-bed expected free dates (JSON array of ISO date strings).';
