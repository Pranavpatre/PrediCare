"""
District-customized demand model — run by Celery worker.

Schedule (from celery_app.py):
  - run_demand_model : weekly (Mon 03:00 IST)

WHAT IT DOES
------------
For every facility it derives the requirement from that facility's OWN patient
inflow instead of a global constant:

    worst_case_daily_footfall = P95 of (opd_count + ipd_count) over the trailing
                                window, aggregated to one value per calendar day
    expected_daily_demand(med) = worst_case_daily_footfall
                                 x per-patient usage for the medicine's category
    dynamic_reorder_level(med) = expected_daily_demand x supplier lead_time_days
                                 (enough buffer to survive one lead-time at the
                                  facility's own worst-case demand)
    required_stock(med)        = dynamic_reorder_level x category safety_factor
                                 (target on-hand level)

Results land in facility_demand_profiles + facility_medicine_requirements, which
the health scorer then reads (see scoring_tasks.run_health_scores).

PROXIES (see 011_demand_model.sql header): footfall is used directly as the
demand signal (no catchment-population data exists); per-patient usage comes from
the tunable medicine_usage_rates table (no dispensing feed exists yet).

Fallback ladder when a facility has too little of its own footfall:
  facility  -> district_fallback (district_footfall monthly avg / 30)
            -> default (keep the medicine's global reorder_level)
"""

from __future__ import annotations

import math
import os

import structlog

from celery_app import celery_app

log = structlog.get_logger(__name__)

# Trailing window of daily snapshots used to characterise a facility's load.
DEMAND_WINDOW_DAYS = int(os.environ.get("DEMAND_WINDOW_DAYS", "90"))
# Minimum days of the facility's own data before we trust its P95; below this we
# fall back to the district monthly average.
MIN_FACILITY_DAYS = int(os.environ.get("DEMAND_MIN_FACILITY_DAYS", "7"))
# Global default safety factor when a category has no usage-rate row.
DEFAULT_SAFETY = 1.25
DEFAULT_USAGE_PER_100 = 20.0


def _sync_db_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    return url.replace("postgresql+asyncpg://", "postgresql://")


