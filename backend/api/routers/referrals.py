"""Digital patient referral — PHC/CHC creates, doctor retrieves.

See docs/PRD-digital-referral.md. Two-tier consent:
  Tier 1 (referral directed to this facility / any DH / national user) → no
          patient credential needed; the referral IS the consent.
  Tier 2 (record held at another facility / walk-in) → patient phone+OTP.
Every view is written to referral_access_log.
"""
from __future__ import annotations

import secrets
import string
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from auth.jwt import get_current_user
from auth.rbac import require_role
from config import get_settings
from db import get_db
from models.facility import Facility
from models.referral import Patient, Referral, ReferralAccessLog, VisitNote
from models.user import User

log = structlog.get_logger()
router = APIRouter(prefix="/referrals", tags=["referrals"])

_phc_plus = require_role("FIELD_WORKER")          # PHC/CHC staff (and above) create
_hospital = require_role("HOSPITAL_STAFF")        # doctor / DH staff retrieve

# In-memory patient OTP store (phone -> (otp, expiry)). Mirrors auth/router.py;
# fine for a single instance / demo. Move to Redis for multi-instance prod.
_otp_store: dict[str, tuple[str, datetime]] = {}

_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no ambiguous 0/O/1/I


# ─────────────────────────── schemas ───────────────────────────
class PatientIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    phone: str = Field(..., min_length=5, max_length=15)
    sex: Optional[str] = None
    year_of_birth: Optional[int] = None


class ReferralCreate(BaseModel):
    patient: PatientIn
    reason: Optional[str] = None
    clinical_summary: Optional[dict[str, Any]] = None
    to_facility_id: Optional[str] = None  # None = any district hospital


class VisitNoteIn(BaseModel):
    diagnosis: Optional[str] = None
    action: Optional[str] = None
    follow_up: Optional[str] = None
    notes: Optional[str] = None


class OTPRequestIn(BaseModel):
    phone: str


class OTPVerifyIn(BaseModel):
    phone: str
    otp: str


# ─────────────────────────── helpers ───────────────────────────
def _norm_phone(p: str) -> str:
    return p.strip().replace(" ", "")


async def _gen_code(db: AsyncSession) -> str:
    for _ in range(10):
        code = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(6))
        exists = await db.scalar(select(Referral.id).where(Referral.code == code))
        if not exists:
            return code
    raise HTTPException(500, "Could not allocate a referral code")


def _tier(referral: Referral, user: User) -> int:
    """1 = allowed without patient credential; 2 = needs OTP/break-glass."""
    if user.role in ("STATE_ADMIN", "SUPERADMIN"):
        return 1
    if referral.to_facility_id is None:  # "any district hospital"
        return 1
    if user.facility_id and referral.to_facility_id == user.facility_id:
        return 1
    return 2


async def _log_access(db, referral_id, user_id: str, method: str, tier: int, reason: str | None = None):
    db.add(ReferralAccessLog(
        referral_id=referral_id, accessed_by=str(user_id), method=method, tier=tier, reason=reason,
    ))


async def _facility_name(db, fid) -> Optional[str]:
    if not fid:
        return None
    return await db.scalar(select(Facility.name).where(Facility.id == fid))


async def _serialize(db, r: Referral, *, full: bool) -> dict:
    p = r.patient
    out: dict[str, Any] = {
        "id": str(r.id),
        "code": r.code,
        "status": r.status,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "expires_at": r.expires_at.isoformat() if r.expires_at else None,
        "reason": r.reason,
        "from_facility": await _facility_name(db, r.from_facility_id),
        "to_facility": await _facility_name(db, r.to_facility_id),
        "patient": {
            "id": str(p.id), "name": p.name, "phone": p.phone,
            "sex": p.sex, "year_of_birth": p.year_of_birth,
        },
        "consent_required": not full,
    }
    if full:
        out["clinical_summary"] = r.clinical_summary or {}
        notes = (await db.execute(
            select(VisitNote).where(VisitNote.referral_id == r.id).order_by(VisitNote.created_at)
        )).scalars().all()
        out["visit_notes"] = [
            {"id": str(n.id), "note": n.note, "created_at": n.created_at.isoformat() if n.created_at else None,
             "facility": await _facility_name(db, n.facility_id)}
            for n in notes
        ]
    return out


