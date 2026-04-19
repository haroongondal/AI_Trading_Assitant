"""
Optional REST quotes for `get_quote`: US (Finnhub / Alpha Vantage), PSX via Twelve Data (XKAR),
and PKR per USD from the public open.er-api.com feed (no key) for rough USD hints next to PKR prices.

Keys come from `settings`; when unset, callers fall back to web search / CoinGecko as before.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


def fetch_pkr_per_usd_open_feed() -> float | None:
    """PKR per 1 USD from open.er-api.com (ExchangeRate-API open feed; no key)."""
    try:
        with httpx.Client(timeout=10.0) as client:
            r = client.get("https://open.er-api.com/v6/latest/USD")
            r.raise_for_status()
            data: dict[str, Any] = r.json()
        if str(data.get("result", "")).lower() != "success":
            return None
        pkr = (data.get("rates") or {}).get("PKR")
        if isinstance(pkr, (int, float)) and float(pkr) > 0:
            return float(pkr)
    except Exception as e:
        logger.warning("open_er_usd_pkr_failed err=%s", e)
    return None


def fetch_finnhub_last_usd(symbol: str, api_key: str) -> float | None:
    """Last trade / current price in USD for US and many global tickers (Finnhub free tier)."""
    key = (api_key or "").strip()
    if not key:
        return None
    try:
        with httpx.Client(timeout=10.0) as client:
            r = client.get(
                "https://finnhub.io/api/v1/quote",
                params={"symbol": symbol.upper(), "token": key},
            )
            r.raise_for_status()
            data: dict[str, Any] = r.json()
        c = data.get("c")
        if isinstance(c, (int, float)) and float(c) > 0:
            return float(c)
    except Exception as e:
        logger.warning("finnhub_quote_failed sym=%s err=%s", symbol, e)
    return None


def fetch_alpha_vantage_last_usd(symbol: str, api_key: str) -> float | None:
    """US-focused backup (25 requests/day on free tier)."""
    key = (api_key or "").strip()
    if not key:
        return None
    try:
        with httpx.Client(timeout=12.0) as client:
            r = client.get(
                "https://www.alphavantage.co/query",
                params={"function": "GLOBAL_QUOTE", "symbol": symbol.upper(), "apikey": key},
            )
            r.raise_for_status()
            data: dict[str, Any] = r.json()
        gq = data.get("Global Quote") or {}
        px = gq.get("05. price")
        if px is None:
            return None
        v = float(str(px).strip())
        return v if v > 0 else None
    except Exception as e:
        logger.warning("alphavantage_quote_failed sym=%s err=%s", symbol, e)
    return None


def _twelve_data_quote_parse(data: dict[str, Any], symbol: str) -> tuple[float, str] | None:
    if str(data.get("status", "")).lower() == "error":
        logger.debug("twelvedata_quote_api_error sym=%s msg=%s", symbol, data.get("message"))
        return None
    raw = data.get("close") or data.get("price")
    if raw is None:
        return None
    try:
        price = float(raw)
    except (TypeError, ValueError):
        return None
    if price <= 0:
        return None
    curr = str(data.get("currency") or "PKR").upper()
    return price, curr


def fetch_twelve_data_psx_last(symbol: str, api_key: str) -> tuple[float, str] | None:
    """
    Pakistan Stock Exchange via Twelve Data (MIC **XKAR** / PSX).

    Tries several parameter shapes; Twelve Data versions differ on ``exchange`` vs ``mic_code``.
    Returns (last_price, currency) where currency is usually PKR.
    """
    key = (api_key or "").strip()
    if not key:
        return None
    sym = symbol.upper().strip()
    if not sym:
        return None
    # Two attempts keep PSX coverage without serial latency on every `get_quote` call.
    param_variants: list[dict[str, str]] = [
        {"symbol": sym, "mic_code": "XKAR", "apikey": key},
        {"symbol": f"{sym}:PSX", "apikey": key},
    ]
    try:
        with httpx.Client(timeout=14.0) as client:
            for params in param_variants:
                r = client.get("https://api.twelvedata.com/quote", params=params)
                r.raise_for_status()
                data: dict[str, Any] = r.json()
                row = _twelve_data_quote_parse(data, sym)
                if row:
                    logger.debug("twelvedata_psx_ok sym=%s params=%s", sym, {k: v for k, v in params.items() if k != "apikey"})
                    return row
    except Exception as e:
        logger.warning("twelvedata_quote_failed sym=%s err=%s", sym, e)
        return None
    return None
