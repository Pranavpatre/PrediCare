-- 008_latest_score_matviews.sql
-- Read-path materialized views: latest health score + latest daily snapshot
-- per facility. The dashboard / facilities / assistant endpoints join these
-- instead of running DISTINCT ON over the full facility_health_scores (~940k
-- rows) and daily_snapshots (~770k rows) time-series tables on every request —
-- that made the national admin map, Facilities browse and AI assistant take
-- 20-90s. With these views those queries drop to milliseconds (scoped) /
-- a few seconds (national).
--
-- Refreshed by tasks.scoring_tasks.run_health_scores (every 6h) via
-- REFRESH MATERIALIZED VIEW CONCURRENTLY (needs the UNIQUE indexes below).
-- The scoring task also creates them if missing (self-healing), so this file
-- is only needed for a clean bootstrap.

CREATE MATERIALIZED VIEW IF NOT EXISTS mv_facility_latest_score AS
SELECT DISTINCT ON (facility_id)
    facility_id, time, status, overall_score,
    medicine_score, doctor_score, bed_score,
    wait_time_score, diagnostics_score
FROM facility_health_scores
ORDER BY facility_id, time DESC;

CREATE UNIQUE INDEX IF NOT EXISTS mv_fls_pk
    ON mv_facility_latest_score(facility_id);

CREATE MATERIALIZED VIEW IF NOT EXISTS mv_facility_latest_snapshot AS
SELECT DISTINCT ON (facility_id)
    facility_id, doctors_present, opd_count, beds_occupied, time
FROM daily_snapshots
ORDER BY facility_id, time DESC;

CREATE UNIQUE INDEX IF NOT EXISTS mv_fls_snap_pk
    ON mv_facility_latest_snapshot(facility_id);
