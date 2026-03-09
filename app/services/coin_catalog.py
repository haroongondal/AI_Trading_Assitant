"""
Top-100 coins by market cap from CoinGecko. Cached in memory for searchable dropdown.
"""
import logging
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

COINGECKO_MARKETS = "https://api.coingecko.com/api/v3/coins/markets"
CACHE_TTL_SEC = 600  # 10 minutes
_cache: list[dict[str, Any]] = []
_cache_time: float = 0


def _fetch_top_coins(per_page: int = 100) -> list[dict[str, Any]]:
    try:
        with httpx.Client(timeout=15.0) as client:
            r = client.get(
                COINGECKO_MARKETS,
                params={
                    "vs_currency": "usd",
                    "order": "market_cap_desc",
                    "per_page": per_page,
                    "page": 1,
                },
            )
            r.raise_for_status()
            return r.json()
    except Exception as e:
        logger.warning("Coin catalog fetch failed: %s", e)
        return []


def get_coin_catalog(force_refresh: bool = False) -> list[dict[str, Any]]:
    """Return list of { id, symbol, name, market_cap_rank }. Cached."""
    global _cache, _cache_time
    now = time.monotonic()
    if force_refresh or not _cache or (now - _cache_time) > CACHE_TTL_SEC:
        raw = _fetch_top_coins(100)
        _cache = [
            {
                "id": c.get("id", ""),
                "symbol": (c.get("symbol") or "").upper(),
                "name": c.get("name", ""),
                "market_cap_rank": c.get("market_cap_rank"),
            }
            for c in raw
            if c.get("id") and c.get("symbol")
        ]
        _cache_time = now
    return _cache


def search_coins(query: str, limit: int = 50) -> list[dict[str, Any]]:
    """Filter catalog by query (symbol or name, case-insensitive)."""
    catalog = get_coin_catalog()
    if not query or not query.strip():
        return catalog[:limit]
    q = query.strip().lower()
    out = [c for c in catalog if q in (c.get("symbol") or "").lower() or q in (c.get("name") or "").lower()]
    return out[:limit]
