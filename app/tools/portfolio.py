"""
Portfolio tools: read and mutate user portfolio so the agent can analyze and update it from chat.
"""
from langchain_core.tools import tool
from sqlalchemy import select, and_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User, PortfolioPosition
from app.core.config import settings


async def _ensure_user(db: AsyncSession) -> User:
    result = await db.execute(select(User).where(User.id == settings.DEFAULT_USER_ID))
    user = result.scalar_one_or_none()
    if not user:
        user = User(id=settings.DEFAULT_USER_ID, name="Demo User")
        db.add(user)
        try:
            await db.flush()
        except IntegrityError:
            await db.rollback()
            result = await db.execute(select(User).where(User.id == settings.DEFAULT_USER_ID))
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
    """Get the user's current portfolio (positions with id, symbol, quantity, entry price) and their stated goal. Use when the user asks about their portfolio, holdings, or to analyze their positions."""
    from app.db.session import async_session_factory
    async with async_session_factory() as session:
        return await _get_portfolio_summary(settings.DEFAULT_USER_ID, session)


@tool
async def add_position(symbol: str, quantity: float, notes: str | None = None) -> str:
    """Add a new position to the user's portfolio. Use when the user asks to add a coin (e.g. 'add 2 ETH'). symbol: coin symbol (e.g. BTC, ETH). quantity: amount. notes: optional."""
    if quantity <= 0:
        return "Quantity must be positive."
    from app.db.session import async_session_factory
    async with async_session_factory() as session:
        await _ensure_user(session)
        pos = PortfolioPosition(
            user_id=settings.DEFAULT_USER_ID,
            symbol=symbol.upper().strip(),
            quantity=quantity,
            entry_price=0.0,
            notes=notes,
        )
        session.add(pos)
        await session.commit()
        return f"Added {quantity} {symbol.upper()} to portfolio."


@tool
async def delete_position(symbol: str) -> str:
    """Remove a position from the user's portfolio by symbol. Use when the user asks to remove or sell a coin (e.g. 'remove BTC', 'delete my ETH position'). symbol: coin symbol to remove."""
    from app.db.session import async_session_factory
    async with async_session_factory() as session:
        result = await session.execute(
            select(PortfolioPosition).where(
                and_(
                    PortfolioPosition.user_id == settings.DEFAULT_USER_ID,
                    PortfolioPosition.symbol == symbol.upper().strip(),
                )
            )
        )
        pos = result.scalar_one_or_none()
        if not pos:
            return f"No position found for {symbol}. Say the exact symbol from their portfolio."
        await session.delete(pos)
        await session.commit()
        return f"Removed {pos.symbol} position from portfolio."


@tool
async def update_position(position_id: int, quantity: float | None = None, entry_price: float | None = None, notes: str | None = None) -> str:
    """Update an existing portfolio position by id. Use when the user asks to change quantity or entry price of a position (e.g. 'update my BTC 0.002 to 0.003', 'change position id 2 quantity to 0.005'). position_id: the id from get_portfolio. quantity: new quantity (optional). entry_price: new entry price (optional). notes: new notes (optional). At least one of quantity, entry_price, notes must be provided."""
    if quantity is None and entry_price is None and notes is None:
        return "Provide at least one of quantity, entry_price, or notes to update."
    if quantity is not None and quantity <= 0:
        return "Quantity must be positive."
    from app.db.session import async_session_factory
    async with async_session_factory() as session:
        result = await session.execute(
            select(PortfolioPosition).where(
                and_(
                    PortfolioPosition.user_id == settings.DEFAULT_USER_ID,
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
    """Update the user's portfolio goal (text description of what they want to achieve). Use when the user states a goal (e.g. 'my goal is long-term growth', 'I want to save for a house')."""
    from app.db.session import async_session_factory
    async with async_session_factory() as session:
        user = await _ensure_user(session)
        user.portfolio_goal = goal.strip() if goal else None
        await session.commit()
        return "Portfolio goal updated."


def make_portfolio_tool(get_db_session):
    """Legacy factory; use get_portfolio tool directly."""
    return get_portfolio


portfolio_tool = get_portfolio
