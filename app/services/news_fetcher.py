"""
Fetch crypto and forex news from RSS/public sources. JS parallel: like a small service that fetches URLs and parses feeds.
"""
import logging
from datetime import datetime
from typing import Any

import feedparser

logger = logging.getLogger(__name__)

# Public RSS feeds for crypto/forex (no API key required)
FEEDS = [
    "https://cointelegraph.com/rss",
    "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "https://cryptonews.com/news/feed/",
]


def fetch_news(limit_per_feed: int = 10) -> list[dict[str, Any]]:
    """Fetch entries from configured feeds. Returns list of {title, summary, link, published}."""
    entries: list[dict[str, Any]] = []
    seen_links: set[str] = set()
    for url in FEEDS:
        try:
            parsed = feedparser.parse(url)
            for e in parsed.entries[:limit_per_feed]:
                link = e.get("link", "")
                if link in seen_links:
                    continue
                seen_links.add(link)
                published = e.get("published_parsed")
                pub_dt = datetime(*published[:6]) if published else datetime.utcnow()
                summary = e.get("summary", "") or e.get("description", "")
                # Strip HTML tags roughly
                if "<" in summary:
                    import re
                    summary = re.sub(r"<[^>]+>", " ", summary)
                entries.append({
                    "title": e.get("title", ""),
                    "summary": (summary or "")[:2000],
                    "link": link,
                    "published": pub_dt.isoformat(),
                })
        except Exception as e:
            logger.warning("Feed %s error: %s", url, e)
    return entries
