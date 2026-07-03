"""
overview.py — National / state-level context layer.

Serves REAL public-health infrastructure data ingested from data.gov.in
(state_infrastructure table). This is aggregate State/UT bed capacity — it
grounds the dashboard's national context, distinct from the per-facility
operational data.

Endpoints
---------
GET /overview/state-infrastructure          — all States/UTs, real bed capacity
GET /overview/state-infrastructure/{state}  — single State/UT
GET /overview/national-summary              — rolled-up national totals
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from auth.rbac import require_role
from db import get_db
from models.state_infrastructure import StateInfrastructure

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/overview")

# The source dataset carries an "All India/Total" roll-up row. Exclude it from
# aggregations and lists so it isn't double-counted or shown as a "state".
_AGGREGATE_ROW = StateInfrastructure.state_ut.ilike("all india%")

# Public-health context data is non-sensitive; any authenticated user may read.
_any_user = require_role(
    "FIELD_WORKER", "PHC_ADMIN", "DISTRICT_OFFICER", "STATE_ADMIN", "SUPERADMIN"
)


class StateInfrastructureResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    state_ut: str
    phc_beds: int | None
    chc_beds: int | None
    sub_district_beds: int | None
    district_hospital_beds: int | None
    medical_college_beds: int | None
    total_beds: int | None
    source: str
    as_on_date: date | None
    ingested_at: datetime


class NationalSummaryResponse(BaseModel):
    states_reported: int
    phc_beds: int
    chc_beds: int
    sub_district_beds: int
    district_hospital_beds: int
    medical_college_beds: int
    total_beds: int
    source: str = "data.gov.in"
    as_on_date: date | None = None


@router.get(
    "/state-infrastructure",
    response_model=list[StateInfrastructureResponse],
    summary="Real state/UT bed capacity (data.gov.in)",
)
async def list_state_infrastructure(
    order_by_total: bool = Query(True, description="Sort by total_beds desc when true"),
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(_any_user),
) -> list[StateInfrastructure]:
    stmt = select(StateInfrastructure).where(~_AGGREGATE_ROW)
    if order_by_total:
        stmt = stmt.order_by(StateInfrastructure.total_beds.desc().nullslast())
    else:
        stmt = stmt.order_by(StateInfrastructure.state_ut.asc())
    rows = (await db.execute(stmt)).scalars().all()
    log.info("state_infrastructure_listed", count=len(rows), user_id=str(current_user.id))
    return list(rows)


@router.get(
    "/national-summary",
    response_model=NationalSummaryResponse,
    summary="Rolled-up national bed totals",
)
async def national_summary(
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(_any_user),
) -> NationalSummaryResponse:
    stmt = select(
        func.count(StateInfrastructure.id),
        func.coalesce(func.sum(StateInfrastructure.phc_beds), 0),
        func.coalesce(func.sum(StateInfrastructure.chc_beds), 0),
        func.coalesce(func.sum(StateInfrastructure.sub_district_beds), 0),
        func.coalesce(func.sum(StateInfrastructure.district_hospital_beds), 0),
        func.coalesce(func.sum(StateInfrastructure.medical_college_beds), 0),
        func.coalesce(func.sum(StateInfrastructure.total_beds), 0),
        func.max(StateInfrastructure.as_on_date),
    ).where(~_AGGREGATE_ROW)
    row = (await db.execute(stmt)).one()
    return NationalSummaryResponse(
        states_reported=row[0] or 0,
        phc_beds=row[1],
        chc_beds=row[2],
        sub_district_beds=row[3],
        district_hospital_beds=row[4],
        medical_college_beds=row[5],
        total_beds=row[6],
        as_on_date=row[7],
    )


@router.get(
    "/state-infrastructure/{state_ut}",
    response_model=StateInfrastructureResponse,
    summary="Single state/UT bed capacity",
)
async def get_state_infrastructure(
    state_ut: str,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(_any_user),
) -> StateInfrastructure:
    # Case-insensitive exact match on state name.
    stmt = select(StateInfrastructure).where(
        func.lower(StateInfrastructure.state_ut) == state_ut.strip().lower()
    )
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No infrastructure data for State/UT '{state_ut}'.",
        )
    return row