def _deliver_whatsapp(phone: str, patient_name: str, to_name: str | None, code: str) -> bool:
    """Best-effort WhatsApp send. Returns False if not configured / fails."""
    try:
        from integrations.whatsapp import WhatsAppClient
        settings = get_settings()
        if not settings.whatsapp_token or not settings.whatsapp_phone_number_id:
            return False
        dest = to_name or "the district hospital"
        body = (
            f"Namaste {patient_name}, you have been referred to {dest}.\n"
            f"Show this referral code at the hospital: {code}\n"
            f"(PrediCare digital referral)"
        )
        WhatsAppClient()._send_text(phone=phone, body=body)
        return True
    except Exception as exc:  # noqa: BLE001 — delivery is best-effort
        log.warning("referral_whatsapp_failed", error=str(exc))
        return False


# ─────────────────────────── create (PHC/CHC) ───────────────────────────
@router.post("", status_code=status.HTTP_201_CREATED)
@router.post("/", status_code=status.HTTP_201_CREATED, include_in_schema=False)
async def create_referral(
    body: ReferralCreate,
    current_user: User = Depends(_phc_plus),
    db: AsyncSession = Depends(get_db),
):
    if not current_user.facility_id:
        raise HTTPException(400, "Your account is not linked to a facility; cannot originate a referral.")

    phone = _norm_phone(body.patient.phone)
    # Upsert patient by phone
    patient = (await db.execute(select(Patient).where(Patient.phone == phone))).scalar_one_or_none()
    if patient is None:
        patient = Patient(
            phone=phone, name=body.patient.name.strip(),
            sex=body.patient.sex, year_of_birth=body.patient.year_of_birth,
        )
        db.add(patient)
        await db.flush()

    code = await _gen_code(db)
    referral = Referral(
        patient_id=patient.id,
        from_facility_id=current_user.facility_id,
        to_facility_id=body.to_facility_id or None,
        code=code,
        reason=body.reason,
        clinical_summary=body.clinical_summary,
        status="CREATED",
        created_by=current_user.id,
        expires_at=datetime.now(timezone.utc) + timedelta(days=30),
    )
    db.add(referral)
    await db.flush()

    to_name = await _facility_name(db, referral.to_facility_id)
    sent = _deliver_whatsapp(phone, patient.name, to_name, code)
    if sent:
        referral.status = "DELIVERED"
        referral.delivered_at = datetime.now(timezone.utc)
    await db.commit()

    return {
        "id": str(referral.id),
        "code": code,
        "retrieve_path": f"/referrals?code={code}",   # frontend builds the QR from origin + this
        "whatsapp_delivered": sent,
        "patient": {"name": patient.name, "phone": phone},
        "to_facility": to_name,
        "expires_at": referral.expires_at.isoformat(),
    }


@router.post("/{referral_id}/deliver")
async def resend_delivery(
    referral_id: str,
    current_user: User = Depends(_phc_plus),
    db: AsyncSession = Depends(get_db),
):
    r = (await db.execute(select(Referral).options(selectinload(Referral.patient)).where(Referral.id == referral_id))).scalar_one_or_none()
    if not r:
        raise HTTPException(404, "Referral not found")
    to_name = await _facility_name(db, r.to_facility_id)
    sent = _deliver_whatsapp(r.patient.phone, r.patient.name, to_name, r.code)
    if sent and r.status == "CREATED":
        r.status, r.delivered_at = "DELIVERED", datetime.now(timezone.utc)
        await db.commit()
    return {"whatsapp_delivered": sent, "code": r.code, "retrieve_path": f"/referrals?code={r.code}"}


# ─────────────────────────── retrieve (doctor) ───────────────────────────
@router.get("/search")
async def search_referrals(
    q: str | None = None,
    phone: str | None = None,
    current_user: User = Depends(_hospital),
    db: AsyncSession = Depends(get_db),
):
    """Search referrals directed to the doctor's facility (Tier 1). National
    roles (no facility) see all. Returns summaries; open one for detail."""
    if not q and not phone:
        raise HTTPException(400, "Provide a name (q) or phone to search.")
    stmt = select(Referral).options(selectinload(Referral.patient)).join(Patient, Patient.id == Referral.patient_id)
    national = current_user.role in ("STATE_ADMIN", "SUPERADMIN")
    if not national:
        if not current_user.facility_id:
            raise HTTPException(400, "Your account is not linked to a facility.")
        stmt = stmt.where(or_(
            Referral.to_facility_id == current_user.facility_id,
            Referral.to_facility_id.is_(None),
        ))
    if q:
        stmt = stmt.where(Patient.name.ilike(f"%{q.strip()}%"))
    if phone:
        stmt = stmt.where(Patient.phone == _norm_phone(phone))
    stmt = stmt.order_by(Referral.created_at.desc()).limit(50)
    rows = (await db.execute(stmt)).scalars().all()
    return {"count": len(rows), "results": [await _serialize(db, r, full=False) for r in rows]}


