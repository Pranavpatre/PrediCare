"""
planning.py — pre-emptive district/state stock & capacity planning.

Replaces the reactive "redistribution" view with a forward-looking actionables
list: which facilities will run short of medicines/tests within the planning
horizon (default 14 days), how much to order, and by when — so the admin can
forward a delivery list to suppliers *before* the stockout. Demand is scaled by
the seasonal model (services/seasonality.py: disease calendar + district
footfall history + live weather) so seasonal spikes are anticipated.

Endpoints (prefix /planning):
  GET /planning/refills          → JSON actionables (medicines + tests)
  GET /planning/refills.csv      → same list as a downloadable CSV (with addresses)
  GET /planning/capacity         → long-term concerns (beds / doctors)
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

from auth.rbac import require_role
from db import get_db
from services import seasonality
from services.planning_core import build_refill_items, refills_to_csv

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/planning")

_field_plus = require_role(
    "FIELD_WORKER", "PHC_ADMIN", "DISTRICT_OFFICER", "STATE_ADMIN", "SUPERADMIN"
)

HORIZON_DAYS = 14  # plan at least two weeks ahead
SCOPED_ROLES = ("FIELD_WORKER", "PHC_ADMIN", "HOSPITAL_STAFF", "DISTRICT_OFFICER")


# ─────────────────────────────────────────────────────────────────────────────
# Scope resolution
# ─────────────────────────────────────────────────────────────────────────────

def _resolve_scope(current_user, state_id: int | None, district_id: int | None):
    """Return (where_sql, params). Scoped roles are pinned to their own district;
    higher roles must pass a district or state (planning is not run nationwide in
    one shot). Raises 400 if a privileged user gives no scope."""
    where: list[str] = []
    params: dict[str, Any] = {}
    udid = getattr(current_user, "district_id", None)
    if current_user.role in SCOPED_ROLES and udid is not None:
        where.append("f.district_id = :did")
        params["did"] = udid
    elif district_id is not None:
        where.append("f.district_id = :did")
        params["did"] = district_id
    elif state_id is not None:
        where.append("d.state_id = :sid")
        params["sid"] = state_id
    else:
        raise HTTPException(
            status_code=400,
            detail="Select a district or state to generate a planning list.",
        )
    return (" AND ".join(where), params)


async def _historical_index(db: AsyncSession, where_sql: str, params: dict, month: int) -> float:
    """District footfall seasonality: target-month avg footfall ÷ annual avg over
    the last 2 years for the facilities in scope. 1.0 when there's no history."""
    row = (
        await db.execute(
            sa_text(
                f"""
                SELECT
                    AVG((ds.opd_count + ds.ipd_count))
                        FILTER (WHERE EXTRACT(MONTH FROM ds.time) = :m) AS m_avg,
                    AVG((ds.opd_count + ds.ipd_count)) AS all_avg
                FROM daily_snapshots ds
                JOIN facilities f ON f.id = ds.facility_id
                JOIN districts d ON d.id = f.district_id
                WHERE ds.time >= NOW() - INTERVAL '2 years' AND {where_sql}
                """
            ),
            {**params, "m": month},
        )
    ).mappings().first()
    if not row or not row["all_avg"] or float(row["all_avg"]) == 0 or row["m_avg"] is None:
        return 1.0
    return round(float(row["m_avg"]) / float(row["all_avg"]), 3)


# ─────────────────────────────────────────────────────────────────────────────
# Refill computation (shared by JSON + CSV)
# ─────────────────────────────────────────────────────────────────────────────

async def _compute_refills(
    db: AsyncSession, where_sql: str, params: dict, horizon: int
) -> list[dict]:
    """Facilities in scope projected to fall below their (seasonally-adjusted)
    demand-derived target within `horizon` days. One row per facility×medicine."""
    target_month = (datetime.now(timezone.utc).date() + timedelta(days=horizon)).month
    hist = await _historical_index(db, where_sql, params, target_month)

    rows = (
        await db.execute(
            sa_text(
                f"""
                SELECT f.id AS fid, f.name, f.code, f.address, d.name AS district,
                       ST_Y(f.location) AS lat, ST_X(f.location) AS lng,
                       m.name AS item, m.category AS cat, m.unit,
                       GREATEST(m.lead_time_days, 1) AS lead,
                       fmr.expected_daily_demand AS edd,
                       fmr.required_stock AS req,
                       COALESCE(SUM(sb.quantity) FILTER (
                           WHERE sb.expiry_date > CURRENT_DATE), 0) AS stock
                FROM facility_medicine_requirements fmr
                JOIN facilities f ON f.id = fmr.facility_id
                JOIN districts d ON d.id = f.district_id
                JOIN medicines m ON m.id = fmr.medicine_id AND m.is_active = TRUE
                LEFT JOIN stock_batches sb
                       ON sb.facility_id = f.id AND sb.medicine_id = m.id
                WHERE {where_sql} AND fmr.expected_daily_demand > 0
                GROUP BY f.id, f.name, f.code, f.address, d.name, f.location,
                         m.name, m.category, m.unit, m.lead_time_days,
                         fmr.expected_daily_demand, fmr.required_stock
                HAVING COALESCE(SUM(sb.quantity) FILTER (
                           WHERE sb.expiry_date > CURRENT_DATE), 0)
                       < fmr.required_stock * 2
                """
            ),
            params,
        )
    ).mappings().all()

    # One best-effort weather call for the scope (first facility with coords).
    weather = {"rain": 1.0, "heat": 1.0}
    for r in rows:
        if r["lat"] is not None and r["lng"] is not None:
            weather = seasonality.fetch_weather_factor(float(r["lat"]), float(r["lng"]))
            break

    today = datetime.now(timezone.utc).date()
    return build_refill_items(rows, target_month, hist, weather, today, horizon)


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────────────────

