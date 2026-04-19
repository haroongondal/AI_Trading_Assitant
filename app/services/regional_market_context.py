"""
Regional / macro web and RAG query builders. PSX and PKR portfolios react to Pakistan
domestic news, USD/PKR, Middle East / oil, and US risk — not just ticker headlines.
Crypto is mostly US-driven but can move on Pakistan policy (e.g. exchange access).
"""
from __future__ import annotations

import re

# Max web queries per run (scheduler vs chat) to control latency and rate limits.
SCHEDULER_WEB_QUERY_CAP = 6
CHAT_PORTFOLIO_WEB_QUERY_CAP = 3


def top_themes_from_text(news_context: str, *, max_themes: int = 3) -> list[str]:
    stopwords = {
        "THE",
        "AND",
        "FOR",
        "WITH",
        "FROM",
        "THIS",
        "THAT",
        "HAVE",
        "WILL",
        "MARKET",
        "CRYPTO",
        "STOCK",
        "PRICE",
        "NEWS",
        "ABOUT",
    }
    counts: dict[str, int] = {}
    for token in re.findall(r"\b[A-Za-z]{4,15}\b", (news_context or "").upper()):
        if token in stopwords:
            continue
        counts[token] = counts.get(token, 0) + 1
    ranked = sorted(counts.items(), key=lambda item: item[1], reverse=True)
    return [token for token, _ in ranked[:max_themes]]


def parse_symbols_from_portfolio_snapshot(portfolio_blob: str) -> list[str]:
    """Parse tickers from get_portfolio() text: `- id=12 SYMBOL: quantity ...`."""
    if not (portfolio_blob or "").strip():
        return []
    found = re.findall(r"- id=\d+\s+([A-Za-z][A-Za-z0-9._-]{0,15}):", portfolio_blob, flags=re.I)
    out: list[str] = []
    seen: set[str] = set()
    for raw in found:
        s = raw.upper().strip()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def split_psx_crypto_other(
    symbols: list[str],
    *,
    psx_catalog: frozenset[str],
    crypto_spot_symbols: set[str],
) -> tuple[list[str], list[str], list[str]]:
    psx: list[str] = []
    crypto: list[str] = []
    other: list[str] = []
    for s in symbols:
        u = s.upper().strip()
        if not u:
            continue
        if u in psx_catalog:
            psx.append(u)
        elif u in crypto_spot_symbols:
            crypto.append(u)
        else:
            other.append(u)
    return psx, crypto, other


def build_digest_rag_query(held_symbols: list[str]) -> str:
    syms = " ".join((held_symbols or [])[:20])
    return (
        "Pakistan PSX stock market economy KSE US Federal Reserve interest rates "
        "dollar emerging markets Middle East oil geopolitics cryptocurrency Bitcoin "
        "regulation Pakistan rupee latest news analysis "
        f"{syms}"
    ).strip()


def build_digest_web_queries(
    held_symbols: list[str],
    *,
    held_psx: list[str],
    held_crypto: list[str],
    goal_text: str,
    news_context: str,
) -> list[str]:
    """
    Ordered searches for scheduled notifications: macro + exchange + holdings.
    """
    themes = top_themes_from_text(news_context)
    theme_fragment = f" themes {', '.join(themes)}" if themes else ""
    goal_snip = (goal_text or "")[:140].strip()

    queries: list[str] = []

    # Pakistan + PSX + transmission channels (Middle East oil, US risk-off).
    queries.append(
        "Pakistan stock market PSX KSE-100 news this week economy IMF Middle East oil prices impact"
    )
    queries.append(
        "United States Federal Reserve interest rates US dollar DXY today emerging markets Pakistan rupee impact"
    )
    queries.append(
        "Middle East geopolitical tensions oil markets global risk sentiment Pakistan stock exchange"
    )

    if held_psx:
        joined = ", ".join(held_psx[:10])
        queries.append(f"Pakistan Stock Exchange PSX latest news {joined} share price catalysts")

    if held_crypto:
        joined_c = ", ".join(held_crypto[:8])
        queries.append(
            f"Bitcoin cryptocurrency United States SEC regulation latest news {joined_c} Pakistan crypto exchange"
        )

    if held_symbols:
        joined = ", ".join(held_symbols[:8])
        queries.append(
            f"Latest market updates risk outlook catalysts for {joined}{theme_fragment}. "
            f"Context: {goal_snip or 'portfolio review'}"
        )

    # Dedupe while preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for q in queries:
        key = q.strip().lower()
        if key and key not in seen:
            seen.add(key)
            unique.append(q.strip())
    return unique[:SCHEDULER_WEB_QUERY_CAP]


def build_chat_portfolio_web_queries(
    symbols: list[str],
    *,
    psx_catalog: frozenset[str],
    crypto_spot_symbols: set[str],
) -> list[str]:
    """Short macro bundle after portfolio prefetch (chat)."""
    psx, crypto, other = split_psx_crypto_other(symbols, psx_catalog=psx_catalog, crypto_spot_symbols=crypto_spot_symbols)
    queries: list[str] = []

    if psx or other:
        queries.append(
            "Pakistan PSX stock market news KSE-100 Middle East oil US markets impact on emerging markets this week"
        )
    if crypto:
        queries.append(
            "United States cryptocurrency Bitcoin regulation Fed liquidity risk latest headlines "
            + ", ".join(crypto[:6])
        )
        queries.append("Pakistan cryptocurrency exchange policy Bitcoin regulation news latest")

    if psx:
        queries.append(
            "Pakistan Stock Exchange PSX latest news " + ", ".join(psx[:8]) + " sector outlook"
        )
    elif symbols and not queries:
        queries.append("Latest market news " + ", ".join(symbols[:8]))

    seen: set[str] = set()
    out: list[str] = []
    for q in queries:
        k = q.strip().lower()
        if k and k not in seen:
            seen.add(k)
            out.append(q.strip())
    return out[:CHAT_PORTFOLIO_WEB_QUERY_CAP]