@router.get("/by-code/{code}")
async def get_by_code(
    code: str,
    reason: str | None = None,  # break-glass justification for Tier-2 without OTP
    current_user: User = Depends(_hospital),
    db: AsyncSession = Depends(get_db),
):
    r = (await db.execute(select(Referral).options(selectinload(Referral.patient)).where(Referral.code == code.strip().upper()))).scalar_one_or_none()
    if not r:
        raise HTTPException(404, "No referral for that code")
    tier = _tier(r, current_user)
    if tier == 2 and not reason:
        # Needs patient OTP consent or a break-glass reason. Return a stub.
        await _log_access(db, r.id, current_user.id, "CODE", tier=2)
        await db.commit()
        return {**await _serialize(db, r, full=False),
                "consent_required": True,
                "message": "This referral is held at another facility. Use patient phone+OTP consent, or pass a break-glass reason."}
    await _log_access(db, r.id, current_user.id, "CODE", tier=tier, reason=reason)
    if r.status == "DELIVERED" or r.status == "CREATED":
        r.status, r.viewed_at = "VIEWED", datetime.now(timezone.utc)
    await db.commit()
    return await _serialize(db, r, full=True)


@router.post("/lookup/otp/request")
async def otp_request(
    body: OTPRequestIn,
    current_user: User = Depends(_hospital),
    db: AsyncSession = Depends(get_db),
):
    phone = _norm_phone(body.phone)
    settings = get_settings()
    otp = f"{secrets.randbelow(1_000_000):06d}"
    _otp_store[phone] = (otp, datetime.now(timezone.utc) + timedelta(minutes=10))
    # Best-effort WhatsApp to the patient; graceful in non-prod (log the OTP).
    try:
        from integrations.whatsapp import WhatsAppClient
        if settings.whatsapp_token and settings.whatsapp_phone_number_id:
            WhatsAppClient()._send_text(phone=phone, body=f"Your PrediCare record-access OTP is {otp}. Valid 10 minutes.")
    except Exception as exc:  # noqa: BLE001
        log.warning("referral_otp_whatsapp_failed", error=str(exc))
    if not settings.is_production:
        log.info("referral_otp_generated", phone=phone, otp=otp, dev_otp=settings.dev_login_otp)
    return {"message": "If the patient exists, an OTP has been sent to their phone."}


@router.post("/lookup/otp/verify")
async def otp_verify(
    body: OTPVerifyIn,
    current_user: User = Depends(_hospital),
    db: AsyncSession = Depends(get_db),
):
    phone = _norm_phone(body.phone)
    settings = get_settings()
    dev_bypass = (not settings.is_production) and body.otp == settings.dev_login_otp
    if not dev_bypass:
        stored = _otp_store.get(phone)
        if not stored or stored[1] < datetime.now(timezone.utc) or body.otp != stored[0]:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired OTP")
        _otp_store.pop(phone, None)
    # Consent granted → return the patient's full referral history (Tier 2 unlocked)
    patient = (await db.execute(select(Patient).where(Patient.phone == phone))).scalar_one_or_none()
    if not patient:
        return {"count": 0, "results": []}
    rows = (await db.execute(
        select(Referral).options(selectinload(Referral.patient)).where(Referral.patient_id == patient.id).order_by(Referral.created_at.desc())
    )).scalars().all()
    for r in rows:
        await _log_access(db, r.id, current_user.id, "OTP", tier=2)
    await db.commit()
    return {"count": len(rows), "results": [await _serialize(db, r, full=True) for r in rows]}


@router.post("/{referral_id}/visit-note", status_code=status.HTTP_201_CREATED)
async def add_visit_note(
    referral_id: str,
    body: VisitNoteIn,
    current_user: User = Depends(_hospital),
    db: AsyncSession = Depends(get_db),
):
    r = (await db.execute(select(Referral).where(Referral.id == referral_id))).scalar_one_or_none()
    if not r:
        raise HTTPException(404, "Referral not found")
    note = {k: v for k, v in body.model_dump().items() if v}
    if not note:
        raise HTTPException(400, "Empty note")
    db.add(VisitNote(referral_id=r.id, facility_id=current_user.facility_id, author_id=current_user.id, note=note))
    r.status, r.completed_at = "COMPLETED", datetime.now(timezone.utc)
    await _log_access(db, r.id, current_user.id, "SEARCH", tier=_tier(r, current_user))
    await db.commit()
    return {"ok": True}