class RefillItem(BaseModel):
    facility_id: str
    facility: str
    code: str
    address: str
    district: str
    item: str
    category: str
    unit: str
    current_stock: int
    required: int
    order_qty: int
    days_of_cover: float
    deliver_by: str
    urgency: str
    seasonal_multiplier: float


class RefillResponse(BaseModel):
    generated_at: str
    horizon_days: int
    target_month: int
    items: list[RefillItem]


@router.get("/refills", response_model=RefillResponse)
async def planning_refills(
    state_id: int | None = Query(None),
    district_id: int | None = Query(None),
    horizon_days: int = Query(HORIZON_DAYS, ge=7, le=60),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(_field_plus),
) -> RefillResponse:
    where_sql, params = _resolve_scope(current_user, state_id, district_id)
    items = await _compute_refills(db, where_sql, params, horizon_days)
    now = datetime.now(timezone.utc)
    return RefillResponse(
        generated_at=now.isoformat(),
        horizon_days=horizon_days,
        target_month=(now.date() + timedelta(days=horizon_days)).month,
        items=[RefillItem(**i) for i in items],
    )


@router.get("/refills.csv")
async def planning_refills_csv(
    state_id: int | None = Query(None),
    district_id: int | None = Query(None),
    horizon_days: int = Query(HORIZON_DAYS, ge=7, le=60),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(_field_plus),
) -> Response:
    where_sql, params = _resolve_scope(current_user, state_id, district_id)
    items = await _compute_refills(db, where_sql, params, horizon_days)
    fname = f"planning_refills_{date.today().isoformat()}.csv"
    return Response(
        content=refills_to_csv(items),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


class CapacityItem(BaseModel):
    facility_id: str
    facility: str
    code: str
    address: str
    district: str
    concern: str      # BEDS | DOCTORS
    detail: str
    metric: str


@router.get("/capacity", response_model=list[CapacityItem])
async def planning_capacity(
    state_id: int | None = Query(None),
    district_id: int | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(_field_plus),
) -> list[CapacityItem]:
    """Long-term structural concerns: facilities running near bed capacity or
    understaffed relative to their patient load. These aren't 'order more stock'
    fixes — they're beds/doctors asks for the district plan."""
    where_sql, params = _resolve_scope(current_user, state_id, district_id)
    rows = (
        await db.execute(
            sa_text(
                f"""
                WITH doc_ct AS (
                    SELECT facility_id, count(*) AS n FROM doctors GROUP BY facility_id
                )
                SELECT f.id AS fid, f.name, f.code, f.address, d.name AS district,
                       f.bed_capacity, snap.beds_occupied, snap.opd_count,
                       COALESCE(dc.n, 0) AS doctors
                FROM facilities f
                JOIN districts d ON d.id = f.district_id
                LEFT JOIN mv_facility_latest_snapshot snap ON snap.facility_id = f.id
                LEFT JOIN doc_ct dc ON dc.facility_id = f.id
                WHERE {where_sql}
                """
            ),
            params,
        )
    ).mappings().all()

    out: list[CapacityItem] = []
    for r in rows:
        cap = int(r["bed_capacity"] or 0)
        occ = int(r["beds_occupied"] or 0)
        opd = int(r["opd_count"] or 0)
        docs = int(r["doctors"] or 0)
        base = {
            "facility_id": str(r["fid"]), "facility": r["name"], "code": r["code"],
            "address": r["address"] or "", "district": r["district"],
        }
        if cap > 0 and occ / cap >= 0.85:
            out.append(CapacityItem(**base, concern="BEDS",
                detail=f"Bed occupancy at {round(occ / cap * 100)}% — consider adding beds.",
                metric=f"{occ}/{cap} beds"))
        # ~50 OPD patients/doctor/day is a rough MoHFW-style load ceiling.
        needed = math.ceil(opd / 50) if opd > 0 else 0
        if needed > docs:
            out.append(CapacityItem(**base, concern="DOCTORS",
                detail=f"~{opd} daily patients need ≈{needed} doctors; {docs} on roster.",
                metric=f"{docs} doctors / {opd} OPD"))
    return out
