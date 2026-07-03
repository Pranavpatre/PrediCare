#!/usr/bin/env python3
"""
SmartHealth — State Infrastructure Ingestion (data.gov.in)

Pulls REAL State/UT-level public-health bed capacity from the data.gov.in open
data API and upserts it into the `state_infrastructure` table.

Source resource: d133eac1-143f-4c1d-bdc4-b9dfd73ab78c
  "State/UT-wise Number of Beds at PHC, CHC, SDH, DH and Medical Colleges in
   India (Rural + Urban) as on 31-03-2023"

Note: this dataset is AGGREGATE (one row per State/UT — bed counts, not
individual facilities). It grounds the national/overview layer of the app; the
per-facility operational data remains in the demo seed.

Usage
-----
    # sample key (max 10 records) is baked in as a default
    python scripts/ingest_state_infrastructure.py

    # full pull with a personal key
    DATA_GOV_API_KEY=<your-key> python scripts/ingest_state_infrastructure.py

Env
---
    DATABASE_URL      Postgres DSN (default: local smarthealth)
    DATA_GOV_API_KEY  data.gov.in key (default: the public sample key)
"""

from __future__ import annotations

import os
import sys
import time
from datetime import date

import httpx
import psycopg2
from psycopg2.extras import RealDictCursor, execute_values

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://smarthealth:smarthealth@localhost:5432/smarthealth",
)
API_KEY = os.environ.get(
    "DATA_GOV_API_KEY",
    "579b464db66ec23bdd000001cdd3946e44ce4aad7209ff7b23ac571b",  # public sample key
)
BASE_URL = os.environ.get("DATA_GOV_BASE_URL", "https://api.data.gov.in/resource")
RESOURCE_ID = os.environ.get(
    "DATA_GOV_STATE_BEDS_RESOURCE_ID", "d133eac1-143f-4c1d-bdc4-b9dfd73ab78c"
)
# The dataset's reporting date, per its title ("as on 31-03-2023").
AS_ON_DATE = date(2023, 3, 31)

PAGE_SIZE = 100
MAX_RETRIES = 5          # data.gov.in intermittently returns 502/timeouts
RETRY_BACKOFF_SEC = 4


def _to_int(value) -> int | None:
    """data.gov.in reports missing numerics as the string 'NA'."""
    if value is None:
        return None
    s = str(value).strip()
    if s == "" or s.upper() == "NA":
        return None
    try:
        return int(float(s))
    except (ValueError, TypeError):
        return None


def _get_page(client: httpx.Client, url: str, offset: int) -> dict:
    """Fetch one page, retrying on transient errors (timeouts, 5xx, bad JSON).

    data.gov.in flaps — it intermittently answers 502 with an empty body — so a
    plain single request fails randomly. Retry with linear backoff.
    """
    last_err: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = client.get(
                url,
                params={
                    "api-key": API_KEY,
                    "format": "json",
                    "offset": offset,
                    "limit": PAGE_SIZE,
                },
            )
            # Retry server-side errors; surface client errors (bad key/resource) immediately.
            if resp.status_code >= 500:
                raise httpx.HTTPStatusError(
                    f"server error {resp.status_code}", request=resp.request, response=resp
                )
            resp.raise_for_status()
            return resp.json()
        except (httpx.HTTPError, ValueError) as exc:  # ValueError = JSON decode failure
            last_err = exc
            if attempt < MAX_RETRIES:
                wait = RETRY_BACKOFF_SEC * attempt
                print(
                    f"  … transient error ({type(exc).__name__}); "
                    f"retry {attempt}/{MAX_RETRIES - 1} in {wait}s",
                    file=sys.stderr,
                )
                time.sleep(wait)
    raise RuntimeError(f"data.gov.in unreachable after {MAX_RETRIES} attempts: {last_err}")


def fetch_all_records() -> list[dict]:
    """Page through the resource until every record is retrieved.

    With the public sample key the API caps each response at 10 records, so we
    stop once a page returns fewer than requested (or we reach `total`).
    """
    url = f"{BASE_URL}/{RESOURCE_ID}"
    records: list[dict] = []
    offset = 0
    with httpx.Client(timeout=60.0) as client:
        while True:
            payload = _get_page(client, url, offset)
            if payload.get("status") != "ok":
                raise RuntimeError(
                    f"data.gov.in returned non-ok status: {payload.get('message')}"
                )

            batch = payload.get("records", [])
            records.extend(batch)

            total = int(payload.get("total", 0))
            if not batch or len(records) >= total or len(batch) < PAGE_SIZE:
                break
            offset += len(batch)

    return records


def upsert(records: list[dict]) -> int:
    """Upsert records into state_infrastructure. Returns rows written."""
    rows = []
    for r in records:
        state = (r.get("state_ut") or "").strip()
        if not state:
            continue
        rows.append(
            (
                state,
                _to_int(r.get("phc")),
                _to_int(r.get("chc")),
                _to_int(r.get("sub_district__sub_divisional_hospital")),
                _to_int(r.get("district_hospital")),
                _to_int(r.get("medical_college")),
                _to_int(r.get("total_no__of_beds")),
                "data.gov.in",
                RESOURCE_ID,
                AS_ON_DATE,
            )
        )

    if not rows:
        return 0

    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    try:
        with conn, conn.cursor() as cur:
            execute_values(
                cur,
                """
                INSERT INTO state_infrastructure
                    (state_ut, phc_beds, chc_beds, sub_district_beds,
                     district_hospital_beds, medical_college_beds, total_beds,
                     source, source_resource_id, as_on_date)
                VALUES %s
                ON CONFLICT (state_ut) DO UPDATE SET
                    phc_beds               = EXCLUDED.phc_beds,
                    chc_beds               = EXCLUDED.chc_beds,
                    sub_district_beds      = EXCLUDED.sub_district_beds,
                    district_hospital_beds = EXCLUDED.district_hospital_beds,
                    medical_college_beds   = EXCLUDED.medical_college_beds,
                    total_beds             = EXCLUDED.total_beds,
                    source                 = EXCLUDED.source,
                    source_resource_id     = EXCLUDED.source_resource_id,
                    as_on_date             = EXCLUDED.as_on_date,
                    ingested_at            = NOW()
                """,
                rows,
            )
    finally:
        conn.close()

    return len(rows)


def main() -> None:
    print(f"→ Fetching state infrastructure from data.gov.in ({RESOURCE_ID}) …")
    is_sample = API_KEY == "579b464db66ec23bdd000001cdd3946e44ce4aad7209ff7b23ac571b"
    if is_sample:
        print("  ⚠ Using the public SAMPLE key — capped at 10 records.")
        print("    Set DATA_GOV_API_KEY=<your-key> for the full ~37-state pull.")

    try:
        records = fetch_all_records()
    except httpx.HTTPError as exc:
        print(f"✗ API request failed: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"  Retrieved {len(records)} record(s).")
    written = upsert(records)
    print(f"✓ Upserted {written} state/UT row(s) into state_infrastructure.")


if __name__ == "__main__":
    main()
