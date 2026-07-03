#!/usr/bin/env python3
"""
SmartHealth — PMGSY Facility Ingestion (real geo-tagged PHCs / CHCs)

Loads REAL individual Primary Health Centres and Community Health Centres from
the PMGSY Rural Facilities Dataset (Ministry of Rural Development, geo-tagged
2019-20) and upserts them into the `facilities` table with real coordinates.

Source (state-wise CSVs, no API key needed):
    https://github.com/pratapvardhan/rural-facilities-pmgsy
    raw: .../master/pmgsy_facilities_<state>.csv

CSV schema:
    State, District, Block, Habitation Name, Habitation ID, Facility Name,
    Address, File Upload Date, Facility Category, Facility Subcategory,
    Lattitude, Longitude

Notes / honest caveats
----------------------
* PMGSY has NO bed-capacity field → we apply IPHS norm defaults (PHC=6, CHC=30).
* Facility names are frequently generic ("PHC", "PHSC") → we build a readable
  display name from Block + type and keep the raw name in `address`.
* PMGSY has NO operational data (stock, footfall) → those remain synthetic
  (demo seed). This script ingests facility MASTER data only.
* Import is ADDITIVE and idempotent (ON CONFLICT by generated code). It does NOT
  delete the curated demo facilities, whose operational data drives the demo.

Usage
-----
    # default: Pune district PHC+CHC from Maharashtra
    python scripts/ingest_pmgsy_facilities.py

    # a different state / districts, or all districts in the state
    python scripts/ingest_pmgsy_facilities.py --state karnataka --districts ALL
    python scripts/ingest_pmgsy_facilities.py --districts "Pune,Satara" --limit 50

Env
---
    DATABASE_URL     Postgres DSN (default: local smarthealth)
    PMGSY_CACHE_DIR  where downloaded CSVs are cached (default: /tmp/pmgsy_cache)
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import os
import re
import sys
from pathlib import Path

import httpx
import psycopg2
from psycopg2.extras import execute_values

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://smarthealth:smarthealth@localhost:5432/smarthealth",
)
PMGSY_RAW_BASE = os.environ.get(
    "PMGSY_RAW_BASE",
    "https://raw.githubusercontent.com/pratapvardhan/rural-facilities-pmgsy/master",
)
CACHE_DIR = Path(os.environ.get("PMGSY_CACHE_DIR", "/tmp/pmgsy_cache"))

# PMGSY "Facility Subcategory" → our facility_type enum.
SUBCATEGORY_TO_TYPE = {
    "Primary Health Centre": "PHC",
    "Community Health Centre": "CHC",
}
# PMGSY carries no bed counts; apply Indian Public Health Standards norms.
DEFAULT_BED_CAPACITY = {"PHC": 6, "CHC": 30}

# India bounding box — reject rows with garbage coordinates.
LAT_RANGE = (6.0, 37.5)
LNG_RANGE = (68.0, 97.5)

# Names too generic to be useful as a label → fall back to "{Block} {type}".
GENERIC_NAMES = {
    "phc", "chc", "phsc", "sc", "phc sc", "phc building", "health center",
    "health centre", "govt primary health center", "primary health centre",
    "community health centre", "govt", "hospital", "dispensary",
}

# Two-letter state codes for the states table (VARCHAR(5)).
STATE_META = {
    "andhra_pradesh": ("AP", "Andhra Pradesh"),
    "arunachal_pradesh": ("AR", "Arunachal Pradesh"),
    "assam": ("AS", "Assam"),
    "bihar": ("BR", "Bihar"),
    "chhattisgarh": ("CG", "Chhattisgarh"),
    "gujarat": ("GJ", "Gujarat"),
    "haryana": ("HR", "Haryana"),
    "himachal_pradesh": ("HP", "Himachal Pradesh"),
    "jammu_and_kashmir": ("JK", "Jammu and Kashmir"),
    "jharkhand": ("JH", "Jharkhand"),
    "karnataka": ("KA", "Karnataka"),
    "kerala": ("KL", "Kerala"),
    "ladakh": ("LA", "Ladakh"),
    "madhya_pradesh": ("MP", "Madhya Pradesh"),
    "maharashtra": ("MH", "Maharashtra"),
    "manipur": ("MN", "Manipur"),
    "meghalaya": ("ML", "Meghalaya"),
    "mizoram": ("MZ", "Mizoram"),
    "nagaland": ("NL", "Nagaland"),
    "odisha": ("OD", "Odisha"),
    "pondicherry": ("PY", "Puducherry"),
    "punjab": ("PB", "Punjab"),
    "rajasthan": ("RJ", "Rajasthan"),
    "sikkim": ("SK", "Sikkim"),
    "tamilnadu": ("TN", "Tamil Nadu"),
    "telangana": ("TG", "Telangana"),
    "tripura": ("TR", "Tripura"),
    "uttar_pradesh": ("UP", "Uttar Pradesh"),
    "uttarakhand": ("UK", "Uttarakhand"),
    "west_bengal": ("WB", "West Bengal"),
}


# ── Fetch ────────────────────────────────────────────────────────────────────

def download_state_csv(state_slug: str) -> Path:
    """Download (and cache) the per-state PMGSY CSV."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / f"pmgsy_facilities_{state_slug}.csv"
    if path.exists() and path.stat().st_size > 0:
        print(f"  Using cached {path}")
        return path

    url = f"{PMGSY_RAW_BASE}/pmgsy_facilities_{state_slug}.csv"
    print(f"  Downloading {url} …")
    with httpx.stream("GET", url, timeout=120.0, follow_redirects=True) as resp:
        resp.raise_for_status()
        with open(path, "wb") as fh:
            for chunk in resp.iter_bytes():
                fh.write(chunk)
    print(f"  Saved {path.stat().st_size:,} bytes")
    return path


