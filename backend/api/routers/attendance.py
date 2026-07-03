"""
attendance.py — Geofenced staff attendance (Project Pulse Module 1).

Endpoints
---------
POST /attendance/check-in    — record a geofenced check-in (lat/lng → distance)
POST /attendance/check-out   — close today's check-in
GET  /attendance/today       — current user's / facility's attendance for today
GET  /attendance/facility/{facility_id}  — recent attendance for a facility

Geofence: check-in GPS is compared to the facility's PostGIS location; if within
`settings.geofence_radius_m` metres the check-in counts as on-site (present).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

from auth.rbac import require_role
from config import get_settings
from db import get_db
from models.attendance import StaffAttendance
from models.facility import Facility

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/attendance")
settings = get_settings()

_staff_plus = require_role(
    "FIELD_WORKER", "PHC_ADMIN", "DISTRICT_OFFICER", "STATE_ADMIN", "SUPERADMIN"
)


class CheckInRequest(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lng: float = Field(..., ge=-180, le=180)
    # Field workers are bound to a facility via their user; allow override for admins/demo.
    facility_id: uuid.UUID | None = None


class AttendanceResponse(BaseModel):
    id: uuid.UUID
    facility_id: uuid.UUID
    attendance_date: date
    check_in_at: datetime
    check_out_at: datetime | None
    distance_m: float | None
    within_geofence: bool


async def _resolve_facility_id(body_facility_id, current_user) -> uuid.UUID:
    fid = current_user.facility_id or body_facility_id
    if fid is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No facility_id: user is not bound to a facility and none was provided.",
        )
    return fid


@router.post("/check-in", response_model=AttendanceResponse, status_code=status.HTTP_201_CREATED)
async def check_in(
    body: CheckInRequest,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(_staff_plus),
) -> AttendanceResponse:
    facility_id = await _resolve_facility_id(body.facility_id, current_user)

    # Distance (metres) from the check-in point to the facility, via geography cast.
    dist_row = (
        await db.execute(
            sa_text(
                """
                SELECT ST_Distance(
                    f.location::geography,
                    ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography
                ) AS distance_m
                FROM facilities f WHERE f.id = :fid
                """
            ),
            {"lng": body.lng, "lat": body.lat, "fid": str(facility_id)},
        )
    ).one_or_none()
    if dist_row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"Facility {facility_id} not found.")

    distance_m = float(dist_row.distance_m) if dist_row.distance_m is not None else None
    within = distance_m is not None and distance_m <= settings.geofence_radius_m
    today = datetime.now(timezone.utc).date()

    # Upsert today's row (re-check-in refreshes location/time).
    await db.execute(
        sa_text(
            """
            INSERT INTO staff_attendance
                (facility_id, user_id, attendance_date, check_in_at,
                 check_in_location, distance_m, within_geofence)
            VALUES
                (:fid, :uid, :adate, NOW(),
                 ST_SetSRID(ST_MakePoint(:lng, :lat), 4326), :dist, :within)
            ON CONFLICT (facility_id, user_id, attendance_date) DO UPDATE SET
                check_in_at       = NOW(),
                check_in_location = EXCLUDED.check_in_location,
                distance_m        = EXCLUDED.distance_m,
                within_geofence   = EXCLUDED.within_geofence
            """
        ),
        {
            "fid": str(facility_id),
            "uid": str(current_user.id),
            "adate": today,
            "lng": body.lng,
            "lat": body.lat,
            "dist": distance_m,
            "within": within,
        },
    )
    row = (
        await db.execute(
            select(StaffAttendance).where(
                StaffAttendance.facility_id == facility_id,
                StaffAttendance.user_id == current_user.id,
                StaffAttendance.attendance_date == today,
            )
        )
    ).scalar_one()

    log.info("attendance_check_in", facility_id=str(facility_id), user_id=str(current_user.id),
             distance_m=distance_m, within_geofence=within)
    return AttendanceResponse(
        id=row.id, facility_id=row.facility_id, attendance_date=row.attendance_date,
        check_in_at=row.check_in_at, check_out_at=row.check_out_at,
        distance_m=row.distance_m, within_geofence=row.within_geofence,
    )


@router.post("/check-out", response_model=AttendanceResponse)
async def check_out(
    body: CheckInRequest | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(_staff_plus),
) -> AttendanceResponse:
    facility_id = await _resolve_facility_id(body.facility_id if body else None, current_user)
    today = datetime.now(timezone.utc).date()
    row = (
        await db.execute(
            select(StaffAttendance).where(
                StaffAttendance.facility_id == facility_id,
                StaffAttendance.user_id == current_user.id,
                StaffAttendance.attendance_date == today,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No check-in found for today.")
    row.check_out_at = datetime.now(timezone.utc)
    await db.flush()
    return AttendanceResponse(
        id=row.id, facility_id=row.facility_id, attendance_date=row.attendance_date,
        check_in_at=row.check_in_at, check_out_at=row.check_out_at,
        distance_m=row.distance_m, within_geofence=row.within_geofence,
    )


@router.get("/today", response_model=AttendanceResponse | None)
async def today_status(
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(_staff_plus),
) -> AttendanceResponse | None:
    if current_user.facility_id is None:
        return None
    today = datetime.now(timezone.utc).date()
    row = (
        await db.execute(
            select(StaffAttendance).where(
                StaffAttendance.facility_id == current_user.facility_id,
                StaffAttendance.user_id == current_user.id,
                StaffAttendance.attendance_date == today,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    return AttendanceResponse(
        id=row.id, facility_id=row.facility_id, attendance_date=row.attendance_date,
        check_in_at=row.check_in_at, check_out_at=row.check_out_at,
        distance_m=row.distance_m, within_geofence=row.within_geofence,
    )


class FacilityAttendanceSummary(BaseModel):
    facility_id: uuid.UUID
    present_today: int          # distinct on-site check-ins today
    total_today: int            # all check-ins today (incl. outside geofence)
    days_since_last_present: int | None   # for absence escalation


@router.get("/facility/{facility_id}", response_model=FacilityAttendanceSummary)
async def facility_attendance(
    facility_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(_staff_plus),
) -> FacilityAttendanceSummary:
    today = datetime.now(timezone.utc).date()
    counts = (
        await db.execute(
            select(
                func.count().filter(StaffAttendance.within_geofence.is_(True)).label("present"),
                func.count().label("total"),
            ).where(
                StaffAttendance.facility_id == facility_id,
                StaffAttendance.attendance_date == today,
            )
        )
    ).one()
    last_present = (
        await db.execute(
            select(func.max(StaffAttendance.attendance_date)).where(
                StaffAttendance.facility_id == facility_id,
                StaffAttendance.within_geofence.is_(True),
            )
        )
    ).scalar_one_or_none()
    days_since = (today - last_present).days if last_present else None
    return FacilityAttendanceSummary(
        facility_id=facility_id,
        present_today=counts.present or 0,
        total_today=counts.total or 0,
        days_since_last_present=days_since,
    )
