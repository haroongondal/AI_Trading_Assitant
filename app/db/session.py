"""
Async database session and initialization.
JS parallel: like a connection pool + getConnection() in Node.
"""
import os
from pathlib import Path
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from .models import Base
from app.core.config import settings

# Resolve SQLite path relative to backend root so DB is always in backend/data/
# (backend root = parent of app/)
_backend_root = Path(__file__).resolve().parent.parent.parent
_database_url = settings.DATABASE_URL
if _database_url.startswith("sqlite+aiosqlite:///./"):
    _rel = _database_url.replace("sqlite+aiosqlite:///./", "")
    _data_dir = _backend_root / os.path.dirname(_rel)
    _data_dir.mkdir(parents=True, exist_ok=True)
    _db_path = (_backend_root / _rel).as_posix()
    _database_url = f"sqlite+aiosqlite:///{_db_path}"

engine = create_async_engine(
    _database_url,
    echo=False,
)
async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db():
    """Dependency that yields a session; use with FastAPI Depends()."""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


def _add_portfolio_goal_if_missing(sync_conn):
    """Add portfolio_goal column to users if it doesn't exist (e.g. existing DBs)."""
    try:
        result = sync_conn.execute(text("PRAGMA table_info(users)"))
        rows = result.fetchall()
        if not any(row[1] == "portfolio_goal" for row in rows):
            sync_conn.execute(text("ALTER TABLE users ADD COLUMN portfolio_goal TEXT"))
    except Exception:
        pass


def _add_google_sub_if_missing(sync_conn):
    """Add google_sub for OAuth users (nullable, unique when set)."""
    try:
        result = sync_conn.execute(text("PRAGMA table_info(users)"))
        rows = result.fetchall()
        if any(row[1] == "google_sub" for row in rows):
            return
        sync_conn.execute(text("ALTER TABLE users ADD COLUMN google_sub VARCHAR(255)"))
        sync_conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ix_users_google_sub "
                "ON users(google_sub) WHERE google_sub IS NOT NULL"
            )
        )
    except Exception:
        pass


async def init_db():
    """Create tables if they don't exist. Migrate existing tables if needed."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_add_portfolio_goal_if_missing)
        await conn.run_sync(_add_google_sub_if_missing)
