"""
Pure refill-projection math shared by the planning API (async, SQLAlchemy) and
the daily digest task (sync, psycopg2). Keeping the seasonal-adjustment / order-
quantity / urgency logic here means both paths behave identically even though
they fetch their rows through different DB drivers.
"""

from __future__ import annotations

import csv
import io
import math
from datetime import date, timedelta

from services import seasonality


def build_refill_items(
    rows,
    target_month: int,
    hist_index: float,
    weather: dict[str, float],
    today: date,
    horizon: int,
) -> list[dict]:
    """Transform raw facility×medicine rows into ordered refill actionables.

    Each row must expose: fid, name, code, address, district, item, cat, unit,
    lead, edd (baseline expected daily demand), req (baseline target stock),
    stock (current on-hand). Returns only items that will dip below their
    seasonally-adjusted target within `horizon + lead` days, HIGH→LOW ordered.
    """
    out: list[dict] = []
    for r in rows:
        cat = r["cat"]
        wf = seasonality.category_weather_factor(cat, weather)
        mult = seasonality.combined_multiplier(cat, target_month, hist_index, wf)
        edd = float(r["edd"]) * mult
        if edd <= 0:
            continue
        stock = int(r["stock"] or 0)
        target = math.ceil(float(r["req"]) * mult)
        order_qty = target - stock
        days_cover = stock / edd
        lead = int(r["lead"])
        if order_qty <= 0 or days_cover > horizon + lead:
            continue
        if days_cover < lead:
            urgency = "HIGH"
        elif days_cover < horizon:
            urgency = "MEDIUM"
        else:
            urgency = "LOW"
        deliver_by = today + timedelta(days=max(1, int(days_cover) - 2))
        out.append({
            "facility_id": str(r["fid"]),
            "facility": r["name"],
            "code": r["code"],
            "address": r["address"] or "",
            "district": r["district"],
            "item": r["item"],
            "category": cat,
            "unit": r["unit"],
            "current_stock": stock,
            "required": target,
            "order_qty": order_qty,
            "days_of_cover": round(days_cover, 1),
            "deliver_by": deliver_by.isoformat(),
            "urgency": urgency,
            "seasonal_multiplier": mult,
        })
    order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    out.sort(key=lambda x: (order[x["urgency"]], x["days_of_cover"]))
    return out


def refills_to_csv(items: list[dict]) -> str:
    """Supplier-ready CSV (includes facility addresses) of a refill list."""
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([
        "District", "Facility", "Code", "Address", "Item", "Category",
        "Unit", "Current Stock", "Order Qty", "Deliver By", "Urgency",
    ])
    for i in items:
        w.writerow([
            i["district"], i["facility"], i["code"], i["address"], i["item"],
            i["category"], i["unit"], i["current_stock"], i["order_qty"],
            i["deliver_by"], i["urgency"],
        ])
    return buf.getvalue()
