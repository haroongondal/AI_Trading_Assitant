"""
Portfolio tool: read user portfolio from DB so the agent can analyze it.
"""
from langchain_core.tools import tool
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import PortfolioPosition
from app.core.config import settings


async def _get_portfolio_summary(user_id: str, db: AsyncSession) -> str:
    result = await db.execute(
        select(PortfolioPosition).where(PortfolioPosition.user_id == user_id)
    )
    positions = result.scalars().all()
    if not positions:
        return "The user has no portfolio positions."
    lines = []
    for p in positions:
        lines.append(f"- {p.symbol}: quantity {p.quantity}, entry price {p.entry_price}" + (f" ({p.notes})" if p.notes else ""))
    return "Portfolio:\n" + "\n".join(lines)


def make_portfolio_tool(get_db_session):
    """
    Factory: returns a tool that has access to DB session.
    get_db_session is an async context manager or dependency that yields AsyncSession.
    """
    @tool
    async def get_portfolio() -> str:
        """Get the user's current portfolio (positions with symbol, quantity, entry price). Use when the user asks about their portfolio, holdings, or to analyze their positions."""
        # We need to get a session; FastAPI dependency injection isn't available inside the tool.
        # So we pass a coroutine that returns a session. The agent runner will need to inject session.
        from app.db.session import async_session_factory
        async with async_session_factory() as session:
            return await _get_portfolio_summary(settings.DEFAULT_USER_ID, session)
    return get_portfolio


# Standalone tool that creates its own session (for use in agent)
@tool
async def get_portfolio() -> str:
    """Get the user's current portfolio (positions with symbol, quantity, entry price). Use when the user asks about their portfolio, holdings, or to analyze their positions."""
    from app.db.session import async_session_factory
    async with async_session_factory() as session:
        return await _get_portfolio_summary(settings.DEFAULT_USER_ID, session)


portfolio_tool = get_portfolio
