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


# ── District-relative status bands (pure functions, no DB) ────────────────────

def test_classify_absolute_fallback_when_no_bands():
    from tasks.scoring_tasks import _classify_status
    # bands=None → classic absolute 70/45
    assert _classify_status(72, None, False) == "GREEN"
    assert _classify_status(50, None, False) == "YELLOW"
    assert _classify_status(30, None, False) == "RED"


def test_classify_critical_alert_forces_red():
    from tasks.scoring_tasks import _classify_status
    assert _classify_status(95, None, True) == "RED"
    assert _classify_status(95, (50, 60), True) == "RED"


def test_classify_absolute_guardrails_override_relative():
    from tasks.scoring_tasks import _classify_status
    # Below floor → RED even if it would out-rank district peers.
    assert _classify_status(35, (10, 20), False) == "RED"
    # At/above ceiling → GREEN even if bottom of a high-performing district.
    assert _classify_status(78, (80, 85), False) == "GREEN"


def test_classify_relative_middle_uses_terciles():
    from tasks.scoring_tasks import _classify_status
    bands = (50.0, 60.0)  # yellow_cut, green_cut
    # A 55 is "good enough for a struggling district" → not RED.
    assert _classify_status(55, bands, False) == "YELLOW"
    assert _classify_status(65, bands, False) == "GREEN"
    assert _classify_status(48, bands, False) == "RED"


def test_district_thresholds_small_district_returns_none():
    from tasks.scoring_tasks import _district_thresholds
    # Fewer than MIN_DISTRICT_N (4) facilities → absolute fallback.
    assert _district_thresholds([60, 70]) is None


def test_district_thresholds_ranks_larger_district():
    from tasks.scoring_tasks import _district_thresholds
    bands = _district_thresholds([30, 40, 50, 60, 70, 80])
    assert bands is not None
    yellow_cut, green_cut = bands
    assert yellow_cut <= green_cut


# ── Seasonality + planning digest ─────────────────────────────────────────────

def test_seasonality_disease_calendar():
    from services.seasonality import disease_season_multiplier, combined_multiplier
    assert disease_season_multiplier("ORS", 7) > 1.0          # monsoon spike
    assert disease_season_multiplier("ANTIHYPERTENSIVE", 7) == 1.0  # chronic, flat
    # combined multiplier is clamped to a sane band even with extreme inputs
    assert 0.6 <= combined_multiplier("ORS", 7, 5.0, 3.0) <= 3.0


def test_planning_digest_runs_without_smtp():
    from tasks.planning_tasks import run_daily_planning_digest
    result = run_daily_planning_digest.apply().get()
    assert isinstance(result, dict)
    assert "recipients" in result and "sent" in result
