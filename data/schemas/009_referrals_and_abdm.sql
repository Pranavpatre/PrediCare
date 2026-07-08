-- 009_referrals_and_abdm.sql
-- Digital patient referral (PHC/CHC → District Hospital) + ABDM linkage fields.
-- These were previously created only via the ORM models / direct DDL on the
-- live DBs; this file brings data/schemas (the source of truth) in sync so a
-- fresh database has the full referral feature. Idempotent.
--
-- See backend/api/models/referral.py and docs/PRD-digital-referral.md.

-- ── ABDM linkage columns (reserved; live calls deferred) ─────────────────────
ALTER TABLE users      ADD COLUMN IF NOT EXISTS hpr_id VARCHAR(32);   -- Health Professional Registry
ALTER TABLE facilities ADD COLUMN IF NOT EXISTS hfr_id VARCHAR(32);   -- Health Facility Registry

-- ── Patient (minimal, additive record) ──────────────────────────────────────
CREATE TABLE IF NOT EXISTS patients (
    id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    phone         VARCHAR(15)  NOT NULL,
    name          VARCHAR(200) NOT NULL,
    sex           VARCHAR(10),
    year_of_birth INTEGER,
    abha_id       VARCHAR(64),                      -- ABDM linkage, later
    created_at    TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_patients_phone ON patients(phone);
CREATE INDEX IF NOT EXISTS idx_patients_name  ON patients(name);

-- ── Referral (travels to the patient's phone; retrieved by a doctor) ─────────
CREATE TABLE IF NOT EXISTS referrals (
    id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    patient_id       UUID NOT NULL REFERENCES patients(id),
    from_facility_id UUID NOT NULL REFERENCES facilities(id),
    to_facility_id   UUID REFERENCES facilities(id),   -- NULL = any district hospital
    code             VARCHAR(20) NOT NULL UNIQUE,
    reason           TEXT,
    clinical_summary JSONB,
    status           VARCHAR(20) NOT NULL DEFAULT 'CREATED',  -- CREATED|DELIVERED|VIEWED|COMPLETED|EXPIRED
    created_by       UUID REFERENCES users(id),
    created_at       TIMESTAMPTZ DEFAULT now(),
    expires_at       TIMESTAMPTZ,
    delivered_at     TIMESTAMPTZ,
    viewed_at        TIMESTAMPTZ,
    completed_at     TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_referrals_patient ON referrals(patient_id);
CREATE INDEX IF NOT EXISTS idx_referrals_to_fac  ON referrals(to_facility_id);
CREATE INDEX IF NOT EXISTS idx_referrals_code    ON referrals(code);

-- ── Access log (consent / audit trail — DPDP §6) ─────────────────────────────
CREATE TABLE IF NOT EXISTS referral_access_log (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    referral_id UUID NOT NULL REFERENCES referrals(id),
    accessed_by VARCHAR(64) NOT NULL,      -- user uuid or 'system'
    method      VARCHAR(16) NOT NULL,      -- SEARCH|CODE|QR|OTP
    tier        INTEGER NOT NULL DEFAULT 1,-- 1=referral-consent, 2=OTP/break-glass
    reason      TEXT,
    accessed_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_referral_access_referral ON referral_access_log(referral_id);

-- ── Visit note (outcome appended by receiving facility — floating history) ───
CREATE TABLE IF NOT EXISTS visit_notes (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    referral_id UUID NOT NULL REFERENCES referrals(id),
    facility_id UUID REFERENCES facilities(id),
    author_id   UUID REFERENCES users(id),
    note        JSONB NOT NULL,            -- {diagnosis, action, follow_up, notes}
    created_at  TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_visit_notes_referral ON visit_notes(referral_id);
