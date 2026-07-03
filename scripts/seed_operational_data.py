#!/usr/bin/env python3
"""
SmartHealth — Operational Data Seeder for real (PMGSY) facilities

The PMGSY ingestion (ingest_pmgsy_facilities.py) loads real facility master data
(name, type, coordinates) but NO operational data. Without stock + footfall, the
scorer can't score them and they render on the map without a health status.

This script backfills SYNTHETIC operational data for facilities that don't yet
have any — stock batches + 90 days of daily snapshots — mirroring the demo seed
(002_seed_demo.sql) so real facilities become "live" (scored) alongside the
curated demo 10. It is idempotent: facilities that already have snapshots (the
demo 10) are skipped, so their hand-crafted scenario is untouched.

Correlated randomness gives a realistic spread: ~12% of facilities are seeded
understaffed / low-stock / near-capacity so they surface as YELLOW/RED in the
bottom-5, the rest trend GREEN.

Usage
-----
    python scripts/seed_operational_data.py                 # only facilities missing data
    python scripts/seed_operational_data.py --days 60       # shorter history
    python scripts/seed_operational_data.py --all           # ALSO re-seed facilities that have data

After running, trigger scoring so the map lights up:
    docker compose -f infrastructure/docker/docker-compose.yml \\
        exec -T celery-worker python -c \\
        "from tasks.scoring_tasks import run_health_scores; print(run_health_scores.apply().result)"
"""

from __future__ import annotations

import argparse
import os
import random
from datetime import date, datetime, timedelta, timezone

import psycopg2
from psycopg2.extras import execute_values

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://smarthealth:smarthealth@localhost:5432/smarthealth",
).replace("postgresql+asyncpg://", "postgresql://")

# Fraction of facilities deliberately seeded in a degraded state (for demo spread).
DEGRADED_FRACTION = 0.12


def _target_facilities(cur, include_all: bool) -> list[tuple]:
    """Return (id, bed_capacity, facility_type) for facilities to seed."""
    if include_all:
        cur.execute("SELECT id, bed_capacity, facility_type FROM facilities ORDER BY id")
    else:
        # Only facilities with no daily_snapshots yet (the freshly ingested ones).
        cur.execute(
            """
            SELECT f.id, f.bed_capacity, f.facility_type
            FROM facilities f
            LEFT JOIN daily_snapshots ds ON ds.facility_id = f.id
            WHERE ds.facility_id IS NULL
            GROUP BY f.id, f.bed_capacity, f.facility_type
            ORDER BY f.id
            """
        )
    return cur.fetchall()


def _medicines(cur) -> list[tuple]:
    cur.execute("SELECT id, reorder_level FROM medicines WHERE is_active = TRUE")
    return cur.fetchall()


# Flush the DB every this many facilities to bound memory at national scale.
FACILITY_CHUNK = 1500


def _build_rows(chunk, medicines, days, today, now, counts):
    stock_rows: list[tuple] = []
    snap_rows: list[tuple] = []
    for fac_id, bed_capacity, ftype in chunk:
        bed_capacity = max(int(bed_capacity or 10), 1)
        degraded = random.random() < DEGRADED_FRACTION
        if degraded:
            counts["degraded"] += 1

        # ── Stock batches (one per medicine) ─────────────────────────────
        for med_id, reorder in medicines:
            reorder = int(reorder or 100)
            if degraded and random.random() < 0.6:
                qty = int(reorder * random.uniform(0.05, 0.5))   # below reorder
            else:
                qty = int(reorder * random.uniform(1.2, 3.5))    # healthy
            expiry = today + timedelta(days=random.randint(45, 330))
            stock_rows.append((str(fac_id), med_id, f"SEED-{med_id}", max(qty, 0), expiry))

        # ── Daily snapshots ──────────────────────────────────────────────
        rostered = 3 if ftype == "CHC" else 2
        base_footfall = 180 if ftype == "CHC" else 90
        for d in range(days, 0, -1):
            ts = now - timedelta(days=d)
            monsoon = random.randint(0, 40) if ts.month in (6, 7, 8, 9) else 0
            opd = max(0, base_footfall + random.randint(-30, 30) + monsoon)
            if degraded:
                present = random.choice([0, 1])
                occupied = int(bed_capacity * random.uniform(0.85, 1.0))
            else:
                present = rostered if random.random() > 0.15 else rostered - 1
                occupied = int(bed_capacity * random.uniform(0.1, 0.7))
            snap_rows.append(
                (ts, str(fac_id), opd, random.randint(0, 5),
                 random.randint(0, 3), occupied, present, rostered, "app")
            )
    return stock_rows, snap_rows


def seed(days: int, include_all: bool) -> dict:
    conn = psycopg2.connect(DATABASE_URL)
    counts = {"facilities": 0, "stock_batches": 0, "snapshots": 0, "degraded": 0}
    try:
        with conn.cursor() as cur:
            facilities = _target_facilities(cur, include_all)
            medicines = _medicines(cur)
        if not facilities:
            return counts

        today = date.today()
        now = datetime.now(timezone.utc)

        # Process in chunks, committing per chunk to bound memory at scale.
        for i in range(0, len(facilities), FACILITY_CHUNK):
            chunk = facilities[i:i + FACILITY_CHUNK]
            stock_rows, snap_rows = _build_rows(chunk, medicines, days, today, now, counts)
            with conn.cursor() as cur:
                if stock_rows:
                    execute_values(
                        cur,
                        """
                        INSERT INTO stock_batches
                            (facility_id, medicine_id, batch_number, quantity, expiry_date)
                        VALUES %s
                        """,
                        stock_rows, page_size=1000,
                    )
                if snap_rows:
                    execute_values(
                        cur,
                        """
                        INSERT INTO daily_snapshots
                            (time, facility_id, opd_count, ipd_count, emergency_count,
                             beds_occupied, doctors_present, doctors_rostered, input_channel)
                        VALUES %s
                        """,
                        snap_rows, page_size=1000,
                    )
            conn.commit()
            counts["stock_batches"] += len(stock_rows)
            counts["snapshots"] += len(snap_rows)
            counts["facilities"] += len(chunk)
            print(f"  … seeded {counts['facilities']}/{len(facilities)} facilities", flush=True)
    finally:
        conn.close()
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed operational data for real facilities.")
    parser.add_argument("--days", type=int, default=90, help="Days of snapshot history (default 90).")
    parser.add_argument("--all", action="store_true",
                        help="Also seed facilities that already have snapshots.")
    args = parser.parse_args()

    print(f"→ Seeding operational data (days={args.days}, all={args.all}) …")
    c = seed(args.days, args.all)
    if c["facilities"] == 0:
        print("  Nothing to do — all facilities already have operational data.")
        return
    print(f"✓ Seeded {c['facilities']} facilities "
          f"({c['degraded']} degraded for YELLOW/RED spread): "
          f"{c['stock_batches']} stock batches, {c['snapshots']} snapshots.")
    print("  Next: trigger run_health_scores to populate the map (see docstring).")


if __name__ == "__main__":
    main()
