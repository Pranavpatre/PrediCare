"""
Medicines router — reference list of active medicines.

Endpoints:
  GET /medicines   list of active medicines, for field-app offline caching
    (stock entry needs the full catalogue on-device before it can work offline)
"""

from __future__ import annotations

from pydantic import BaseModel
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth.rbac import require_role
from db import get_db
from models.inventory import Medicine

router = APIRouter(prefix="/medicines", tags=["medicines"])

_staff_plus = require_role(
    "FIELD_WORKER", "PHC_ADMIN", "DISTRICT_OFFICER", "STATE_ADMIN", "SUPERADMIN"
)


class MedicineOut(BaseModel):
    id: int
    name: str
    reorder_level: int
    unit: str
    category: str


@router.get("", response_model=list[MedicineOut])
async def list_medicines(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(_staff_plus),
) -> list[MedicineOut]:
    result = await db.execute(
        select(Medicine.id, Medicine.name, Medicine.reorder_level, Medicine.unit, Medicine.category)
        .where(Medicine.is_active.is_(True))
        .order_by(Medicine.category, Medicine.name)
    )
    return [
        MedicineOut(id=r.id, name=r.name, reorder_level=r.reorder_level, unit=r.unit, category=r.category)
        for r in result.all()
    ]