# ── Transform ──────────────────────────────────────────────────────────────

def _parse_coord(value: str) -> float | None:
    try:
        return float(str(value).strip())
    except (ValueError, TypeError):
        return None


def _display_name(raw: str, block: str, district: str, ftype: str) -> str:
    raw = (raw or "").strip()
    if raw.lower() in GENERIC_NAMES or len(raw) < 5:
        base = block.strip() or district.strip()
        name = f"{base} {ftype}".strip()
    else:
        name = raw
    return name[:200]


def _facility_code(state_code: str, ftype: str, district: str, block: str,
                   raw_name: str, lat: float, lng: float) -> str:
    """Deterministic, ≤20-char unique code (stable across re-runs)."""
    key = f"{state_code}|{district}|{block}|{raw_name}|{lat:.5f}|{lng:.5f}"
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:8]
    return f"{state_code}-{ftype}-{digest}"  # e.g. MH-PHC-a3f8e1c2 (15 chars)


def load_facilities(path: Path, state_code: str,
                    districts_filter: set[str] | None,
                    limit: int | None) -> list[dict]:
    """Parse the CSV → deduped list of facility dicts ready to upsert."""
    by_code: dict[str, dict] = {}
    skipped_coords = 0

    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if row.get("Facility Category", "").strip() != "Medical":
                continue
            ftype = SUBCATEGORY_TO_TYPE.get(row.get("Facility Subcategory", "").strip())
            if ftype is None:
                continue

            district = row.get("District", "").strip()
            if districts_filter and district.lower() not in districts_filter:
                continue

            lat = _parse_coord(row.get("Lattitude"))
            lng = _parse_coord(row.get("Longitude"))
            if (
                lat is None or lng is None
                or not (LAT_RANGE[0] <= lat <= LAT_RANGE[1])
                or not (LNG_RANGE[0] <= lng <= LNG_RANGE[1])
            ):
                skipped_coords += 1
                continue

            block = row.get("Block", "").strip()
            raw_name = row.get("Facility Name", "").strip()
            code = _facility_code(state_code, ftype, district, block, raw_name, lat, lng)

            # Dedup within the run (identical coords/name hash to same code).
            by_code[code] = {
                "code": code,
                "district": district,
                "name": _display_name(raw_name, block, district, ftype),
                "facility_type": ftype,
                "lat": lat,
                "lng": lng,
                "address": (row.get("Address") or block or "").strip()[:500] or None,
                "bed_capacity": DEFAULT_BED_CAPACITY[ftype],
            }

    facilities = list(by_code.values())

    # Disambiguate repeated display names (source names are often generic, so
    # many collapse to "{Block} {type}"). Number the 2nd+ occurrence.
    name_counts: dict[str, int] = {}
    for f in facilities:
        seen = name_counts.get(f["name"], 0) + 1
        name_counts[f["name"]] = seen
        if seen > 1:
            f["name"] = f"{f['name']} {seen}"[:200]

    if skipped_coords:
        print(f"  Skipped {skipped_coords} row(s) with missing/out-of-range coordinates.")
    if limit is not None:
        facilities = facilities[:limit]
    return facilities


# ── Load (DB) ────────────────────────────────────────────────────────────────