@celery_app.task(
    name="tasks.demand_tasks.run_demand_model",
    bind=True,
    max_retries=2,
    default_retry_delay=300,
)
def run_demand_model(self) -> dict:
    """Recompute per-facility demand profiles and dynamic reorder levels."""
    import psycopg2
    import psycopg2.extras

    log.info("demand_model_started", window_days=DEMAND_WINDOW_DAYS)

    try:
        conn = psycopg2.connect(_sync_db_url())
        conn.autocommit = False
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

        # ── Per-category usage rates (proxy) ─────────────────────────────────
        cur.execute(
            "SELECT category, units_per_100_patients, safety_factor "
            "FROM medicine_usage_rates"
        )
        usage = {
            r["category"]: (
                float(r["units_per_100_patients"]) / 100.0,
                float(r["safety_factor"]),
            )
            for r in cur.fetchall()
        }

        # ── Active medicines (category + lead time) ──────────────────────────
        cur.execute(
            "SELECT id, category, lead_time_days FROM medicines WHERE is_active = TRUE"
        )
        medicines = [
            (r["id"], r["category"], max(int(r["lead_time_days"] or 7), 1))
            for r in cur.fetchall()
        ]

        # ── Per-facility footfall distribution (own data), one value per day ──
        # Aggregate multiple same-day snapshots into a single daily total first,
        # then take mean + P95 across days.
        cur.execute(
            """
            WITH daily AS (
                SELECT facility_id,
                       time::date AS d,
                       SUM(opd_count + ipd_count) AS visits
                FROM daily_snapshots
                WHERE time >= NOW() - (%s || ' days')::interval
                GROUP BY facility_id, time::date
            )
            SELECT facility_id,
                   COUNT(*)                                                   AS n_days,
                   AVG(visits)                                                AS mean_f,
                   PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY visits)       AS p95_f
            FROM daily
            GROUP BY facility_id
            """,
            (DEMAND_WINDOW_DAYS,),
        )
        fac_stats = {
            str(r["facility_id"]): (
                int(r["n_days"]),
                float(r["mean_f"] or 0),
                float(r["p95_f"] or 0),
            )
            for r in cur.fetchall()
        }

        # ── District fallback: HMIS monthly OPD avg -> per-day ────────────────
        # Facilities too new to trust get their district's monthly average / 30.
        cur.execute(
            """
            SELECT f.id AS facility_id,
                   df.opd_monthly_avg
            FROM facilities f
            JOIN districts d  ON d.id = f.district_id
            LEFT JOIN LATERAL (
                SELECT opd_monthly_avg
                FROM district_footfall df
                WHERE lower(df.district) = lower(d.name)
                ORDER BY df.period DESC
                LIMIT 1
            ) df ON TRUE
            """
        )
        district_fallback = {
            str(r["facility_id"]): (
                float(r["opd_monthly_avg"]) / 30.0
                if r["opd_monthly_avg"]
                else 0.0
            )
            for r in cur.fetchall()
        }

        # ── All facilities + district grouping (for share / population factor)─
        cur.execute("SELECT id, district_id FROM facilities ORDER BY id")
        facilities = [(str(r["id"]), r["district_id"]) for r in cur.fetchall()]

        # District mean-footfall totals for share / population factor.
        dist_totals: dict[int, float] = {}
        dist_counts: dict[int, int] = {}
        for fac_id, dist_id in facilities:
            mean_f = fac_stats.get(fac_id, (0, 0.0, 0.0))[1]
            if mean_f <= 0:
                mean_f = district_fallback.get(fac_id, 0.0)
            dist_totals[dist_id] = dist_totals.get(dist_id, 0.0) + mean_f
            dist_counts[dist_id] = dist_counts.get(dist_id, 0) + 1

        profiles = 0
        requirements = 0

        for fac_id, dist_id in facilities:
            try:
                n_days, mean_f, p95_f = fac_stats.get(fac_id, (0, 0.0, 0.0))

                if n_days >= MIN_FACILITY_DAYS and p95_f > 0:
                    basis = "facility"
                elif district_fallback.get(fac_id, 0.0) > 0:
                    # No/low own data → use district monthly avg as both mean and
                    # (with a surge multiplier) the worst-case design load.
                    mean_f = district_fallback[fac_id]
                    p95_f = mean_f * 1.5
                    basis = "district_fallback"
                else:
                    # Nothing to go on → leave global reorder levels in place.
                    mean_f = mean_f or 0.0
                    p95_f = p95_f or 0.0
                    basis = "default"

                dist_total = dist_totals.get(dist_id, 0.0) or 1.0
                dist_avg = dist_total / max(dist_counts.get(dist_id, 1), 1)
                share = round(mean_f / dist_total, 4) if dist_total > 0 else 0.0
                pop_factor = round(mean_f / dist_avg, 3) if dist_avg > 0 else 1.0

                cur.execute(
                    """
                    INSERT INTO facility_demand_profiles (
                        facility_id, sample_days, mean_daily_footfall,
                        p95_daily_footfall, district_footfall_share,
                        population_factor, basis, computed_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
                    ON CONFLICT (facility_id) DO UPDATE SET
                        sample_days = EXCLUDED.sample_days,
                        mean_daily_footfall = EXCLUDED.mean_daily_footfall,
                        p95_daily_footfall = EXCLUDED.p95_daily_footfall,
                        district_footfall_share = EXCLUDED.district_footfall_share,
                        population_factor = EXCLUDED.population_factor,
                        basis = EXCLUDED.basis,
                        computed_at = NOW()
                    """,
                    (fac_id, n_days, round(mean_f, 2), round(p95_f, 2),
                     share, pop_factor, basis),
                )
                profiles += 1

                # ── Per-medicine dynamic requirements ────────────────────────
                # basis=default → skip; scorer falls back to the global reorder.
                if basis == "default" or p95_f <= 0:
                    continue

                for med_id, category, lead_days in medicines:
                    per_patient, safety = usage.get(
                        category, (DEFAULT_USAGE_PER_100 / 100.0, DEFAULT_SAFETY)
                    )
                    expected_daily = p95_f * per_patient
                    reorder = max(1, math.ceil(expected_daily * lead_days))
                    required = max(reorder, math.ceil(reorder * safety))

                    cur.execute(
                        """
                        INSERT INTO facility_medicine_requirements (
                            facility_id, medicine_id, expected_daily_demand,
                            dynamic_reorder_level, required_stock, computed_at
                        )
                        VALUES (%s, %s, %s, %s, %s, NOW())
                        ON CONFLICT (facility_id, medicine_id) DO UPDATE SET
                            expected_daily_demand = EXCLUDED.expected_daily_demand,
                            dynamic_reorder_level = EXCLUDED.dynamic_reorder_level,
                            required_stock = EXCLUDED.required_stock,
                            computed_at = NOW()
                        """,
                        (fac_id, med_id, round(expected_daily, 2), reorder, required),
                    )
                    requirements += 1

                conn.commit()

            except Exception as fac_err:
                conn.rollback()
                log.error("demand_model_facility_error", facility=fac_id,
                          error=str(fac_err))
                continue

        cur.close()
        conn.close()

        log.info("demand_model_complete", profiles=profiles,
                 requirements=requirements)
        return {"profiles": profiles, "requirements": requirements}

    except Exception as exc:
        log.error("demand_model_failed", error=str(exc))
        raise self.retry(exc=exc)
