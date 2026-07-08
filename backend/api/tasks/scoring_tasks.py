"""
Scoring and anomaly detection tasks — run by Celery worker.

Schedule (from celery_app.py):
  - run_health_scores  : every 6 hours
  - run_anomaly_scan   : every hour

Table alignment notes (001_core.sql):
  - facility_health_scores is a hypertable in local dev (TimescaleDB) and a plain table on Cloud SQL; either way `time` is required.
    Every INSERT must supply `time`.
  - Weights: medicine 25%, doctor 20%, bed 20%, wait_time 20%, diagnostics 15%.
    (overall_score is the composite; the remaining 100% is covered by all five.)
"""

from __future__ import annotations

import os

import structlog

from celery_app import celery_app

log = structlog.get_logger(__name__)


# ── Status band configuration ────────────────────────────────────────────────
# District-relative bands peer-benchmark each facility against its district while
# keeping absolute guardrails, so a healthy district isn't forced to have a
# "worst" facility flagged RED and a struggling district's genuinely
# under-resourced facilities still read RED. All tunable via env for rollback.
RELATIVE_BANDS = os.environ.get("SCORING_RELATIVE_BANDS", "true").lower() != "false"
ABS_FLOOR = float(os.environ.get("SCORING_ABS_FLOOR", "40"))   # below → RED regardless of peers
ABS_GREEN = float(os.environ.get("SCORING_ABS_GREEN", "70"))   # at/above → GREEN regardless of peers
MIN_DISTRICT_N = int(os.environ.get("SCORING_MIN_DISTRICT_N", "4"))  # need this many facilities to rank
# Absolute fallback bands (small districts / relative disabled).
ABS_GREEN_CUT = 70.0
ABS_YELLOW_CUT = 45.0


def _district_thresholds(scores: list[float]) -> tuple[float, float] | None:
    """Tercile (33rd, 67th pct) cut points for a district's score distribution,
    used to rank facilities against their peers. Returns None to signal 'use the
    absolute fallback bands' — when relative banding is disabled or the district
    has too few facilities (< MIN_DISTRICT_N) to rank meaningfully."""
    import statistics

    if not RELATIVE_BANDS or len(scores) < MIN_DISTRICT_N:
        return None
    yellow_cut, green_cut = statistics.quantiles(scores, n=3, method="inclusive")
    return (yellow_cut, green_cut)


def _classify_status(
    score: float,
    bands: tuple[float, float] | None,
    has_critical: bool,
) -> str:
    """Assign GREEN/YELLOW/RED. An open CRITICAL alert always forces RED. With no
    district bands (small district / relative disabled) the classic absolute
    70/45 bands apply. Otherwise absolute guardrails decide the clearly-bad
    (< ABS_FLOOR → RED) and clearly-good (>= ABS_GREEN → GREEN), and the
    contested middle is split by the district's terciles."""
    if has_critical:
        return "RED"
    if bands is None:
        if score >= ABS_GREEN_CUT:
            return "GREEN"
        return "YELLOW" if score >= ABS_YELLOW_CUT else "RED"
    # District-relative with absolute guardrails.
    if score < ABS_FLOOR:
        return "RED"
    if score >= ABS_GREEN:
        return "GREEN"
    yellow_cut, green_cut = bands
    if score >= green_cut:
        return "GREEN"
    return "YELLOW" if score >= yellow_cut else "RED"


def _sync_db_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    return url.replace("postgresql+asyncpg://", "postgresql://")


def _ensure_latest_matviews(cur) -> None:
    """Create the latest-score / latest-snapshot materialized views + their
    unique indexes if missing. These back the read-path queries (dashboard,
    facilities, assistant) so they don't scan the full time-series tables.
    Idempotent — safe to call before every REFRESH. Runs with autocommit."""
    cur.execute(
        """
        CREATE MATERIALIZED VIEW IF NOT EXISTS mv_facility_latest_score AS
        SELECT DISTINCT ON (facility_id)
            facility_id, time, status, overall_score,
            medicine_score, doctor_score, bed_score,
            wait_time_score, diagnostics_score
        FROM facility_health_scores
        ORDER BY facility_id, time DESC
        """
    )
    cur.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS mv_fls_pk "
        "ON mv_facility_latest_score(facility_id)"
    )
    cur.execute(
        """
        CREATE MATERIALIZED VIEW IF NOT EXISTS mv_facility_latest_snapshot AS
        SELECT DISTINCT ON (facility_id)
            facility_id, doctors_present, opd_count, beds_occupied, time
        FROM daily_snapshots
        ORDER BY facility_id, time DESC
        """
    )
    cur.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS mv_fls_snap_pk "
        "ON mv_facility_latest_snapshot(facility_id)"
    )


