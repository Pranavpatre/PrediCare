"""Doctors router — per-facility doctor roster + daily per-doctor attendance.

Field workers maintain the doctor list for their PHC/CHC and mark each doctor
present/absent for the day. The admin dashboard reads the roster + today's
status. See data/schemas/010_doctors.sql.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any

import structlog
from fastapi import APIRouter, Depends, status
from pydantic import BaseModel
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

from auth.rbac import require_role
from db import get_db

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/doctors", tags=["doctors"])

_staff_plus = require_role(
    "FIELD_WORKER", "PHC_ADMIN", "HOSPITAL_STAFF", "DISTRICT_OFFICER", "STATE_ADMIN", "SUPERADMIN"
)


class DoctorRow(BaseModel):
    id: uuid.UUID
    name: str
    specialty: str | None = None
    present_today: bool = False


class NewDoctor(BaseModel):
    name: str
    specialty: str | None = None


class AttendanceMark(BaseModel):
    doctor_id: uuid.UUID
    present: bool


@router.get("/facility/{facility_id}", response_model=list[DoctorRow])
async def list_doctors(
    facility_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(_staff_plus),
) -> list[DoctorRow]:
    """Active doctors for a facility with each one's present/absent mark for today."""
    today = datetime.now(timezone.utc).date()
    rows = (
        await db.execute(
            sa_text(
                """
                SELECT d.id, d.name, d.specialty,
                       COALESCE(da.present, FALSE) AS present_today
                FROM doctors d
                LEFT JOIN doctor_attendance da
                       ON da.doctor_id = d.id AND da.attendance_date = :today
                WHERE d.facility_id = :fid AND d.is_active = TRUE
                ORDER BY d.name
                """
            ),
            {"fid": str(facility_id), "today": today},
        )
    ).mappings().all()
    return [
        DoctorRow(id=r["id"], name=r["name"], specialty=r["specialty"],
                  present_today=r["present_today"])
        for r in rows
    ]


@router.post("/facility/{facility_id}", response_model=DoctorRow, status_code=status.HTTP_201_CREATED)
async def add_doctor(
    facility_id: uuid.UUID,
    body: NewDoctor,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(_staff_plus),
) -> DoctorRow:
    row = (
        await db.execute(
            sa_text(
                """
                INSERT INTO doctors (facility_id, name, specialty)
                VALUES (:fid, :name, :spec)
                RETURNING id, name, specialty
                """
            ),
            {"fid": str(facility_id), "name": body.name.strip(), "spec": body.specialty},
        )
    ).mappings().first()
    log.info("doctor_added", facility_id=str(facility_id), name=body.name)
    return DoctorRow(id=row["id"], name=row["name"], specialty=row["specialty"], present_today=False)


@router.delete("/{doctor_id}")
async def remove_doctor(
    doctor_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(_staff_plus),
) -> dict:
    await db.execute(
        sa_text("UPDATE doctors SET is_active = FALSE WHERE id = :id"),
        {"id": str(doctor_id)},
    )
    return {"ok": True}


@router.put("/facility/{facility_id}/attendance", response_model=list[DoctorRow])
async def mark_attendance(
    facility_id: uuid.UUID,
    body: list[AttendanceMark],
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(_staff_plus),
) -> list[DoctorRow]:
    """Upsert today's present/absent for each doctor."""
    today = datetime.now(timezone.utc).date()
    for mark in body:
        await db.execute(
            sa_text(
                """
                INSERT INTO doctor_attendance (doctor_id, facility_id, attendance_date, present, marked_by)
                VALUES (:did, :fid, :today, :present, :uid)
                ON CONFLICT (doctor_id, attendance_date) DO UPDATE SET
                    present = EXCLUDED.present, marked_by = EXCLUDED.marked_by
                """
            ),
            {"did": str(mark.doctor_id), "fid": str(facility_id), "today": today,
             "present": mark.present, "uid": str(current_user.id)},
        )
    log.info("doctor_attendance_marked", facility_id=str(facility_id), count=len(body))
    return await list_doctors(facility_id, db, current_user)
