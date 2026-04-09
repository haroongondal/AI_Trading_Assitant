"""
Portfolio CRUD. JS parallel: REST resource routes like Express router.get/post/delete.
"""
import logging
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select, and_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import resolve_effective_user_id
from app.core.config import settings
from app.db.session import get_db
from app.db.models import User, PortfolioPosition
from app.models.schemas import (
    PortfolioPositionCreate,
    PortfolioPositionOut,
    PortfolioOut,
    PortfolioGoalUpdate,
    PortfolioPositionUpdate,
)
from app.tools.symbol_normalize import normalize_trading_symbol

logger = logging.getLogger(__name__)
router = APIRouter()


async def _ensure_user(db: AsyncSession, uid: str) -> User:
    result = await db.execute(select(User).where(User.id == uid))
    user = result.scalar_one_or_none()
    if not user:
        user = User(id=uid, name="Demo User" if uid == settings.DEFAULT_USER_ID else "User")
        db.add(user)
        try:
            await db.flush()
        except IntegrityError:
            await db.rollback()
            result = await db.execute(select(User).where(User.id == uid))
            user = result.scalar_one_or_none()
            if not user:
                raise
    return user


@router.get("", response_model=PortfolioOut)
async def list_portfolio(request: Request, db: AsyncSession = Depends(get_db)):
    uid = resolve_effective_user_id(request)
    user = await _ensure_user(db, uid)
    result = await db.execute(select(PortfolioPosition).where(PortfolioPosition.user_id == uid))
    positions = result.scalars().all()
    return PortfolioOut(
        positions=[PortfolioPositionOut.model_validate(p) for p in positions],
        total_positions=len(positions),
        goal=user.portfolio_goal,
    )


@router.post("", response_model=PortfolioPositionOut)
async def create_position(
    request: Request,
    body: PortfolioPositionCreate,
    db: AsyncSession = Depends(get_db),
):
    uid = resolve_effective_user_id(request)
    await _ensure_user(db, uid)
    entry = body.entry_price if body.entry_price is not None else 0.0
    pos = PortfolioPosition(
        user_id=uid,
        symbol=normalize_trading_symbol(body.symbol),
        quantity=body.quantity,
        entry_price=entry,
        notes=body.notes,
    )
    db.add(pos)
    await db.flush()
    await db.refresh(pos)
    return PortfolioPositionOut.model_validate(pos)


@router.get("/goal")
async def get_portfolio_goal(request: Request, db: AsyncSession = Depends(get_db)):
    uid = resolve_effective_user_id(request)
    user = await _ensure_user(db, uid)
    return {"goal": user.portfolio_goal}


@router.patch("/goal", response_model=dict)
async def update_portfolio_goal(
    request: Request,
    body: PortfolioGoalUpdate,
    db: AsyncSession = Depends(get_db),
):
    uid = resolve_effective_user_id(request)
    user = await _ensure_user(db, uid)
    user.portfolio_goal = body.goal
    await db.flush()
    return {"goal": user.portfolio_goal}


@router.delete("/{position_id}")
async def delete_position(
    request: Request,
    position_id: int,
    db: AsyncSession = Depends(get_db),
):
    uid = resolve_effective_user_id(request)
    result = await db.execute(
        select(PortfolioPosition).where(
            and_(
                PortfolioPosition.id == position_id,
                PortfolioPosition.user_id == uid,
            )
        )
    )
    pos = result.scalar_one_or_none()
    if not pos:
        raise HTTPException(status_code=404, detail="Position not found")
    await db.delete(pos)
    return {"ok": True}


@router.patch("/{position_id}", response_model=PortfolioPositionOut)
async def edit_position(
    request: Request,
    position_id: int,
    body: PortfolioPositionUpdate,
    db: AsyncSession = Depends(get_db),
):
    if body.quantity is None and body.entry_price is None and body.notes is None:
        raise HTTPException(status_code=400, detail="Provide quantity, entry_price, or notes")
    uid = resolve_effective_user_id(request)
    result = await db.execute(
        select(PortfolioPosition).where(
            and_(
                PortfolioPosition.id == position_id,
                PortfolioPosition.user_id == uid,
            )
        )
    )
    pos = result.scalar_one_or_none()
    if not pos:
        raise HTTPException(status_code=404, detail="Position not found")
    if body.quantity is not None:
        pos.quantity = body.quantity
    if body.entry_price is not None:
        pos.entry_price = body.entry_price
    if body.notes is not None:
        pos.notes = body.notes.strip() or None
    await db.flush()
    await db.refresh(pos)
    return PortfolioPositionOut.model_validate(pos)
