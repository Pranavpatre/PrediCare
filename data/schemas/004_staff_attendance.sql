-- SmartHealth — Geofenced Staff Attendance (Project Pulse Module 1)
-- Geofenced check-in/check-out for doctors & specialists to combat absenteeism.
-- Run after 001_core.sql.

CREATE TABLE IF NOT EXISTS staff_attendance (
    id                  UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    facility_id         UUID NOT NULL REFERENCES facilities(id),
    user_id             UUID REFERENCES users(id),      -- who checked in (nullable for demo)
    attendance_date     DATE NOT NULL,                  -- local date, for consecutive-day queries
    check_in_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    check_out_at        TIMESTAMPTZ,
    -- Geolocation captured at check-in
    check_in_location   GEOMETRY(Point, 4326),
    distance_m          DOUBLE PRECISION,               -- metres from the facility
    within_geofence     BOOLEAN NOT NULL DEFAULT FALSE, -- distance_m <= geofence radius
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- One open check-in per user per facility per day (re-check-in updates).
CREATE UNIQUE INDEX IF NOT EXISTS staff_attendance_daily_uniq
    ON staff_attendance (facility_id, user_id, attendance_date);
CREATE INDEX IF NOT EXISTS staff_attendance_facility_date
    ON staff_attendance (facility_id, attendance_date DESC);

COMMENT ON TABLE  staff_attendance IS 'Geofenced staff check-in/out (Project Pulse Module 1).';
COMMENT ON COLUMN staff_attendance.within_geofence IS 'True when check-in GPS was within the facility geofence radius.';
