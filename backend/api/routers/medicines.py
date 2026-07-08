"""
Medicines router — reference list of active medicines.

Endpoints:
  GET /medicines   list of active medicines, for field-app offline caching
    (stock entry needs the full catalogue on-device before it can work offline)
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel
from fastapi import APIRouter, Depends
from sqlalchemy import select, text as sa_text
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


class StockRow(BaseModel):
    medicine_id: int
    name: str
    category: str
    unit: str
    reorder_level: int          # the level used for status (dynamic when available)
    current_stock: int
    status: str                 # OK | WATCH | LOW
    demand_based: bool = False  # True when reorder came from the demand model
    required_stock: int | None = None      # target on-hand at worst-case demand
    expected_daily_demand: float | None = None


@router.get("/stock/{facility_id}", response_model=list[StockRow])
async def facility_stock(
    facility_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(_staff_plus),
) -> list[StockRow]:
    """Per-medicine current stock for one facility (non-expired batches summed),
    with a LOW/WATCH/OK status vs the reorder level. Powers the admin Stock view
    and the field-app stock table. LOW = below reorder, WATCH = below 1.5×.

    The reorder level is the facility's DEMAND-DERIVED dynamic level
    (facility_medicine_requirements, computed weekly by run_demand_model from
    local footfall) when a profile exists, falling back to the medicine's global
    reorder_level otherwise."""
    rows = (
        await db.execute(
            sa_text(
                """
                SELECT m.id AS medicine_id, m.name, m.category, m.unit,
                       m.reorder_level AS global_reorder,
                       fmr.dynamic_reorder_level,
                       fmr.required_stock,
                       fmr.expected_daily_demand,
                       COALESCE(SUM(sb.quantity) FILTER (
                           WHERE sb.expiry_date > CURRENT_DATE), 0) AS current_stock
                FROM medicines m
                LEFT JOIN stock_batches sb
                       ON sb.medicine_id = m.id AND sb.facility_id = :fid
                LEFT JOIN facility_medicine_requirements fmr
                       ON fmr.medicine_id = m.id AND fmr.facility_id = :fid
                WHERE m.is_active = TRUE
                GROUP BY m.id, m.name, m.category, m.unit, m.reorder_level,
                         fmr.dynamic_reorder_level, fmr.required_stock,
                         fmr.expected_daily_demand
                ORDER BY m.category, m.name
                """
            ),
            {"fid": str(facility_id)},
        )
    ).mappings().all()

    out: list[StockRow] = []
    for r in rows:
        stock = int(r["current_stock"] or 0)
        demand_based = r["dynamic_reorder_level"] is not None
        reorder = int(
            r["dynamic_reorder_level"] if demand_based else (r["global_reorder"] or 0)
        )
        if reorder > 0 and stock < reorder:
            status = "LOW"
        elif reorder > 0 and stock < reorder * 1.5:
            status = "WATCH"
        else:
            status = "OK"
        out.append(StockRow(
            medicine_id=r["medicine_id"], name=r["name"], category=r["category"],
            unit=r["unit"], reorder_level=reorder, current_stock=stock, status=status,
            demand_based=demand_based,
            required_stock=int(r["required_stock"]) if r["required_stock"] is not None else None,
            expected_daily_demand=(
                float(r["expected_daily_demand"])
                if r["expected_daily_demand"] is not None else None
            ),
        ))
    return out
