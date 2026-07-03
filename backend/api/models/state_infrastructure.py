from datetime import date, datetime
from typing import Optional

from sqlalchemy import Date, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from db import Base


class StateInfrastructure(Base):
    """Real state/UT-level public-health bed capacity from data.gov.in.

    Aggregate figures (bed counts per state), NOT individual facilities.
    Ingested by scripts/ingest_state_infrastructure.py. Grounds the national
    overview layer alongside the per-facility operational (synthetic) data.
    """

    __tablename__ = "state_infrastructure"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    state_ut: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)

    # Bed counts — NULL where the source reports "NA".
    phc_beds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    chc_beds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    sub_district_beds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    district_hospital_beds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    medical_college_beds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    total_beds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    source: Mapped[str] = mapped_column(String(50), nullable=False, default="data.gov.in")
    source_resource_id: Mapped[str] = mapped_column(String(64), nullable=False)
    as_on_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
