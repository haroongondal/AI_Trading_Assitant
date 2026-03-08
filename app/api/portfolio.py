"""
Portfolio CRUD. JS parallel: REST resource routes like Express router.get/post/delete.
"""
import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, and_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import get_db
from app.db.models import User, PortfolioPosition
from app.models.schemas import PortfolioPositionCreate, PortfolioPositionOut, PortfolioOut

logger = logging.getLogger(__name__)
router = APIRouter()


async def _ensure_user(db: AsyncSession) -> User:
    uid = settings.DEFAULT_USER_ID
    result = await db.execute(select(User).where(User.id == uid))
    user = result.scalar_one_or_none()
    if not user:
        user = User(id=uid, name="Demo User")
        db.add(user)
        try:
            await db.flush()
        except IntegrityError:
            # User was created by another request/session (e.g. scheduler); re-query
            await db.rollback()
            result = await db.execute(select(User).where(User.id == uid))
            user = result.scalar_one_or_none()
            if not user:
                raise
    return user


@router.get("", response_model=PortfolioOut)
async def list_portfolio(db: AsyncSession = Depends(get_db)):
    await _ensure_user(db)
    result = await db.execute(
        select(PortfolioPosition).where(PortfolioPosition.user_id == settings.DEFAULT_USER_ID)
    )
    positions = result.scalars().all()
    return PortfolioOut(
        positions=[PortfolioPositionOut.model_validate(p) for p in positions],
        total_positions=len(positions),
    )


@router.post("", response_model=PortfolioPositionOut)
async def create_position(
    body: PortfolioPositionCreate,
    db: AsyncSession = Depends(get_db),
):
    await _ensure_user(db)
    pos = PortfolioPosition(
        user_id=settings.DEFAULT_USER_ID,
        symbol=body.symbol.upper(),
        quantity=body.quantity,
        entry_price=body.entry_price,
        notes=body.notes,
    )
    db.add(pos)
    await db.flush()
    await db.refresh(pos)
    return PortfolioPositionOut.model_validate(pos)


@router.delete("/{position_id}")
async def delete_position(
    position_id: int,
  db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(PortfolioPosition).where(
            and_(
                PortfolioPosition.id == position_id,
                PortfolioPosition.user_id == settings.DEFAULT_USER_ID,
            )
        )
    )
    pos = result.scalar_one_or_none()
    if not pos:
        raise HTTPException(status_code=404, detail="Position not found")
    await db.delete(pos)
    return {"ok": True}
