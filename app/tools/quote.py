"""
`get_quote`: live spot price lookup for a single symbol.

Strategy (in order):
  1. CoinGecko **top markets** only for liquid crypto (no /search until later — faster for equities).
  2. Finnhub, then Alpha Vantage, for US/global equities when those API keys are set.
  3. Twelve Data **PSX** (MIC XKAR / PSX) when `TWELVEDATA_API_KEY` is set.
  4. CoinGecko **/search** + /simple/price for altcoins not in the top-N list.
  5. **Fast** DuckDuckGo snippets only (bounded timeout) — never Groq Compound here, so
     `get_quote` does not block on slow native web search used by the `search_web` tool.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from typing import Any

import httpx
from langchain_community.tools import DuckDuckGoSearchRun
from langchain_core.tools import tool

from app.core.config import settings
from app.services.coin_catalog import PSX_CATALOG_SYMBOLS
from app.services import market_quotes
from app.services.price_fetcher import fetch_crypto_prices
from app.tools.symbol_normalize import normalize_trading_symbol

logger = logging.getLogger(__name__)

COINGECKO_SEARCH = "https://api.coingecko.com/api/v3/search"
COINGECKO_SIMPLE_PRICE = "https://api.coingecko.com/api/v3/simple/price"

_ddg = DuckDuckGoSearchRun()
_QUOTE_WEB_TIMEOUT_SEC = 14.0


def _coingecko_id_for_symbol(symbol: str) -> str | None:
    """Resolve a ticker like BTC/ETH to a CoinGecko id via the /search endpoint."""
    try:
        with httpx.Client(timeout=8.0) as client:
            r = client.get(COINGECKO_SEARCH, params={"query": symbol})
            r.raise_for_status()
            data: dict[str, Any] = r.json()
    except Exception as e:
        logger.warning("coingecko_search_failed symbol=%s err=%s", symbol, e)
        return None
    coins = data.get("coins") or []
    sym_up = symbol.upper()
    for c in coins:
        if (c.get("symbol") or "").upper() == sym_up:
            return c.get("id")
    return None


def _coingecko_price_by_id(coin_id: str) -> float | None:
    try:
        with httpx.Client(timeout=8.0) as client:
            r = client.get(
                COINGECKO_SIMPLE_PRICE,
                params={"ids": coin_id, "vs_currencies": "usd"},
            )
            r.raise_for_status()
            data: dict[str, Any] = r.json()
    except Exception as e:
        logger.warning("coingecko_price_failed id=%s err=%s", coin_id, e)
        return None
    row = data.get(coin_id) or {}
    px = row.get("usd")
    if isinstance(px, (int, float)):
        return float(px)
    return None


def _top_crypto_price_only(symbol: str, top_crypto: dict[str, float]) -> float | None:
    """USD spot from top-N markets only (no /search — avoids slow path for stock tickers)."""
    return top_crypto.get(symbol.upper())


def _coingecko_search_price(symbol: str) -> float | None:
    coin_id = _coingecko_id_for_symbol(symbol)
    if not coin_id:
        return None
    return _coingecko_price_by_id(coin_id)


def _quote_web_snippets_ddg(query: str) -> str:
    """
    DuckDuckGo only, hard timeout — `search_web` may call Groq Compound and take minutes;
    quote fallback must stay snappy for the agent UI ('Fetching live price…').
    """
    try:
        with ThreadPoolExecutor(max_workers=1) as ex:
            fut = ex.submit(_ddg.invoke, query)
            return str(fut.result(timeout=_QUOTE_WEB_TIMEOUT_SEC) or "")
    except FuturesTimeout:
        logger.warning("quote_web_ddg_timeout query=%r", query[:80])
        return (
            f"[Timed out after {_QUOTE_WEB_TIMEOUT_SEC:.0f}s] "
            "Configure Finnhub, Twelve Data, or Alpha Vantage for faster quotes, or retry."
        )
    except Exception as e:
        logger.warning("quote_web_ddg_failed err=%s", e)
        return f"Search error: {e}"


def _equity_web_query(sym: str) -> str:
    if sym in PSX_CATALOG_SYMBOLS:
        return f"{sym} PSX Pakistan Stock Exchange share price PKR today"
    return f"{sym} stock share price today USD NASDAQ NYSE"


@tool
def get_quote(symbol: str) -> str:
    """Return the latest spot price (USD) for a single ticker so the agent can size positions.

    Use this BEFORE add_position/update_position whenever the user gives a cash
    amount instead of a quantity (e.g. "I bought $500 of BTC", "20,000 PKR in a
    listed stock") or gives a quantity without entry price ("I have 10 shares of
    AAPL"). The agent can then compute:
        quantity = amount / price
        entry_price = price
    and call add_position/update_position.

    symbol: ticker (BTC, ETH, AAPL, PSX tickers, forex pairs as supported by data providers).
    Returns a short text line ending with "USD" on success for crypto/US spot, or PKR per share
    for Pakistan listings when the source reports PKR.
    """
    sym = normalize_trading_symbol(symbol)
    if not sym:
        return "Provide a non-empty symbol."

    top_crypto = fetch_crypto_prices(250)
    px = _top_crypto_price_only(sym, top_crypto)
    if px is not None:
        return f"{sym} spot price: {px:.6f} USD (source: CoinGecko live)"

    fh = (settings.FINNHUB_API_KEY or "").strip()
    if fh:
        u = market_quotes.fetch_finnhub_last_usd(sym, fh)
        if u is not None:
            return f"{sym} spot price: {u:.6f} USD (source: Finnhub)"
    av = (settings.ALPHA_VANTAGE_API_KEY or "").strip()
    if av:
        u = market_quotes.fetch_alpha_vantage_last_usd(sym, av)
        if u is not None:
            return f"{sym} spot price: {u:.6f} USD (source: Alpha Vantage)"

    td_key = (settings.TWELVEDATA_API_KEY or "").strip()
    if td_key and sym not in top_crypto:
        psx_row = market_quotes.fetch_twelve_data_psx_last(sym, td_key)
        if psx_row:
            last_px, curr = psx_row
            fx = market_quotes.fetch_pkr_per_usd_open_feed()
            usd_hint = ""
            if curr == "PKR" and fx:
                usd_per_share = last_px / fx
                usd_hint = f" (~{usd_per_share:.6f} USD/share at open USD/PKR≈{fx:.4f})"
            elif curr == "USD":
                usd_hint = " (already in USD per share)"
            return (
                f"{sym} quote (Twelve Data, Pakistan listing): {last_px:.4f} {curr} per share{usd_hint}. "
                f"If the user invested in PKR: shares = total_pkr_invested / price_pkr; entry_price = PKR per share. "
                f"Do not ask for per-share PKR when they already gave total PKR invested."
            )

    cpx = _coingecko_search_price(sym)
    if cpx is not None:
        return f"{sym} spot price: {cpx:.6f} USD (source: CoinGecko live)"

    query = _equity_web_query(sym)
    snippets = _quote_web_snippets_ddg(query)

    if sym in PSX_CATALOG_SYMBOLS:
        return (
            f"{sym}: snippets below often list **PKR per share** (Pakistan listing). "
            f"Use that for sizing: shares_owned = total_pkr_invested / pkr_per_share; "
            f"add_position(symbol=\"{sym}\", quantity=shares_owned, entry_price=pkr_per_share, "
            f"notes=…). Do NOT ask the user for per-share PKR if they already gave total PKR invested.\n"
            f"Web snippets for '{query}':\n{snippets}"
        )
    return (
        f"No direct API quote for {sym}. Read the latest price from the web snippets below "
        f"(USD for US listings, PKR or local currency for other exchanges). "
        f"If there is no usable price, say so briefly—do not invent one.\n"
        f"Web snippets for '{query}':\n{snippets}"
    )


quote_tool = get_quote
