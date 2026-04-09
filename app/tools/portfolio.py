"""
Portfolio tools: read and mutate user portfolio so the agent can analyze and update it from chat.
"""
from langchain_core.tools import tool
from sqlalchemy import select, and_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth_context import get_effective_user_id
from app.core.config import settings
from app.db.models import User, PortfolioPosition
from app.tools.symbol_normalize import normalize_trading_symbol


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


async def _get_portfolio_summary(user_id: str, db: AsyncSession) -> str:
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    goal = user.portfolio_goal if user else None
    result = await db.execute(select(PortfolioPosition).where(PortfolioPosition.user_id == user_id))
    positions = result.scalars().all()
    lines = []
    if goal:
        lines.append(f"User's stated goal: {goal}")
    if not positions:
        lines.append("The user has no portfolio positions.")
    else:
        for p in positions:
            lines.append(f"- id={p.id} {p.symbol}: quantity {p.quantity}, entry price {p.entry_price}" + (f" ({p.notes})" if p.notes else ""))
    return "Portfolio:\n" + "\n".join(lines)


@tool
async def get_portfolio() -> str:
    """Get the user's portfolio: each position's id, symbol (ticker), quantity held, entry price, notes, plus their text goal. Symbols may be crypto (BTC), US equities (AAPL), PSX tickers, etc."""
    from app.db.session import async_session_factory

    uid = get_effective_user_id()
    async with async_session_factory() as session:
        return await _get_portfolio_summary(uid, session)


@tool
async def add_position(
    symbol: str,
    quantity: float,
    entry_price: float | None = None,
    notes: str | None = None,
) -> str:
    """Add a new holding. symbol: ticker (BTC, ETH, AAPL, PSX symbols, etc.). quantity: units CURRENTLY OWNED only—not a goal multiplier. entry_price is optional average buy price per unit. Use notes for USD cost basis or estimation method (e.g. ~$400 spot estimate)."""
    if quantity <= 0:
        return "Quantity must be positive."
    if entry_price is not None and entry_price <= 0:
        return "Entry price must be positive when provided."
    from app.db.session import async_session_factory

    sym = normalize_trading_symbol(symbol)
    uid = get_effective_user_id()
    async with async_session_factory() as session:
        await _ensure_user(session, uid)
        pos = PortfolioPosition(
            user_id=uid,
            symbol=sym,
            quantity=quantity,
            entry_price=entry_price if entry_price is not None else 0.0,
            notes=notes,
        )
        session.add(pos)
        await session.commit()
        if entry_price is not None:
            return f"Added {quantity} {sym} to portfolio with entry_price={entry_price}."
        return f"Added {quantity} {sym} to portfolio."


@tool
async def delete_position(symbol: str) -> str:
    """Remove a position by ticker (same symbol format as add_position: BTC, ETH, AAPL, PSX tickers, etc.)."""
    from app.db.session import async_session_factory

    sym = normalize_trading_symbol(symbol)
    uid = get_effective_user_id()
    async with async_session_factory() as session:
        result = await session.execute(
            select(PortfolioPosition).where(
                and_(
                    PortfolioPosition.user_id == uid,
                    PortfolioPosition.symbol == sym,
                )
            )
        )
        pos = result.scalar_one_or_none()
        if not pos:
            return f"No position found for {sym}. Say the exact symbol from their portfolio."
        await session.delete(pos)
        await session.commit()
        return f"Removed {pos.symbol} position from portfolio."


@tool
async def update_position(position_id: int, quantity: float | None = None, entry_price: float | None = None, notes: str | None = None) -> str:
    """Update a position by id from get_portfolio. quantity is the new UNITS HELD (not a goal/target multiple). At least one of quantity, entry_price, notes must be set."""
    if quantity is None and entry_price is None and notes is None:
        return "Provide at least one of quantity, entry_price, or notes to update."
    if quantity is not None and quantity <= 0:
        return "Quantity must be positive."
    if entry_price is not None and entry_price <= 0:
        return "Entry price must be positive."
    from app.db.session import async_session_factory

    uid = get_effective_user_id()
    async with async_session_factory() as session:
        result = await session.execute(
            select(PortfolioPosition).where(
                and_(
                    PortfolioPosition.user_id == uid,
                    PortfolioPosition.id == position_id,
                )
            )
        )
        pos = result.scalar_one_or_none()
        if not pos:
            return f"No position found with id={position_id}. Use get_portfolio to see valid ids."
        if quantity is not None:
            pos.quantity = quantity
        if entry_price is not None:
            pos.entry_price = entry_price
        if notes is not None:
            pos.notes = notes.strip() or None
        await session.commit()
        parts = [f"Updated position id={position_id} ({pos.symbol})"]
        if quantity is not None:
            parts.append(f"quantity={quantity}")
        if entry_price is not None:
            parts.append(f"entry_price={entry_price}")
        if notes is not None:
            parts.append("notes updated")
        return ". ".join(parts) + "."


@tool
async def set_portfolio_goal(goal: str) -> str:
    """Set the user's investment goal as free text only (e.g. 'double in 6 months', 'reach $800'). Never use this to record how many shares/coins they own—that belongs in add_position/update_position."""
    from app.db.session import async_session_factory

    uid = get_effective_user_id()
    async with async_session_factory() as session:
        user = await _ensure_user(session, uid)
        user.portfolio_goal = goal.strip() if goal else None
        await session.commit()
        return "Portfolio goal updated."


def make_portfolio_tool(get_db_session):
    """Legacy factory; use get_portfolio tool directly."""
    return get_portfolio


portfolio_tool = get_portfolio
