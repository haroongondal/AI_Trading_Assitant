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

_NASDAQ_50: list[dict[str, Any]] = [
    {"id": "nasdaq-aapl", "symbol": "AAPL", "name": "Apple Inc. (NASDAQ)", "market_cap_rank": None},
    {"id": "nasdaq-msft", "symbol": "MSFT", "name": "Microsoft Corp. (NASDAQ)", "market_cap_rank": None},
    {"id": "nasdaq-nvda", "symbol": "NVDA", "name": "NVIDIA Corp. (NASDAQ)", "market_cap_rank": None},
    {"id": "nasdaq-amzn", "symbol": "AMZN", "name": "Amazon.com Inc. (NASDAQ)", "market_cap_rank": None},
    {"id": "nasdaq-googl", "symbol": "GOOGL", "name": "Alphabet Inc. (NASDAQ)", "market_cap_rank": None},
    {"id": "nasdaq-meta", "symbol": "META", "name": "Meta Platforms Inc. (NASDAQ)", "market_cap_rank": None},
    {"id": "nasdaq-tsla", "symbol": "TSLA", "name": "Tesla Inc. (NASDAQ)", "market_cap_rank": None},
    {"id": "nasdaq-avgo", "symbol": "AVGO", "name": "Broadcom Inc. (NASDAQ)", "market_cap_rank": None},
    {"id": "nasdaq-cost", "symbol": "COST", "name": "Costco Wholesale (NASDAQ)", "market_cap_rank": None},
    {"id": "nasdaq-pep", "symbol": "PEP", "name": "PepsiCo Inc. (NASDAQ)", "market_cap_rank": None},
    {"id": "nasdaq-asml", "symbol": "ASML", "name": "ASML Holding (NASDAQ)", "market_cap_rank": None},
    {"id": "nasdaq-adbe", "symbol": "ADBE", "name": "Adobe Inc. (NASDAQ)", "market_cap_rank": None},
    {"id": "nasdaq-csco", "symbol": "CSCO", "name": "Cisco Systems (NASDAQ)", "market_cap_rank": None},
    {"id": "nasdaq-cmcs", "symbol": "CMCSA", "name": "Comcast Corp. (NASDAQ)", "market_cap_rank": None},
    {"id": "nasdaq-intc", "symbol": "INTC", "name": "Intel Corp. (NASDAQ)", "market_cap_rank": None},
    {"id": "nasdaq-amd", "symbol": "AMD", "name": "Advanced Micro Devices (NASDAQ)", "market_cap_rank": None},
    {"id": "nasdaq-qcom", "symbol": "QCOM", "name": "Qualcomm Inc. (NASDAQ)", "market_cap_rank": None},
    {"id": "nasdaq-amat", "symbol": "AMAT", "name": "Applied Materials (NASDAQ)", "market_cap_rank": None},
    {"id": "nasdaq-txmn", "symbol": "TXN", "name": "Texas Instruments (NASDAQ)", "market_cap_rank": None},
    {"id": "nasdaq-intu", "symbol": "INTU", "name": "Intuit Inc. (NASDAQ)", "market_cap_rank": None},
    {"id": "nasdaq-isrg", "symbol": "ISRG", "name": "Intuitive Surgical (NASDAQ)", "market_cap_rank": None},
    {"id": "nasdaq-pypl", "symbol": "PYPL", "name": "PayPal Holdings (NASDAQ)", "market_cap_rank": None},
    {"id": "nasdaq-mu", "symbol": "MU", "name": "Micron Technology (NASDAQ)", "market_cap_rank": None},
    {"id": "nasdaq-bkng", "symbol": "BKNG", "name": "Booking Holdings (NASDAQ)", "market_cap_rank": None},
    {"id": "nasdaq-gild", "symbol": "GILD", "name": "Gilead Sciences (NASDAQ)", "market_cap_rank": None},
    {"id": "nasdaq-regn", "symbol": "REGN", "name": "Regeneron Pharma (NASDAQ)", "market_cap_rank": None},
    {"id": "nasdaq-mdlz", "symbol": "MDLZ", "name": "Mondelez International (NASDAQ)", "market_cap_rank": None},
    {"id": "nasdaq-adp", "symbol": "ADP", "name": "ADP (NASDAQ)", "market_cap_rank": None},
    {"id": "nasdaq-lrcx", "symbol": "LRCX", "name": "Lam Research (NASDAQ)", "market_cap_rank": None},
    {"id": "nasdaq-klac", "symbol": "KLAC", "name": "KLA Corp. (NASDAQ)", "market_cap_rank": None},
    {"id": "nasdaq-mrvl", "symbol": "MRVL", "name": "Marvell Technology (NASDAQ)", "market_cap_rank": None},
    {"id": "nasdaq-snps", "symbol": "SNPS", "name": "Synopsys Inc. (NASDAQ)", "market_cap_rank": None},
    {"id": "nasdaq-cdns", "symbol": "CDNS", "name": "Cadence Design Systems (NASDAQ)", "market_cap_rank": None},
    {"id": "nasdaq-panw", "symbol": "PANW", "name": "Palo Alto Networks (NASDAQ)", "market_cap_rank": None},
    {"id": "nasdaq-crwd", "symbol": "CRWD", "name": "CrowdStrike Holdings (NASDAQ)", "market_cap_rank": None},
    {"id": "nasdaq-ftnt", "symbol": "FTNT", "name": "Fortinet Inc. (NASDAQ)", "market_cap_rank": None},
    {"id": "nasdaq-zs", "symbol": "ZS", "name": "Zscaler Inc. (NASDAQ)", "market_cap_rank": None},
    {"id": "nasdaq-team", "symbol": "TEAM", "name": "Atlassian Corp. (NASDAQ)", "market_cap_rank": None},
    {"id": "nasdaq-ddog", "symbol": "DDOG", "name": "Datadog Inc. (NASDAQ)", "market_cap_rank": None},
    {"id": "nasdaq-abnb", "symbol": "ABNB", "name": "Airbnb Inc. (NASDAQ)", "market_cap_rank": None},
    {"id": "nasdaq-uber", "symbol": "UBER", "name": "Uber Technologies (NASDAQ)", "market_cap_rank": None},
    {"id": "nasdaq-lyft", "symbol": "LYFT", "name": "Lyft Inc. (NASDAQ)", "market_cap_rank": None},
    {"id": "nasdaq-ebay", "symbol": "EBAY", "name": "eBay Inc. (NASDAQ)", "market_cap_rank": None},
    {"id": "nasdaq-docu", "symbol": "DOCU", "name": "DocuSign Inc. (NASDAQ)", "market_cap_rank": None},
    {"id": "nasdaq-roku", "symbol": "ROKU", "name": "Roku Inc. (NASDAQ)", "market_cap_rank": None},
    {"id": "nasdaq-rivn", "symbol": "RIVN", "name": "Rivian Automotive (NASDAQ)", "market_cap_rank": None},
    {"id": "nasdaq-pltr", "symbol": "PLTR", "name": "Palantir Technologies (NASDAQ)", "market_cap_rank": None},
    {"id": "nasdaq-sofi", "symbol": "SOFI", "name": "SoFi Technologies (NASDAQ)", "market_cap_rank": None},
    {"id": "nasdaq-coin", "symbol": "COIN", "name": "Coinbase Global (NASDAQ)", "market_cap_rank": None},
    {"id": "nasdaq-mrna", "symbol": "MRNA", "name": "Moderna Inc. (NASDAQ)", "market_cap_rank": None},
]

