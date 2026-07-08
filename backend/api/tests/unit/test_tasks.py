"""Celery task tests — run the scoring/anomaly/attendance tasks eagerly against
the seeded test DB. These tasks use psycopg2 (sync) so they run without the
async engine. Also validates the materialized-view refresh path."""
import pytest


def _run(task):
    # Bound tasks (bind=True): .apply() executes synchronously (eager) and
    # returns an EagerResult; .get() returns the task's dict (or re-raises).
    return task.apply().get()


def test_run_health_scores_scores_facilities():
    from tasks.scoring_tasks import run_health_scores
    result = _run(run_health_scores)
    assert isinstance(result, dict)
    assert result.get("scored", 0) >= 1  # seeded facilities get scored


def test_health_scores_refresh_matviews_populated():
    """After scoring, the latest-score matview should have rows."""
    import os
    import psycopg2
    dsn = os.environ["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://")
    conn = psycopg2.connect(dsn)
    try:
        cur = conn.cursor()
        cur.execute("SELECT count(*) FROM mv_facility_latest_score")
        assert cur.fetchone()[0] >= 1
    finally:
        conn.close()


def test_run_anomaly_scan():
    from tasks.scoring_tasks import run_anomaly_scan
    result = _run(run_anomaly_scan)
    assert isinstance(result, dict)
    assert "anomalies_detected" in result


def test_run_attendance_escalation():
    from tasks.scoring_tasks import run_attendance_escalation
    result = _run(run_attendance_escalation)
    assert isinstance(result, dict)
    assert "escalated" in result


def test_run_district_prediction_scan():
    from tasks.prediction_tasks import run_district_prediction_scan
    result = run_district_prediction_scan.apply().get()
    assert isinstance(result, dict)
    assert "predictions_written" in result


def test_run_single_facility_prediction():
    import os
    import psycopg2
    from tasks.prediction_tasks import run_single_facility_prediction
    dsn = os.environ["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://")
    conn = psycopg2.connect(dsn)
    try:
        cur = conn.cursor()
        cur.execute("SELECT id FROM facilities LIMIT 1")
        fac = str(cur.fetchone()[0])
        cur.execute("SELECT id FROM medicines LIMIT 1")
        med = cur.fetchone()[0]
    finally:
        conn.close()
    result = run_single_facility_prediction.apply(args=[fac, med]).get()
    assert isinstance(result, dict)


# ── Demand model (district-customized reorder levels) ─────────────────────────

def test_run_demand_model():
    from tasks.demand_tasks import run_demand_model
    result = _run(run_demand_model)
    assert isinstance(result, dict)
    assert "profiles" in result and "requirements" in result
    # every seeded facility should get a profile row (even if basis=default)
    assert result["profiles"] >= 1


def test_demand_then_health_scores_still_score():
    """Health scores must still compute after the demand model populates the
    facility_medicine_requirements the scorer now LEFT JOINs against."""
    from tasks.demand_tasks import run_demand_model
    from tasks.scoring_tasks import run_health_scores
    _run(run_demand_model)
    result = _run(run_health_scores)
    assert result.get("scored", 0) >= 1


def test_demand_usage_rates_seeded():
    import os
    import psycopg2
    dsn = os.environ["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://")
    conn = psycopg2.connect(dsn)
    try:
        cur = conn.cursor()
        cur.execute("SELECT count(*) FROM medicine_usage_rates")
        assert cur.fetchone()[0] >= 1
        # profiles table is populated by the task
        from tasks.demand_tasks import run_demand_model
        run_demand_model.apply().get()
        cur.execute("SELECT count(*) FROM facility_demand_profiles")
        assert cur.fetchone()[0] >= 1
    finally:
        conn.close()
