#!/usr/bin/env python3
"""
SmartHealth — Staff Attendance Seeder (Project Pulse Module 1/3 demo)

Seeds geofenced attendance history so the "zero attendance for N consecutive
days" escalation has something to fire on. Most facilities are present daily;
a small fraction go absent for the last N+ days (but have prior history, so the
escalation rule treats them as genuinely absent rather than never-onboarded).

Scope: facilities in a district (default MH-PUNE) — the active/scored demo set.
Idempotent: clears prior seeded (user_id IS NULL) attendance for the scope first.

Usage:
    python scripts/seed_attendance.py                    # Pune, 10 days history
    python scripts/seed_attendance.py --district MH-PUNE --days 10 --absent 0.08
Then trigger escalation:
    docker compose -f infrastructure/docker/docker-compose.yml exec -T celery-worker \\
        python -c "from tasks.scoring_tasks import run_attendance_escalation; \\
                   print(run_attendance_escalation.apply().result)"
"""

from __future__ import annotations

import argparse
import os
import random
from datetime import date, datetime, time, timedelta, timezone

import psycopg2
from psycopg2.extras import execute_values

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://smarthealth:smarthealth@localhost:5432/smarthealth",
).replace("postgresql+asyncpg://", "postgresql://")

ESCALATION_DAYS = int(os.environ.get("ATTENDANCE_ESCALATION_DAYS", "3"))


def seed(district_code: str, days: int, absent_frac: float) -> dict:
    conn = psycopg2.connect(DATABASE_URL)
    counts = {"facilities": 0, "present": 0, "absent": 0, "rows": 0}
    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT f.id FROM facilities f
                JOIN districts d ON d.id = f.district_id
                WHERE d.code = %s
                ORDER BY f.id
                """,
                (district_code,),
            )
            facility_ids = [str(r[0]) for r in cur.fetchall()]
            if not facility_ids:
                return counts

            # Idempotent: clear prior seeded (facility-level, user_id NULL) rows.
            cur.execute(
                """
                DELETE FROM staff_attendance
                WHERE user_id IS NULL AND facility_id = ANY(%s::uuid[])
                """,
                (facility_ids,),
            )

            today = date.today()
            rows: list[tuple] = []
            for fid in facility_ids:
                absent = random.random() < absent_frac
                if absent:
                    counts["absent"] += 1
                    # Present only up to (ESCALATION_DAYS + 1) days ago → recent gap.
                    day_range = range(days, ESCALATION_DAYS, -1)
                else:
                    counts["present"] += 1
                    day_range = range(days, -1, -1)  # includes today

                for d in day_range:
                    adate = today - timedelta(days=d)
                    check_in = datetime.combine(
                        adate, time(hour=9, minute=random.randint(0, 59)), tzinfo=timezone.utc
                    )
                    dist = round(random.uniform(8, 160), 1)   # within 200m geofence
                    rows.append((str(fid), adate, check_in, dist, True))

            execute_values(
                cur,
                """
                INSERT INTO staff_attendance
                    (facility_id, attendance_date, check_in_at, distance_m, within_geofence)
                VALUES %s
                """,
                rows,
                page_size=2000,
            )
            counts["facilities"] = len(facility_ids)
            counts["rows"] = len(rows)
    finally:
        conn.close()
    return counts


def main() -> None:
    p = argparse.ArgumentParser(description="Seed geofenced attendance for a district.")
    p.add_argument("--district", default="MH-PUNE", help="District code (default MH-PUNE).")
    p.add_argument("--days", type=int, default=10, help="Days of attendance history.")
    p.add_argument("--absent", type=float, default=0.08,
                   help="Fraction of facilities absent for the last N+ days.")
    args = p.parse_args()

    print(f"→ Seeding attendance for {args.district} ({args.days}d history, "
          f"{args.absent:.0%} absent) …")
    c = seed(args.district, args.days, args.absent)
    if c["facilities"] == 0:
        print(f"  No facilities found for district {args.district}.")
        return
    print(f"✓ {c['facilities']} facilities: {c['present']} present, "
          f"{c['absent']} absent (escalation candidates); {c['rows']} attendance rows.")
    print("  Next: trigger run_attendance_escalation (see docstring) to create alerts.")


if __name__ == "__main__":
    main()
