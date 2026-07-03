#!/usr/bin/env python3
"""
SmartHealth — Disease/Outbreak Event Seeder (Project Pulse Module 2)

Seeds the `disease_events` calendar with realistic SEASONAL outbreaks so the AI
demand-forecasting layer has an epidemiological signal to cross-reference.

The seasonality is real Indian epidemiology (monsoon Jun–Sep → vector/water-borne
diseases: malaria, dengue, chikungunya, cholera/diarrheal, typhoid; winter →
acute respiratory infection). The specific per-district events are simulated
(no public real-time IDSP feed exists).

Idempotent: clears prior seeded rows (source='seed') first.

Usage:
    python scripts/seed_disease_events.py           # season inferred from today
    python scripts/seed_disease_events.py --coverage 0.5
"""

from __future__ import annotations

import argparse
import os
from datetime import date, timedelta

import psycopg2

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://smarthealth:smarthealth@localhost:5432/smarthealth",
).replace("postgresql+asyncpg://", "postgresql://")

# month → seasonally-plausible diseases (with a severity bias).
MONSOON = ["Malaria", "Dengue", "Chikungunya", "Acute Diarrheal Disease", "Typhoid"]
WINTER = ["Acute Respiratory Infection", "Influenza"]
SUMMER = ["Measles", "Heat Exhaustion"]

SEVERITIES = ["low", "moderate", "high", "outbreak"]


def _season_diseases(month: int) -> list[str]:
    if month in (6, 7, 8, 9):
        return MONSOON
    if month in (11, 12, 1, 2):
        return WINTER
    return SUMMER


def seed(coverage: float) -> dict:
    today = date.today()
    diseases = _season_diseases(today.month)
    start = today - timedelta(days=10)
    end = today + timedelta(days=50)

    conn = psycopg2.connect(DATABASE_URL)
    counts = {"districts": 0, "events": 0}
    try:
        with conn, conn.cursor() as cur:
            # Only districts that actually have facilities.
            cur.execute(
                """
                SELECT DISTINCT d.id
                FROM districts d JOIN facilities f ON f.district_id = d.id
                ORDER BY d.id
                """
            )
            district_ids = [r[0] for r in cur.fetchall()]
            if not district_ids:
                return counts

            cur.execute("DELETE FROM disease_events WHERE source = 'seed'")

            rows = []
            for did in district_ids:
                # Deterministic per-district selection (~coverage fraction affected).
                if (did * 2654435761 % 1000) / 1000.0 > coverage:
                    continue
                counts["districts"] += 1
                # 1–2 diseases per affected district.
                n = 1 + (did % 2)
                for k in range(n):
                    disease = diseases[(did + k) % len(diseases)]
                    severity = SEVERITIES[(did + k) % len(SEVERITIES)]
                    rows.append((did, disease, start, end, severity))

            cur.executemany(
                """
                INSERT INTO disease_events
                    (district_id, disease_name, start_date, end_date, severity, source, notes)
                VALUES (%s, %s, %s, %s, %s, 'seed', 'Seasonal surveillance (simulated)')
                """,
                rows,
            )
            counts["events"] = len(rows)
    finally:
        conn.close()
    return counts


def main() -> None:
    p = argparse.ArgumentParser(description="Seed seasonal disease outbreak events.")
    p.add_argument("--coverage", type=float, default=0.45,
                   help="Fraction of districts with an active outbreak (default 0.45).")
    args = p.parse_args()

    today = date.today()
    season = ("monsoon" if today.month in (6, 7, 8, 9)
              else "winter" if today.month in (11, 12, 1, 2) else "summer")
    print(f"→ Seeding {season}-season disease events (coverage {args.coverage:.0%}) …")
    c = seed(args.coverage)
    print(f"✓ {c['events']} outbreak events across {c['districts']} districts "
          f"({', '.join(_season_diseases(today.month))}).")


if __name__ == "__main__":
    main()