# ---------------------------------------------------------------------------
# Facility health scores
# ---------------------------------------------------------------------------

@celery_app.task(
    name="tasks.scoring_tasks.run_health_scores",
    bind=True,
    max_retries=2,
    default_retry_delay=120,
)
def run_health_scores(self) -> dict:
    """
    Compute a composite health score for every active facility and persist a
    new row in facility_health_scores.

    Sub-scores (0-100):
      medicine_score    — avg stock coverage vs reorder_level, capped at 100
      doctor_score      — doctors_present / doctors_rostered from latest snapshot
      bed_score         — inverse occupancy: (capacity - occupied) / capacity
      wait_time_score   — placeholder 75; replace when wait-time table is added
      diagnostics_score — avg diagnostic kit availability; placeholder 80

    Overall = 0.25·med + 0.20·doc + 0.20·bed + 0.20·wait + 0.15·diag

    Status: assigned in a second pass so bands can be DISTRICT-RELATIVE. Absolute
    guardrails force RED below ABS_FLOOR (objectively under-resourced) and GREEN
    at/above ABS_GREEN (objectively adequate); the contested middle is split by
    the district's terciles. Small districts (< MIN_DISTRICT_N) and
    SCORING_RELATIVE_BANDS=false fall back to absolute 70/45. An open CRITICAL
    alert always forces RED. See _classify_status / _district_thresholds.
    """
    import psycopg2
    import psycopg2.extras

    try:
        conn = psycopg2.connect(_sync_db_url())
        conn.autocommit = False
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

        cur.execute(
            "SELECT id, bed_capacity, district_id FROM facilities ORDER BY id"
        )
        facilities = cur.fetchall()

        computed: list[dict] = []
        skipped = 0

        for fac in facilities:
            fac_id = str(fac["id"])
            bed_capacity: int = max(fac["bed_capacity"] or 10, 1)
            district_id = fac["district_id"]

            try:
                # ── Medicine score ───────────────────────────────────────────
                # Coverage = min(current_stock / reorder_level, 1.0) per medicine,
                # averaged across all active medicines. The reorder level is the
                # facility's DEMAND-DERIVED dynamic level (facility_medicine_
                # requirements, computed by run_demand_model from local footfall)
                # when present, falling back to the medicine's global reorder_level
                # for facilities that don't yet have a demand profile.
                cur.execute(
                    """
                    SELECT
                        AVG(
                            LEAST(
                                COALESCE(sb.total_stock, 0)::float
                                    / NULLIF(
                                        COALESCE(fmr.dynamic_reorder_level,
                                                 m.reorder_level), 0),
                                1.0
                            )
                        ) AS coverage
                    FROM medicines m
                    LEFT JOIN (
                        SELECT medicine_id, SUM(quantity) AS total_stock
                        FROM stock_batches
                        WHERE facility_id = %s AND expiry_date > CURRENT_DATE
                        GROUP BY medicine_id
                    ) sb ON sb.medicine_id = m.id
                    LEFT JOIN facility_medicine_requirements fmr
                        ON fmr.medicine_id = m.id AND fmr.facility_id = %s
                    WHERE m.is_active = TRUE
                    """,
                    (fac_id, fac_id),
                )
                row = cur.fetchone()
                medicine_score = round(float(row["coverage"] or 0.5) * 100, 1)

                # ── Doctor score ─────────────────────────────────────────────
                # Ratio of present to rostered doctors from the most recent snapshot.
                cur.execute(
                    """
                    SELECT doctors_present, doctors_rostered
                    FROM daily_snapshots
                    WHERE facility_id = %s
                    ORDER BY time DESC
                    LIMIT 1
                    """,
                    (fac_id,),
                )
                snap = cur.fetchone()
                if snap and snap["doctors_rostered"] and snap["doctors_rostered"] > 0:
                    doctor_ratio = min(
                        snap["doctors_present"] / snap["doctors_rostered"], 1.0
                    )
                else:
                    doctor_ratio = 0.8  # assume reasonable coverage when no data
                doctor_score = round(doctor_ratio * 100, 1)

                # ── Bed score ────────────────────────────────────────────────
                # How much spare capacity exists. Higher = better.
                cur.execute(
                    """
                    SELECT beds_occupied
                    FROM daily_snapshots
                    WHERE facility_id = %s
                    ORDER BY time DESC
                    LIMIT 1
                    """,
                    (fac_id,),
                )
                bed_snap = cur.fetchone()
                beds_occupied = int(bed_snap["beds_occupied"]) if bed_snap else 0
                bed_ratio = max(0.0, (bed_capacity - beds_occupied) / bed_capacity)
                bed_score = round(min(bed_ratio, 1.0) * 100, 1)

                # ── Wait-time score (placeholder) ────────────────────────────
                # Replace with actual wait-time data when the table is available.
                wait_time_score = 75.0

                # ── Diagnostics score (placeholder) ──────────────────────────
                # Replace with: avg(diagnostic_stock_snapshots.quantity / reorder_level)
                # once diagnostic kit data flows regularly.
                cur.execute(
                    """
                    SELECT AVG(
                        LEAST(dss.quantity::float / NULLIF(dt.reorder_level, 0), 1.0)
                    ) AS diag_coverage
                    FROM diagnostic_stock_snapshots dss
                    JOIN diagnostic_tests dt ON dt.id = dss.test_id
                    WHERE dss.facility_id = %s
                      AND dss.time >= NOW() - INTERVAL '24 hours'
                    """,
                    (fac_id,),
                )
                diag_row = cur.fetchone()
                diag_coverage = float(diag_row["diag_coverage"] or 0.8)
                diagnostics_score = round(min(diag_coverage, 1.0) * 100, 1)

                # ── Composite overall score ──────────────────────────────────
                overall_score = round(
                    0.25 * medicine_score
                    + 0.20 * doctor_score
                    + 0.20 * bed_score
                    + 0.20 * wait_time_score
                    + 0.15 * diagnostics_score,
                    1,
                )
                # ── Critical-alert flag ──────────────────────────────────────
                # The composite score averages across all medicines/diagnostics,
                # so a single critical shortage (e.g. one stocked-out medicine
                # among many well-stocked ones) can get diluted and never pull
                # the facility below its band. Any facility with an OPEN CRITICAL
                # alert must show RED regardless of the averaged score / district
                # rank — one critical stockout is enough to flag it.
                cur.execute(
                    """
                    SELECT 1 FROM alerts
                    WHERE facility_id = %s AND status = 'OPEN' AND severity = 'CRITICAL'
                    LIMIT 1
                    """,
                    (fac_id,),
                )
                has_critical = cur.fetchone() is not None

                # Status is assigned in a second pass below, once every facility's
                # score is known, so bands can be set relative to district peers.
                computed.append({
                    "fac_id": fac_id,
                    "district_id": district_id,
                    "med": medicine_score,
                    "doc": doctor_score,
                    "bed": bed_score,
                    "wait": wait_time_score,
                    "diag": diagnostics_score,
                    "overall": overall_score,
                    "has_critical": has_critical,
                })

            except Exception as fac_err:
                # Reset the aborted transaction state (reads only up to here) and
                # skip this facility.
                conn.rollback()
                skipped += 1
                log.error(
                    "health_score_error",
                    facility=fac_id,
                    error=str(fac_err),
                )
                continue

        # ── District-relative status bands (second pass) ─────────────────────
        # Peer-benchmark each facility against its district cohort. See
        # _classify_status / _district_thresholds for the hybrid band logic.
        from collections import defaultdict

        by_district: dict = defaultdict(list)
        for c in computed:
            by_district[c["district_id"]].append(c["overall"])
        district_bands = {
            did: _district_thresholds(scores)
            for did, scores in by_district.items()
        }

        # ── Persist (single batch INSERT; must supply `time`) ────────────────
        from psycopg2.extras import execute_values

        rows = []
        for c in computed:
            status = _classify_status(
                c["overall"],
                district_bands.get(c["district_id"]),
                c["has_critical"],
            )
            rows.append((
                c["fac_id"], c["med"], c["doc"], c["bed"],
                c["wait"], c["diag"], c["overall"], status,
            ))
        if rows:
            execute_values(
                cur,
                """
                INSERT INTO facility_health_scores (
                    time, facility_id,
                    medicine_score, doctor_score, bed_score,
                    wait_time_score, diagnostics_score,
                    overall_score, status
                ) VALUES %s
                """,
                rows,
                template="(NOW(), %s, %s, %s, %s, %s, %s, %s, %s)",
            )
        scored = len(rows)

        conn.commit()

        # Refresh the read-path materialized views so the dashboard / facilities
        # / assistant queries (which join these instead of scanning the full
        # facility_health_scores + daily_snapshots tables) see fresh values.
        # CONCURRENTLY can't run inside a transaction, so use autocommit; a
        # refresh failure must never fail the scoring run.
        try:
            conn.autocommit = True
            rcur = conn.cursor()
            _ensure_latest_matviews(rcur)
            rcur.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY mv_facility_latest_score")
            rcur.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY mv_facility_latest_snapshot")
            rcur.close()
            log.info("latest_matviews_refreshed")
        except Exception as refresh_err:
            log.error("latest_matviews_refresh_failed", error=str(refresh_err))

        cur.close()
        conn.close()

        log.info("health_scores_updated", scored=scored, skipped=skipped)
        return {"scored": scored, "skipped": skipped}

    except Exception as exc:
        log.error("health_scoring_failed", error=str(exc))
        raise self.retry(exc=exc)


