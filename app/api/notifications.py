"""
Notifications: list and mark read. JS parallel: REST resource routes.
"""
import logging
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import resolve_effective_user_id
from app.db.session import get_db
from app.db.models import Notification
from app.models.schemas import NotificationOut

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("", response_model=list[NotificationOut])
async def list_notifications(request: Request, db: AsyncSession = Depends(get_db)):
    uid = resolve_effective_user_id(request)
    result = await db.execute(
        select(Notification).where(Notification.user_id == uid).order_by(Notification.created_at.desc())
    )
    notifications = result.scalars().all()
    return [NotificationOut.model_validate(n) for n in notifications]


@router.patch("/{notification_id}/read")
async def mark_read(
    request: Request,
    notification_id: int,
    db: AsyncSession = Depends(get_db),
):
    uid = resolve_effective_user_id(request)
    result = await db.execute(
        select(Notification).where(
            and_(
                Notification.id == notification_id,
                Notification.user_id == uid,
            )
        )
    )
    notif = result.scalar_one_or_none()
    if not notif:
        raise HTTPException(status_code=404, detail="Notification not found")
    notif.read = True
    await db.flush()
    return {"ok": True}
