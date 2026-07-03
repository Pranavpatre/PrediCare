#!/usr/bin/env python3
"""
SmartHealth — HMIS District Footfall Ingestion (real OPD, data.gov.in)

Pulls REAL district-level outpatient (OPD) attendance from the HMIS
"Item-wise HMIS report of <State>" resources and upserts it into
district_footfall. This grounds the (synthetic) per-facility footfall with
actual government district volumes.

Granularity: district, annual (latest HMIS year available per state, FY2011-12
to FY2018-19 depending on state). Parameter: "Allopathic- Outpatient attendance".

Usage:
    DATA_GOV_API_KEY=<key> python scripts/ingest_hmis_footfall.py
    python scripts/ingest_hmis_footfall.py --only "Uttar Pradesh,Maharashtra"
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.parse

import psycopg2
from psycopg2.extras import execute_values

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://smarthealth:smarthealth@localhost:5432/smarthealth",
).replace("postgresql+asyncpg://", "postgresql://")
API_KEY = os.environ.get(
    "DATA_GOV_API_KEY", "579b464db66ec23bdd0000018a8cd8224ea9422c499b573016bbceb4"
)
BASE_URL = "https://api.data.gov.in/resource"
# HMIS resources come in two schema generations — try both OPD parameter names
# and both annual-total field names.
OPD_PARAM_CANDIDATES = ["Allopathic- Outpatient attendance", "OPD attendance (All)"]
ANNUAL_FIELD_CANDIDATES = ["total___total___a_b__or__c_d__", "total"]

# State/UT → (HMIS reporting year, resource UUID). Harvested from the
# data.gov.in /lists search (latest year available per state).
STATE_RESOURCES: dict[str, tuple[str, str]] = {
    "Andhra Pradesh": ("2017-18", "fc014058-5074-4d21-9893-5878db745d4b"),
    "Arunachal Pradesh": ("2018-19", "df2d51ea-8fca-4581-bace-01fa78da65e6"),
    "Assam": ("2017-18", "acadd432-bdf8-4ea8-8c6e-78854df4bfd4"),
    "Bihar": ("2017-18", "be1bb3aa-567a-4a5c-860a-100cd89ca437"),
    "Chandigarh": ("2017-18", "251b0e3f-7384-4f1d-bb72-58c3afa5050a"),
    "Chhattisgarh": ("2011-12", "abffb8a8-ea16-441a-8a75-13f6fa54975b"),
    "Delhi": ("2011-12", "420f8317-6160-4388-afba-d1fd43efc6b4"),
    "Goa": ("2016-17", "8eddc589-3ebb-44ed-bfd2-ce37ebe3a08e"),
    "Gujarat": ("2016-17", "3ec5cf35-b9b7-437b-bf79-9917acc2310c"),
    "Haryana": ("2013-14", "bcb239fa-48a5-4c94-934d-dde200916598"),
    "Himachal Pradesh": ("2013-14", "2e1b227d-84ad-4c50-bd4c-01e905672a45"),
    "Jharkhand": ("2016-17", "88f2ecbe-d6ac-4d2b-aa7b-00aac47b4411"),
    "Karnataka": ("2018-19", "5d6f6798-a380-47aa-8e27-7b76f50fcd30"),
    "Kerala": ("2015-16", "8ab9e6f0-9f2e-4030-8d95-587a638f4f7c"),
    "Madhya Pradesh": ("2014-15", "9d8b6c98-b2b4-4d79-b8dd-a12ca17b1b92"),
    "Maharashtra": ("2016-17", "2a30b30d-4b97-42f6-8176-74c55e796ca5"),
    "Manipur": ("2017-18", "2e865802-c7e2-4d2b-a5b7-059627dd4cb1"),
    "Meghalaya": ("2012-13", "579240c4-98c2-4822-bb6f-b0d9a6a01103"),
    "Mizoram": ("2016-17", "7d93f848-36c5-4256-9ae2-4e1e6541519d"),
    "Nagaland": ("2018-19", "9ffead32-979a-46ef-8b40-8b3cc8397867"),
    "Odisha": ("2018-19", "5165bdca-372d-42d2-ae8c-04717dfe4bee"),
    "Puducherry": ("2016-17", "572f109b-84a0-4754-97d5-106dc053923a"),
    "Punjab": ("2016-17", "2a7b555c-7c96-4f7e-b874-9cdfdf5204f2"),
    "Rajasthan": ("2017-18", "6d9d4536-ca11-48ee-bf6f-890387edc544"),
    "Sikkim": ("2016-17", "3ca1a2ac-1e52-498f-956e-e1937646cc99"),
    "Tamil Nadu": ("2016-17", "a5e16550-b983-4378-a842-57909884f70b"),
    "Tripura": ("2018-19", "5df10bcb-8391-4696-aed3-2e8540eba6dd"),
    "Uttar Pradesh": ("2016-17", "9e4ebc58-d61e-466f-8b0c-2aee6dbb1c83"),
    "Uttarakhand": ("2012-13", "77e31c6c-d5b4-488c-a1e4-0a4e88a73f89"),
    "West Bengal": ("2017-18", "f83b63d8-4b5f-47b0-9835-5c0b01f4bfd4"),
}


def _to_int(v) -> int | None:
    if v is None:
        return None
    s = str(v).strip()
    if s == "" or s.upper() == "NA":
        return None
    try:
        return int(float(s))
    except (ValueError, TypeError):
        return None


def _curl_json(url: str) -> dict:
    """GET JSON via curl (far more reliable than httpx vs data.gov.in's flaky API)."""
    proc = subprocess.run(
        ["curl", "-s", "-g", "--retry", "6", "--retry-all-errors",
         "--retry-delay", "3", "--max-time", "40", url],
        capture_output=True, text=True,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        raise RuntimeError(f"curl failed (rc={proc.returncode})")
    return json.loads(proc.stdout)


def _detect(resource_id: str) -> tuple[str | None, str | None]:
    """Return (opd_param, annual_field) for a resource by inspecting its schema
    (field ids) and probing the OPD parameter candidates."""
    meta = _curl_json(f"{BASE_URL}/{resource_id}?api-key={API_KEY}&format=json&limit=1")
    field_ids = {f["id"] for f in meta.get("field", [])}
    annual = next((f for f in ANNUAL_FIELD_CANDIDATES if f in field_ids), None)

    opd_param = None
    for cand in OPD_PARAM_CANDIDATES:
        enc = urllib.parse.quote(cand)
        probe = _curl_json(
            f"{BASE_URL}/{resource_id}?api-key={API_KEY}&format=json&limit=1"
            f"&filters%5Bparameters%5D={enc}"
        )
        if int(probe.get("total", 0)) > 0:
            opd_param = cand
            break
    return opd_param, annual


def fetch_state_opd(resource_id: str) -> list[tuple[str, int]]:
    """Return [(district, opd_annual)] for a state, auto-detecting schema.
    Dedupes by district (keeps the max annual value)."""
    opd_param, annual = _detect(resource_id)
    if not opd_param or not annual:
        return []

    by_district: dict[str, int] = {}
    offset = 0
    enc = urllib.parse.quote(opd_param)
    while True:
        url = (
            f"{BASE_URL}/{resource_id}?api-key={API_KEY}&format=json"
            f"&offset={offset}&limit=100&filters%5Bparameters%5D={enc}"
        )
        payload = _curl_json(url)
        batch = payload.get("records", [])
        for rec in batch:
            district = (rec.get("district") or "").strip()
            if not district or district.lower() in ("total", "grand total", "state total"):
                continue
            opd = _to_int(rec.get(annual))
            if opd is None:
                continue
            by_district[district] = max(by_district.get(district, 0), opd)
        total = int(payload.get("total", 0))
        if not batch or offset + len(batch) >= total or len(batch) < 100:
            break
        offset += len(batch)
    return list(by_district.items())


def main() -> None:
    p = argparse.ArgumentParser(description="Ingest real HMIS district OPD footfall.")
    p.add_argument("--only", default=None, help="Comma-separated state names to limit ingestion.")
    args = p.parse_args()

    states = STATE_RESOURCES
    if args.only:
        want = {s.strip().lower() for s in args.only.split(",")}
        states = {k: v for k, v in STATE_RESOURCES.items() if k.lower() in want}

    print(f"→ Ingesting HMIS district OPD for {len(states)} state(s) …", flush=True)
    conn = psycopg2.connect(DATABASE_URL)
    total_written = 0
    try:
        if True:
            for state, (period, rid) in states.items():
                # Skip states already ingested (resumable across kills).
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT count(*) FROM district_footfall WHERE state_ut=%s AND period=%s",
                        (state, period),
                    )
                    if cur.fetchone()[0] > 0:
                        print(f"  {state} ({period}): already ingested — skip", flush=True)
                        continue
                try:
                    pairs = fetch_state_opd(rid)
                except Exception as exc:
                    print(f"  ✗ {state}: fetch failed ({exc})", file=sys.stderr, flush=True)
                    continue
                rows = [
                    (state, district, period, opd, opd // 12, rid)
                    for (district, opd) in pairs
                ]
                if rows:
                    with conn, conn.cursor() as cur:
                        execute_values(
                            cur,
                            """
                            INSERT INTO district_footfall
                                (state_ut, district, period, opd_annual, opd_monthly_avg, resource_id)
                            VALUES %s
                            ON CONFLICT (state_ut, district, period) DO UPDATE SET
                                opd_annual      = EXCLUDED.opd_annual,
                                opd_monthly_avg = EXCLUDED.opd_monthly_avg,
                                resource_id     = EXCLUDED.resource_id,
                                ingested_at     = NOW()
                            """,
                            rows, page_size=1000,
                        )
                    total_written += len(rows)
                print(f"  {state} ({period}): {len(rows)} districts", flush=True)
    finally:
        conn.close()
    print(f"✓ Upserted {total_written} district-footfall rows from HMIS.")


if __name__ == "__main__":
    main()