# ---------------------------------------------------------------------------
# Anomaly detection scan
# ---------------------------------------------------------------------------

@celery_app.task(
    name="tasks.scoring_tasks.run_anomaly_scan",
    bind=True,
    max_retries=2,
    default_retry_delay=120,
)
def run_anomaly_scan(self) -> dict:
    """
    Run statistical anomaly detection across all facilities.

    Current implementation: z-score detection on rolling 30-day opd_count.
    Any facility whose latest opd_count deviates by > 2.5 σ from its own
    30-day mean triggers an ANOMALY prediction and an INFO alert.

    Replace with the ml-models/anomaly IsolationForest artefact once trained.
    """
    import psycopg2
    import psycopg2.extras

    log.info("anomaly_scan_started")

    try:
        conn = psycopg2.connect(_sync_db_url())
        conn.autocommit = False
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

        cur.execute("SELECT id, code FROM facilities ORDER BY id")
        facilities = cur.fetchall()

        anomalies_detected = 0

        for fac in facilities:
            fac_id = str(fac["id"])
            fac_code = fac["code"]

            try:
                # 30-day rolling stats per facility
                cur.execute(
                    """
                    SELECT
                        AVG(opd_count + ipd_count)         AS mean_visits,
                        STDDEV(opd_count + ipd_count)      AS stddev_visits,
                        MAX(time)                          AS latest_time,
                        (
                            SELECT opd_count + ipd_count
                            FROM daily_snapshots ds2
                            WHERE ds2.facility_id = %s
                            ORDER BY time DESC
                            LIMIT 1
                        )                                  AS latest_visits
                    FROM daily_snapshots
                    WHERE facility_id = %s
                      AND time >= NOW() - INTERVAL '30 days'
                    """,
                    (fac_id, fac_id),
                )
                stats = cur.fetchone()

                if (
                    not stats
                    or stats["mean_visits"] is None
                    or stats["stddev_visits"] is None
                    or float(stats["stddev_visits"]) == 0
                ):
                    continue

                mean = float(stats["mean_visits"])
                stddev = float(stats["stddev_visits"])
                latest = float(stats["latest_visits"] or 0)
                z_score = (latest - mean) / stddev

                if abs(z_score) > 2.5:
                    anomalies_detected += 1
                    direction = "spike" if z_score > 0 else "drop"
                    reasoning = {
                        "z_score": round(z_score, 2),
                        "mean_visits": round(mean, 1),
                        "stddev_visits": round(stddev, 1),
                        "latest_visits": latest,
                        "direction": direction,
                    }

                    import json
                    cur.execute(
                        """
                        INSERT INTO ai_predictions (
                            facility_id, prediction_type, predicted_value,
                            confidence, reasoning, recommendation,
                            model_version, horizon_days
                        )
                        VALUES (%s, 'ANOMALY', %s, %s, %s,
                                %s, 'anomaly_zscore_v1', 1)
                        """,
                        (
                            fac_id,
                            round(abs(z_score), 2),
                            round(min(abs(z_score) / 5.0, 0.99), 3),
                            json.dumps(reasoning),
                            f"Unusual footfall {direction} detected (z={z_score:.2f}). Investigate.",
                        ),
                    )

                    anomaly_params = {
                        "facility": fac_code,
                        "direction": direction,   # 'spike' | 'drop'
                        "latest": round(latest),
                        "mean": round(mean, 1),
                        "zscore": round(z_score, 2),
                    }
                    cur.execute(
                        """
                        INSERT INTO alerts (
                            facility_id, severity, status, title, body,
                            message_key, message_params
                        )
                        SELECT %s, 'INFO'::alert_severity, 'OPEN', %s, %s,
                               'alert.anomaly', %s::jsonb
                        WHERE NOT EXISTS (
                            SELECT 1 FROM alerts
                            WHERE facility_id = %s
                              AND title = %s
                              AND status = 'OPEN'
                              AND created_at >= NOW() - INTERVAL '6 hours'
                        )
                        """,
                        (
                            fac_id,
                            f"Anomaly detected: {fac_code}",
                            (
                                f"Footfall {direction} at {fac_code}: "
                                f"{latest:.0f} visits vs {mean:.1f} avg "
                                f"(z={z_score:.2f}). Review staffing and supplies."
                            ),
                            json.dumps(anomaly_params),
                            fac_id,
                            f"Anomaly detected: {fac_code}",
                        ),
                    )

            except Exception as fac_err:
                conn.rollback()
                log.error(
                    "anomaly_scan_facility_error",
                    facility=fac_code,
                    error=str(fac_err),
                )
                continue

        conn.commit()
        cur.close()
        conn.close()

        log.info("anomaly_scan_complete", anomalies_detected=anomalies_detected)
        return {
            "status": "anomaly_scan_completed",
            "anomalies_detected": anomalies_detected,
        }

    except Exception as exc:
        log.error("anomaly_scan_failed", error=str(exc))
        raise self.retry(exc=exc)


