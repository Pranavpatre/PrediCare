"""
Notifications router — delivery log for the current user, for the field-app
notifications tab (in-app fallback view of what was sent via WhatsApp/SMS).

Endpoints:
  GET /notifications   current user's notifications, newest first
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth.jwt import get_current_user
from db import get_db
from models.alert import Notification

router = APIRouter(prefix="/notifications", tags=["notifications"])


class NotificationOut(BaseModel):
    id: str
    channel: str
    body: str
    template_key: Optional[str] = None
    template_params: Optional[dict] = None
    created_at: str
    read: bool = False


@router.get("", response_model=list[NotificationOut])
async def list_notifications(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
) -> list[NotificationOut]:
    result = await db.execute(
        select(Notification)
        .where(Notification.user_id == current_user.id)
        .order_by(Notification.sent_at.desc())
        .limit(100)
    )
    return [
        NotificationOut(
            id=str(n.id),
            # Raw channel key ("whatsapp"/"sms"/"push"/"in_app") — the client
            # translates this via i18n so the label follows the UI language
            # the worker has picked, instead of a fixed English string baked
            # in here.
            channel=n.channel if n.channel in ("whatsapp", "sms", "push", "in_app") else "in_app",
            body=n.message,
            # template_key/template_params (when present) let the client
            # re-render the body via i18n too, so it also follows the UI
            # language live instead of staying frozen in whatever language
            # it was sent in. `body` remains the fallback for older rows.
            template_key=n.template_key,
            template_params=n.template_params,
            created_at=(n.sent_at or n.response_at).isoformat() if (n.sent_at or n.response_at) else "",
        )
        for n in result.scalars().all()
    ]