_PSX_50: list[dict[str, Any]] = [
    {"id": "psx-ogdc", "symbol": "OGDC", "name": "Oil & Gas Development Co. (PSX)", "market_cap_rank": None},
    {"id": "psx-ppl", "symbol": "PPL", "name": "Pakistan Petroleum Ltd. (PSX)", "market_cap_rank": None},
    {"id": "psx-psx", "symbol": "PSX", "name": "Pakistan Stock Exchange Ltd. (PSX)", "market_cap_rank": None},
    {"id": "psx-hubc", "symbol": "HUBC", "name": "Hub Power Co. (PSX)", "market_cap_rank": None},
    {"id": "psx-ffc", "symbol": "FFC", "name": "Fauji Fertilizer Co. (PSX)", "market_cap_rank": None},
    {"id": "psx-engro", "symbol": "ENGRO", "name": "Engro Corp. (PSX)", "market_cap_rank": None},
    {"id": "psx-mcb", "symbol": "MCB", "name": "MCB Bank Ltd. (PSX)", "market_cap_rank": None},
    {"id": "psx-hbl", "symbol": "HBL", "name": "Habib Bank Ltd. (PSX)", "market_cap_rank": None},
    {"id": "psx-ubl", "symbol": "UBL", "name": "United Bank Ltd. (PSX)", "market_cap_rank": None},
    {"id": "psx-bafl", "symbol": "BAFL", "name": "Bank Alfalah Ltd. (PSX)", "market_cap_rank": None},
    {"id": "psx-meezan", "symbol": "MEBL", "name": "Meezan Bank Ltd. (PSX)", "market_cap_rank": None},
    {"id": "psx-abl", "symbol": "ABL", "name": "Allied Bank Ltd. (PSX)", "market_cap_rank": None},
    {"id": "psx-nbp", "symbol": "NBP", "name": "National Bank of Pakistan (PSX)", "market_cap_rank": None},
    {"id": "psx-fauji-c", "symbol": "FCCL", "name": "Fauji Cement Co. (PSX)", "market_cap_rank": None},
    {"id": "psx-lucky", "symbol": "LUCK", "name": "Lucky Cement Ltd. (PSX)", "market_cap_rank": None},
    {"id": "psx-dgkc", "symbol": "DGKC", "name": "D.G. Khan Cement (PSX)", "market_cap_rank": None},
    {"id": "psx-maple", "symbol": "MLCF", "name": "Maple Leaf Cement (PSX)", "market_cap_rank": None},
    {"id": "psx-pioc", "symbol": "PIOC", "name": "Pioneer Cement (PSX)", "market_cap_rank": None},
    {"id": "psx-efert", "symbol": "EFERT", "name": "Engro Fertilizers (PSX)", "market_cap_rank": None},
    {"id": "psx-fatima", "symbol": "FATIMA", "name": "Fatima Fertilizer (PSX)", "market_cap_rank": None},
    {"id": "psx-pakt", "symbol": "PAKT", "name": "Pakistan Tobacco (PSX)", "market_cap_rank": None},
    {"id": "psx-pol", "symbol": "POL", "name": "Pakistan Oilfields (PSX)", "market_cap_rank": None},
    {"id": "psx-mari", "symbol": "MARI", "name": "Mari Petroleum (PSX)", "market_cap_rank": None},
    {"id": "psx-attock", "symbol": "APL", "name": "Attock Petroleum (PSX)", "market_cap_rank": None},
    {"id": "psx-shell", "symbol": "SHEL", "name": "Shell Pakistan (PSX)", "market_cap_rank": None},
    {"id": "psx-ssgc", "symbol": "SSGC", "name": "Sui Southern Gas (PSX)", "market_cap_rank": None},
    {"id": "psx-sngp", "symbol": "SNGP", "name": "Sui Northern Gas (PSX)", "market_cap_rank": None},
    {"id": "psx-ptc", "symbol": "PTC", "name": "Pakistan Telecommunication (PSX)", "market_cap_rank": None},
    {"id": "psx-trg", "symbol": "TRG", "name": "TRG Pakistan (PSX)", "market_cap_rank": None},
    {"id": "psx-sys", "symbol": "SYS", "name": "Systems Limited (PSX)", "market_cap_rank": None},
    {"id": "psx-airlink", "symbol": "AIRLINK", "name": "Air Link Communication (PSX)", "market_cap_rank": None},
    {"id": "psx-avn", "symbol": "AVN", "name": "Avanceon Ltd. (PSX)", "market_cap_rank": None},
    {"id": "psx-hum", "symbol": "HUMNL", "name": "Hum Network (PSX)", "market_cap_rank": None},
    {"id": "psx-tele", "symbol": "TELE", "name": "Telecard Ltd. (PSX)", "market_cap_rank": None},
    {"id": "psx-ghni", "symbol": "GHNI", "name": "Ghani Global Glass (PSX)", "market_cap_rank": None},
    {"id": "psx-ghnl", "symbol": "GHNL", "name": "Ghandhara Nissan (PSX)", "market_cap_rank": None},
    {"id": "psx-indu", "symbol": "INDU", "name": "Indus Motor Co. (PSX)", "market_cap_rank": None},
    {"id": "psx-psmc", "symbol": "PSMC", "name": "Pak Suzuki Motors (PSX)", "market_cap_rank": None},
    {"id": "psx-hcar", "symbol": "HCAR", "name": "Honda Atlas Cars (PSX)", "market_cap_rank": None},
    {"id": "psx-astl", "symbol": "ASTL", "name": "Aisha Steel Mills (PSX)", "market_cap_rank": None},
    {"id": "psx-mughal", "symbol": "MUGHAL", "name": "Mughal Iron & Steel (PSX)", "market_cap_rank": None},
    {"id": "psx-inil", "symbol": "INIL", "name": "International Industries (PSX)", "market_cap_rank": None},
    {"id": "psx-ktml", "symbol": "KTML", "name": "Kohinoor Textile (PSX)", "market_cap_rank": None},
    {"id": "psx-ngr", "symbol": "NML", "name": "Nishat Mills (PSX)", "market_cap_rank": None},
    {"id": "psx-ncl", "symbol": "NCL", "name": "Nishat Chunian (PSX)", "market_cap_rank": None},
    {"id": "psx-ici", "symbol": "ICI", "name": "ICI Pakistan (PSX)", "market_cap_rank": None},
    {"id": "psx-colg", "symbol": "COLG", "name": "Colgate Palmolive Pakistan (PSX)", "market_cap_rank": None},
    {"id": "psx-unilever", "symbol": "UPFL", "name": "Unilever Pakistan Foods (PSX)", "market_cap_rank": None},
    {"id": "psx-nestle", "symbol": "NESTLE", "name": "Nestle Pakistan (PSX)", "market_cap_rank": None},
    {"id": "psx-glaxo", "symbol": "GLAXO", "name": "GlaxoSmithKline Pakistan (PSX)", "market_cap_rank": None},
    {"id": "psx-sazew", "symbol": "SAZEW", "name": "Sazgar Engineering Works (PSX)", "market_cap_rank": None},
]

# PSX-focused catalog rows (dropdown + PKR-flavored web search hints). Quote routing no longer
# depends only on this set — see `get_quote` + Twelve Data for broader PSX coverage.
PSX_CATALOG_SYMBOLS: frozenset[str] = frozenset(
    (row["symbol"] or "").upper() for row in _PSX_50 if row.get("symbol")
)


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
    catalog = [*_NASDAQ_50, *_PSX_50, *get_coin_catalog()]
    if not query or not query.strip():
        return catalog[:limit]
    q = query.strip().lower()
    out = [c for c in catalog if q in (c.get("symbol") or "").lower() or q in (c.get("name") or "").lower()]
    return out[:limit]


def get_supported_symbols(limit: int = 150) -> list[dict[str, Any]]:
    """Return default dropdown list: 50 NASDAQ + 50 PSX + 50 crypto (total 150)."""
    crypto_50 = get_coin_catalog()[:50]
    combined = [*_NASDAQ_50[:50], *_PSX_50[:50], *crypto_50]
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for row in combined:
        sym = (row.get("symbol") or "").upper()
        if not sym or sym in seen:
            continue
        seen.add(sym)
        out.append(row)
        if len(out) >= limit:
            break
    return out