# ---------------------------------------------------------------------------
# Staff attendance escalation (Project Pulse Module 3)
# ---------------------------------------------------------------------------

@celery_app.task(
    name="tasks.scoring_tasks.run_attendance_escalation",
    bind=True,
    max_retries=2,
    default_retry_delay=120,
)
def run_attendance_escalation(self) -> dict:
    """Escalate facilities with zero on-site (geofenced) attendance for N+
    consecutive days into the admin feed as CRITICAL alerts.

    Only considers facilities that HAVE attendance history (at least one
    check-in ever) — facilities that never onboarded attendance are not
    flagged as "absent". Dedups against alerts opened in the last 24h.
    """
    import psycopg2

    days = int(os.environ.get("ATTENDANCE_ESCALATION_DAYS", "3"))
    try:
        conn = psycopg2.connect(_sync_db_url())
        conn.autocommit = False
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO alerts (facility_id, severity, status, title, body,
                                message_key, message_params)
            SELECT f.id, 'CRITICAL'::alert_severity, 'OPEN',
                   'Zero doctor attendance: ' || f.name,
                   f.name || ' has reported zero on-site attendance for '
                       || %s || '+ consecutive days. Action recommended.',
                   'alert.attendance',
                   jsonb_build_object('facility', f.name, 'days', %s::int)
            FROM facilities f
            WHERE EXISTS (
                    SELECT 1 FROM staff_attendance a WHERE a.facility_id = f.id
                  )
              AND NOT EXISTS (
                    SELECT 1 FROM staff_attendance a
                    WHERE a.facility_id = f.id
                      AND a.within_geofence = TRUE
                      AND a.attendance_date > CURRENT_DATE - %s
                  )
              AND NOT EXISTS (
                    SELECT 1 FROM alerts al
                    WHERE al.facility_id = f.id
                      AND al.title = 'Zero doctor attendance: ' || f.name
                      AND al.status = 'OPEN'
                      AND al.created_at >= NOW() - INTERVAL '24 hours'
                  )
            """,
            (days, days, days),
        )
        escalated = cur.rowcount
        conn.commit()
        cur.close()
        conn.close()
        log.info("attendance_escalation_complete", escalated=escalated, days=days)
        return {"status": "attendance_escalation_completed", "escalated": escalated}
    except Exception as exc:
        log.error("attendance_escalation_failed", error=str(exc))
        raise self.retry(exc=exc)
