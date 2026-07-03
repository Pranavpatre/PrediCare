-- SmartHealth — Bed Matrix + Test Availability (Project Pulse Module 1)
-- Two daily-ledger inputs: categorised bed occupancy + diagnostic test audit.
-- Run after 001_core.sql (+ 002 seed for diagnostic_tests).

-- ── Bed Matrix: General / ICU / Maternity ──────────────────────────────────
CREATE TYPE bed_type AS ENUM ('GENERAL', 'ICU', 'MATERNITY');

CREATE TABLE IF NOT EXISTS facility_beds (
    facility_id     UUID NOT NULL REFERENCES facilities(id),
    bed_type        bed_type NOT NULL,
    total_beds      INT NOT NULL DEFAULT 0,
    occupied_beds   INT NOT NULL DEFAULT 0,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (facility_id, bed_type)
);

-- ── Test Availability: daily Yes/No audit of key diagnostics ────────────────
CREATE TABLE IF NOT EXISTS test_availability (
    facility_id     UUID NOT NULL REFERENCES facilities(id),
    test_id         INT NOT NULL REFERENCES diagnostic_tests(id),
    available       BOOLEAN NOT NULL DEFAULT TRUE,
    checked_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (facility_id, test_id)
);

CREATE INDEX IF NOT EXISTS test_availability_unavailable
    ON test_availability (facility_id) WHERE available = FALSE;

COMMENT ON TABLE facility_beds IS 'Categorised bed matrix (General/ICU/Maternity) per facility.';
COMMENT ON TABLE test_availability IS 'Latest daily Yes/No diagnostic-test availability audit per facility.';
