"""
Fetch current crypto prices from CoinGecko (free, no API key). Top-100 by market cap for analysis.
"""
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

MARKETS_URL = "https://api.coingecko.com/api/v3/coins/markets"


def fetch_crypto_prices(limit: int = 100) -> dict[str, float]:
    """Return dict of symbol -> USD price for top coins by market cap. Empty dict on error."""
    try:
        with httpx.Client(timeout=15.0) as client:
            r = client.get(
                MARKETS_URL,
                params={
                    "vs_currency": "usd",
                    "order": "market_cap_desc",
                    "per_page": limit,
                    "page": 1,
                },
            )
            r.raise_for_status()
            data: list[dict[str, Any]] = r.json()
    except Exception as e:
        logger.warning("Price fetch failed: %s", e)
        return {}
    result: dict[str, float] = {}
    for c in data:
        sym = (c.get("symbol") or "").upper()
        price = c.get("current_price")
        if sym and isinstance(price, (int, float)):
            result[sym] = float(price)
    return result


def format_prices_for_prompt(prices: dict[str, float]) -> str:
    """Format current prices for inclusion in the LLM prompt."""
    if not prices:
        return "Current prices: unavailable (price API did not return data)."
    lines = [f"{sym}: ${p:,.2f}" for sym, p in sorted(prices.items())]
    return "Current prices (USD): " + ", ".join(lines)


def non_crypto_price_disclaimer(portfolio_symbols: list[str], crypto_prices: dict[str, float]) -> str:
    """
    Remind the model that CoinGecko-style prices only cover symbols present in crypto_prices;
    equities/PSX tickers must not get invented spot prices.
    """
    if not portfolio_symbols:
        return ""
    known = {k.upper() for k in crypto_prices.keys()}
    missing = sorted({s.upper() for s in portfolio_symbols if s.upper() not in known})
    if not missing:
        return ""
    return (
        "The live price list above is from the crypto feed only. "
        f"These portfolio tickers are not in that feed—do not invent prices for them: {', '.join(missing)}."
    )