def _slug_upper(text: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", text.upper())


def ensure_state(cur, state_code: str, state_name: str) -> int:
    cur.execute(
        "INSERT INTO states (code, name) VALUES (%s, %s) "
        "ON CONFLICT (code) DO NOTHING",
        (state_code, state_name),
    )
    cur.execute("SELECT id FROM states WHERE code = %s", (state_code,))
    return cur.fetchone()[0]


def ensure_district(cur, state_id: int, state_code: str, district_name: str,
                    _seen: dict[str, int]) -> int:
    """Return district id, reusing an existing row (by name) or creating one
    with a unique ≤10-char code."""
    if district_name in _seen:
        return _seen[district_name]

    # Reuse an existing district with the same name in this state (e.g. seeded Pune).
    cur.execute(
        "SELECT id FROM districts WHERE state_id = %s AND lower(name) = lower(%s)",
        (state_id, district_name),
    )
    hit = cur.fetchone()
    if hit:
        _seen[district_name] = hit[0]
        return hit[0]

    # Generate a unique code that fits VARCHAR(10): "MH-" + up to 7 chars.
    base = f"{state_code}-{_slug_upper(district_name)[:7]}"[:10]
    code = base
    suffix = 1
    while True:
        cur.execute("SELECT 1 FROM districts WHERE code = %s", (code,))
        if not cur.fetchone():
            break
        tail = str(suffix)
        code = f"{base[:10 - len(tail)]}{tail}"
        suffix += 1

    cur.execute(
        "INSERT INTO districts (state_id, code, name) VALUES (%s, %s, %s) RETURNING id",
        (state_id, code, district_name),
    )
    did = cur.fetchone()[0]
    _seen[district_name] = did
    return did


def upsert_facilities(cur, facilities: list[dict], district_ids: dict[str, int]) -> int:
    rows = [
        (
            f["code"],
            district_ids[f["district"]],
            f["name"],
            f["facility_type"],
            f["lng"],  # ST_MakePoint(x=lng, y=lat)
            f["lat"],
            f["address"],
            f["bed_capacity"],
        )
        for f in facilities
    ]
    if not rows:
        return 0
    execute_values(
        cur,
        """
        INSERT INTO facilities
            (code, district_id, name, facility_type, location, address, bed_capacity)
        VALUES %s
        ON CONFLICT (code) DO UPDATE SET
            district_id  = EXCLUDED.district_id,
            name         = EXCLUDED.name,
            facility_type= EXCLUDED.facility_type,
            location     = EXCLUDED.location,
            address      = EXCLUDED.address,
            bed_capacity = EXCLUDED.bed_capacity
        """,
        rows,
        template="(%s,%s,%s,%s::facility_type,"
                 "ST_SetSRID(ST_MakePoint(%s,%s),4326),%s,%s)",
    )
    return len(rows)


# ── Orchestration ────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest PMGSY PHC/CHC facilities.")
    parser.add_argument("--state", default="maharashtra",
                        help="State slug (default: maharashtra). See STATE_META keys.")
    parser.add_argument("--districts", default="Pune",
                        help='Comma-separated district names, or "ALL" (default: Pune).')
    parser.add_argument("--limit", type=int, default=None,
                        help="Cap number of facilities imported (for testing).")
    parser.add_argument("--file", default=None,
                        help="Use a local CSV instead of downloading.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Parse + report only; do not write to the DB.")
    args = parser.parse_args()

    state_slug = args.state.strip().lower()
    if state_slug not in STATE_META:
        print(f"✗ Unknown state '{state_slug}'. Known: {', '.join(sorted(STATE_META))}",
              file=sys.stderr)
        sys.exit(2)
    state_code, state_name = STATE_META[state_slug]

    districts_filter: set[str] | None = None
    if args.districts.strip().upper() != "ALL":
        districts_filter = {d.strip().lower() for d in args.districts.split(",") if d.strip()}

    print(f"→ PMGSY ingestion: state={state_name} districts={args.districts}")

    # Fetch + parse
    try:
        path = Path(args.file) if args.file else download_state_csv(state_slug)
        facilities = load_facilities(path, state_code, districts_filter, args.limit)
    except httpx.HTTPError as exc:
        print(f"✗ Download failed: {exc}", file=sys.stderr)
        sys.exit(1)

    if not facilities:
        print("✗ No PHC/CHC facilities matched the filter.", file=sys.stderr)
        sys.exit(1)

    # Report
    n_phc = sum(1 for f in facilities if f["facility_type"] == "PHC")
    n_chc = sum(1 for f in facilities if f["facility_type"] == "CHC")
    n_districts = len({f["district"] for f in facilities})
    print(f"  Parsed {len(facilities)} facilities ({n_phc} PHC, {n_chc} CHC) "
          f"across {n_districts} district(s).")
    for f in facilities[:5]:
        print(f"    {f['code']}  {f['facility_type']}  {f['name'][:34]:34s} "
              f"({f['lat']:.4f},{f['lng']:.4f})  {f['district']}")

    if args.dry_run:
        print("✓ Dry run — no database writes performed.")
        return

    # Load
    conn = psycopg2.connect(DATABASE_URL)
    try:
        with conn, conn.cursor() as cur:
            state_id = ensure_state(cur, state_code, state_name)
            seen_districts: dict[str, int] = {}
            for name in sorted({f["district"] for f in facilities}):
                ensure_district(cur, state_id, state_code, name, seen_districts)
            written = upsert_facilities(cur, facilities, seen_districts)
    finally:
        conn.close()

    print(f"✓ Upserted {written} facilities into `facilities` "
          f"(additive; demo facilities untouched).")


if __name__ == "__main__":
    main()
