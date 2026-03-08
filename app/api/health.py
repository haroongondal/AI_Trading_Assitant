"""
Health check: DB connectivity and Ollama reachability.
Useful for C-level demo and Docker readiness probes.
"""
import logging
import httpx
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import get_db

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("")
async def health(db: AsyncSession = Depends(get_db)):
    """Returns status of database and Ollama. JS parallel: like a /health route in Express."""
    db_ok = False
    ollama_ok = False
    try:
        await db.execute(text("SELECT 1"))
        db_ok = True
    except Exception as e:
        logger.warning("Health check DB error: %s", e)
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{settings.OLLAMA_BASE_URL.rstrip('/')}/api/tags")
            ollama_ok = r.status_code == 200
    except Exception as e:
        logger.warning("Health check Ollama error: %s", e)
    status = "healthy" if (db_ok and ollama_ok) else "degraded"
    return {
        "status": status,
        "database": "ok" if db_ok else "error",
        "ollama": "ok" if ollama_ok else "error",
    }
