"""
Coin catalog API: top-100 by market cap, searchable for portfolio dropdown.
"""
from fastapi import APIRouter, Query

from app.services.coin_catalog import get_supported_symbols, search_coins

router = APIRouter()


@router.get("")
async def list_coins(search: str | None = Query(default=None, description="Filter by symbol or name")):
    """Return dropdown symbols. If search provided, filter by symbol/name; otherwise top supported list."""
    if search and search.strip():
        return {"coins": search_coins(search, limit=50)}
    return {"coins": get_supported_symbols(limit=150)}
