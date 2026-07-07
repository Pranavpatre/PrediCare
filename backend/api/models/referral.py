"""Digital patient-referral models (PHC/CHC → District Hospital).

See docs/PRD-digital-referral.md. A minimal, additive patient record plus the
referral that travels to the patient's phone and is retrieved by an
authenticated doctor. Records are retained indefinitely; only the share window
(referrals.expires_at) lapses.
"""
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String, Text, func, Integer
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db import Base


class Patient(Base):
    __tablename__ = "patients"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    phone: Mapped[str] = mapped_column(String(15), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    sex: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    year_of_birth: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    abha_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)  # ABDM linkage, later
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    referrals: Mapped[list["Referral"]] = relationship(back_populates="patient")


class Referral(Base):
    __tablename__ = "referrals"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patients.id"), nullable=False, index=True)
    from_facility_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("facilities.id"), nullable=False)
    to_facility_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("facilities.id"), nullable=True, index=True
    )  # NULL = "any district hospital"
    code: Mapped[str] = mapped_column(String(20), nullable=False, unique=True, index=True)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    clinical_summary: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    # CREATED | DELIVERED | VIEWED | COMPLETED | EXPIRED
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="CREATED")
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    viewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    patient: Mapped["Patient"] = relationship(back_populates="referrals")
    visit_notes: Mapped[list["VisitNote"]] = relationship(back_populates="referral")


class ReferralAccessLog(Base):
    """Consent / audit trail — one row per view of a referral (DPDP §6)."""
    __tablename__ = "referral_access_log"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    referral_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("referrals.id"), nullable=False, index=True)
    accessed_by: Mapped[str] = mapped_column(String(64), nullable=False)  # user uuid or 'system'
    method: Mapped[str] = mapped_column(String(16), nullable=False)  # SEARCH | CODE | QR | OTP
    tier: Mapped[int] = mapped_column(Integer, nullable=False, default=1)  # 1=referral-consent, 2=OTP/break-glass
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # break-glass justification
    accessed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class VisitNote(Base):
    """Outcome appended by the receiving facility — the 'floating history'."""
    __tablename__ = "visit_notes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    referral_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("referrals.id"), nullable=False, index=True)
    facility_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("facilities.id"), nullable=True)
    author_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id"), nullable=True)
    note: Mapped[dict] = mapped_column(JSONB, nullable=False)  # {diagnosis, action, follow_up, notes}
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    referral: Mapped["Referral"] = relationship(back_populates="visit_notes")
