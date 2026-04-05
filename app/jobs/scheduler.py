"""
APScheduler: fetch news, ingest into RAG, then run portfolio + news analysis and create notifications.
JS parallel: like setInterval or node-cron jobs that run in the background.
"""
import logging
import re
import time

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.chat_timing import utc_iso
from app.core.config import settings
from app.db.session import async_session_factory
from app.db.models import PortfolioPosition, Notification, User
from app.services.news_fetcher import fetch_news
from app.services.rag_ingest import ingest_documents
from app.services.price_fetcher import (
    fetch_crypto_prices,
)
from app.services.email import send_notification as send_email
from app.services.whatsapp import send_notification as send_whatsapp
from app.tools.rag import get_rag_retriever
from app.tools.web_search import search_web
from app.agent.stream_sanitize import sanitize_assistant_visible_text
from app.services.ollama_client import get_llm
from langchain_core.messages import SystemMessage, HumanMessage

logger = logging.getLogger(__name__)
scheduler = AsyncIOScheduler()


async def job_fetch_news_and_ingest():
    """Fetch crypto/forex news and add to RAG vector store."""
    try:
        entries = fetch_news(limit_per_feed=8)
        if entries:
            n = ingest_documents(entries)
            logger.info("News job: fetched %s entries, ingested %s chunks", len(entries), n)
        else:
            logger.warning("News job: no entries fetched")
    except Exception as e:
        logger.exception("News job error: %s", e)


async def _ensure_user_row(db: AsyncSession, uid: str) -> User:
    r = await db.execute(select(User).where(User.id == uid))
    user = r.scalar_one_or_none()
    if not user:
        try:
            user = User(id=uid, name="Demo User" if uid == settings.DEFAULT_USER_ID else "User")
            db.add(user)
            await db.flush()
        except IntegrityError:
            await db.rollback()
            r = await db.execute(select(User).where(User.id == uid))
            user = r.scalar_one_or_none()
            if not user:
                raise
    return user


def _extract_symbols(text: str) -> list[str]:
    symbols = set()
    for token in re.findall(r"\b[A-Z][A-Z0-9._-]{1,11}\b", (text or "").upper()):
        if token not in {"USD", "USDT", "USDC", "HOLD", "SELL", "BUY"}:
            symbols.add(token)
    return sorted(symbols)


def _header_section(body: str, header: str) -> str:
    if not body:
        return ""
    marker = f"## {header}".lower()
    low = body.lower()
    start = low.find(marker)
    if start < 0:
        return ""
    section = body[start + len(marker) :]
    next_idx = section.lower().find("\n## ")
    if next_idx >= 0:
        section = section[:next_idx]
    return section.strip()


def _format_symbol_prices(symbols: list[str], crypto_prices: dict[str, float]) -> str:
    rows = []
    for sym in symbols:
        if sym in crypto_prices:
            rows.append(f"- {sym}: ${crypto_prices[sym]:,.4f}")
    return "\n".join(rows)


def _web_search(query: str) -> str:
    try:
        if hasattr(search_web, "invoke"):
            result = search_web.invoke({"query": query})
        else:
            result = search_web(query)
        return str(result or "").strip()
    except Exception as exc:
        return f"Search error: {exc}"


def _top_news_themes(news_context: str) -> list[str]:
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
    return [token for token, _ in ranked[:3]]


def _build_targeted_web_context(portfolio_symbols: list[str], goal_text: str, news_context: str) -> str:
    if not portfolio_symbols:
        return "No portfolio symbols available for targeted web search."
    joined = ", ".join(portfolio_symbols[:8])
    themes = _top_news_themes(news_context)
    theme_fragment = f" and themes {', '.join(themes)}" if themes else ""
    queries = [
        f"Latest market updates and catalysts for {joined}{theme_fragment}",
        f"Risk outlook and near-term momentum for {joined}. Goal context: {goal_text[:120]}. News themes: {', '.join(themes) or 'none'}",
    ]
    snippets = []
    for query in queries:
        result = _web_search(query)
        if result:
            snippets.append(f"Query: {query}\nResult: {result[:700]}")
    return "\n\n".join(snippets) if snippets else "Targeted web search returned no usable results."


def _fallback_markdown(
    portfolio_prices_section: str,
    suggested_buys_prices: str,
    suggested_hold_sell_prices: str,
    suggested_watch_prices: str,
    analysis_text: str,
    recommendation: str,
) -> str:
    chunks = [
        "## Portfolio Prices",
        portfolio_prices_section or "- No live crypto prices available for held symbols.",
        "## Suggested Buys",
        suggested_buys_prices or "- No buy candidates identified.",
        "## Hold/Sell Review",
        suggested_hold_sell_prices or "- Continue monitoring current holdings.",
        "## Watchlist",
        suggested_watch_prices or "- No watchlist additions identified.",
        "## Market Analysis",
        analysis_text or "- Market is mixed; monitor catalysts and volatility.",
        "## Recommendation",
        recommendation or "HOLD",
    ]
    return "\n\n".join(chunks).strip()


def _extract_goal_amount(goal_text: str) -> float | None:
    if not goal_text:
        return None
    m = re.search(r"\$?\s*([0-9][0-9,]*(?:\.[0-9]+)?)", goal_text)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return None


def _portfolio_prices_markdown(positions: list[PortfolioPosition], prices: dict[str, float]) -> str:
    lines: list[str] = []
    for p in positions:
        sym = (p.symbol or "").upper().strip()
        qty = float(p.quantity)
        if sym in prices:
            px = prices[sym]
            lines.extend(
                [
                    f"### {sym}",
                    f"- Symbol: {sym}",
                    f"- Quantity: {qty:g}",
                    f"- Price: ${px:,.4f}",
                    f"- Total Value: ${qty * px:,.2f}",
                ]
            )
        else:
            lines.extend(
                [
                    f"### {sym}",
                    f"- Symbol: {sym}",
                    f"- Quantity: {qty:g}",
                    "- Price: N/A (web/news-only)",
                ]
            )
    return "\n".join(lines) if lines else "- No holdings found."


def _clean_line_value(line: str) -> str:
    cleaned = line.strip().lstrip("-* ").strip()
    cleaned = re.sub(r"^(recommendation|concrete action|action)\s*:\s*", "", cleaned, flags=re.I)
    cleaned = re.sub(r"^[#>\s`*_~]+", "", cleaned)
    cleaned = re.sub(r"[`*_~]+", "", cleaned)
    return cleaned.strip()


def _normalize_section(section: str, default_line: str) -> str:
    if not section.strip():
        return default_line
    normalized = []
    for raw in section.splitlines():
        value = _clean_line_value(raw)
        if value:
            normalized.append(f"- {value}")
    return "\n".join(normalized) if normalized else default_line


def _merge_price_rows(section_text: str, symbols: list[str], prices: dict[str, float]) -> str:
    price_rows = _format_symbol_prices(symbols, prices)
    if not price_rows:
        return section_text
    prefixed_rows = "\n".join(f"- {row[2:]}" if row.startswith("- ") else f"- {row}" for row in price_rows.splitlines())
    return section_text + "\n- Live price snapshot:\n" + prefixed_rows


async def _analyze_and_notify_user(db: AsyncSession, user: User, positions: list[PortfolioPosition]) -> None:
    uid = user.id
    goal_text = f"User's goal: {user.portfolio_goal}" if user.portfolio_goal else "User has not set a goal."
    portfolio_lines = "No positions." if not positions else "\n".join(
        f"- {p.symbol.upper()}: {p.quantity} @ {p.entry_price}" for p in positions
    )
    portfolio_text = goal_text + "\n" + portfolio_lines

    prices = fetch_crypto_prices(limit=250)
    held_symbols = sorted({(p.symbol or "").upper() for p in positions if (p.symbol or "").strip()})
    held_crypto_symbols = [sym for sym in held_symbols if sym in prices]
    held_non_crypto_symbols = [sym for sym in held_symbols if sym not in prices]
    portfolio_prices_section = _portfolio_prices_markdown(positions, prices)
    non_crypto_note = ""
    if held_non_crypto_symbols:
        non_crypto_note = (
            "- Non-crypto holdings (web/news-only analysis, no guaranteed live feed): "
            + ", ".join(held_non_crypto_symbols)
        )
        portfolio_prices_section = portfolio_prices_section + "\n" + non_crypto_note
    portfolio_value = sum(float(p.quantity) * prices.get((p.symbol or "").upper(), 0.0) for p in positions)
    goal_amount = _extract_goal_amount(user.portfolio_goal or "")
    goal_hint = ""
    if goal_amount is not None:
        gap = goal_amount - portfolio_value
        goal_hint = (
            f"Goal target amount: ${goal_amount:,.2f}. Estimated current portfolio value from live-priced holdings: ${portfolio_value:,.2f}. "
            f"Gap to target: ${gap:,.2f}."
        )

    retriever = get_rag_retriever()
    try:
        docs = retriever.invoke("portfolio specific crypto equities forex emerging markets latest news analysis")
        seen_sources = set()
        unique_docs = []
        for d in docs:
            src = (d.metadata.get("source") or "").strip() or (d.metadata.get("title") or "")[:80]
            if src and src not in seen_sources:
                seen_sources.add(src)
                unique_docs.append(d)
            elif not src:
                unique_docs.append(d)
        docs = unique_docs[:8]
        news_context = "\n\n".join(d.page_content[:600] for d in docs) if docs else "No recent news in knowledge base."
    except Exception:
        news_context = "News retrieval failed."
    targeted_web_context = _build_targeted_web_context(held_symbols, goal_text, news_context)

    prompt = f"""You are a concise markets analyst. Analyze this user's portfolio only and produce portfolio-aware sections.

Portfolio (user holdings):
{portfolio_text}

Live crypto prices for held symbols only:
{portfolio_prices_section or "No held symbols were found in the crypto live-price feed."}
{non_crypto_note}

Recent news context:
{news_context[:3000]}

Targeted web intelligence:
{targeted_web_context[:2200]}

Rules:
- Never dump all market prices.
- Mention only portfolio symbols or clearly related same-domain candidates.
- For crypto tickers with known live prices, include the price.
- For non-crypto assets, use web/news narrative and write "Price: N/A (web/news-only)" if needed.
- Keep each section concise and useful.
- Analyze the goal realism using estimated portfolio value and timeline context from user goal. If target appears aggressive, explicitly say so.

Goal realism context:
{goal_hint or f"Estimated current portfolio value from live-priced holdings: ${portfolio_value:,.2f}."}

Respond in markdown with EXACT headers in this order:
## Portfolio Prices
## Suggested Buys
## Hold/Sell Review
## Watchlist
## Market Analysis
## Recommendation

Under recommendation include one of BUY / HOLD / SELL and one concrete action sentence."""

    llm = get_llm()
    messages = [
        SystemMessage(
            content="You are a portfolio notification analyst. Follow requested markdown section headers exactly."
        ),
        HumanMessage(content=prompt),
    ]
    response = await llm.ainvoke(messages)
    text = sanitize_assistant_visible_text((response.content or "").strip())

    title = "Portfolio & market update"
    recommendation_section = _header_section(text, "Recommendation")
    recommendation = ""
    match = re.search(r"\b(BUY|HOLD|SELL)\b", recommendation_section.upper())
    if match:
        recommendation = match.group(1)
    suggested_action = ""
    for line in recommendation_section.splitlines():
        clean = _clean_line_value(line)
        normalized = re.sub(r"[^A-Z]", "", clean.upper())
        if clean and normalized not in {"BUY", "HOLD", "SELL"}:
            suggested_action = clean
            break
    if not suggested_action:
        action_match = re.search(r"(?i)(?:concrete action|action)\s*:\s*(.+)", recommendation_section)
        if action_match:
            suggested_action = action_match.group(1).strip()
    if not suggested_action:
        suggested_action = "Review position sizing and rebalance only if your risk budget allows."

    buys_section = _header_section(text, "Suggested Buys")
    hold_sell_section = _header_section(text, "Hold/Sell Review")
    watchlist_section = _header_section(text, "Watchlist")
    analysis_section = _header_section(text, "Market Analysis")
    buy_symbols = _extract_symbols(buys_section)
    hold_sell_symbols = _extract_symbols(hold_sell_section) or held_crypto_symbols
    watch_symbols = _extract_symbols(watchlist_section)
    normalized_buys = _normalize_section(
        buys_section,
        "- No suggested buys based on current portfolio and market context.",
    )
    normalized_hold_sell = _normalize_section(
        hold_sell_section,
        "- Hold core positions unless risk conditions change.",
    )
    normalized_watchlist = _normalize_section(
        watchlist_section,
        "- No additional watchlist names at this time.",
    )
    normalized_analysis = _normalize_section(
        analysis_section,
        "- Market is range-bound; monitor catalysts and volatility before adding risk.",
    )
    normalized_buys = _merge_price_rows(normalized_buys, buy_symbols, prices)
    normalized_hold_sell = _merge_price_rows(normalized_hold_sell, hold_sell_symbols, prices)
    normalized_watchlist = _merge_price_rows(normalized_watchlist, watch_symbols, prices)
    body = "\n\n".join(
        [
            "## Portfolio Prices",
            portfolio_prices_section,
            "## Suggested Buys",
            normalized_buys,
            "## Hold/Sell Review",
            normalized_hold_sell,
            "## Watchlist",
            normalized_watchlist,
            "## Market Analysis",
            normalized_analysis,
            "## Recommendation",
            f"- Recommendation: {recommendation or 'HOLD'}\n- Action: {suggested_action}",
        ]
    ).strip()

    notif = Notification(
        user_id=uid,
        title=title,
        body=body,
        suggested_action=suggested_action,
        read=False,
    )
    db.add(notif)
    await db.flush()
    logger.info("Analysis job: created notification for user %s", uid)
    send_email(
        user.email,
        title,
        body,
        suggested_action,
        allow_default_recipient=False,
        skip_sender_recipient=True,
    )
    send_whatsapp(title, body, suggested_action)


async def job_analyze_and_notify():
    """For each user in the database, run portfolio + news analysis and create a notification."""
    try:
        async with async_session_factory() as db:
            r = await db.execute(
                select(User).where(
                    User.google_sub.is_not(None),
                    User.email.is_not(None),
                    User.email != "",
                )
            )
            users = r.scalars().all()
            logger.info(
                "[scheduler] ts=%s job=analyze_and_notify phase=users_loaded count=%s",
                utc_iso(),
                len(users),
            )

            for user in users:
                try:
                    pos_result = await db.execute(
                        select(PortfolioPosition).where(PortfolioPosition.user_id == user.id)
                    )
                    positions = pos_result.scalars().all()
                    if not positions:
                        logger.info(
                            "[scheduler] skipping user %s: no portfolio positions",
                            user.id,
                        )
                        continue
                    await _analyze_and_notify_user(db, user, positions)
                except Exception as e:
                    logger.exception("Analysis for user %s failed: %s", user.id, e)
            await db.commit()
    except Exception as e:
        logger.exception("Analysis job error: %s", e)


async def job_news_then_analyze():
    """Run news fetch + ingest first, then analysis, so the notification always uses latest news."""
    t0 = time.perf_counter()
    logger.info("[scheduler] ts=%s job=news_then_analyze phase=start", utc_iso())
    await job_fetch_news_and_ingest()
    t1 = time.perf_counter()
    logger.info(
        "[scheduler] ts=%s job=news_then_analyze phase=after_news_ingest elapsed_s=%.2f",
        utc_iso(),
        t1 - t0,
    )
    await job_analyze_and_notify()
    t2 = time.perf_counter()
    logger.info(
        "[scheduler] ts=%s job=news_then_analyze phase=complete total_s=%.2f analyze_phase_s=%.2f",
        utc_iso(),
        t2 - t0,
        t2 - t1,
    )


def start_scheduler():
    """Schedule news+analysis by cron expression. Manual trigger: POST /api/jobs/trigger-analysis"""
    if not settings.SCHEDULER_ENABLED:
        logger.info("Scheduler disabled (SCHEDULER_ENABLED=false)")
        return
    if scheduler.running:
        logger.info("Scheduler already running; skipping restart")
        return

    cron_expr = (settings.SCHEDULER_CRON or "").strip()
    try:
        trigger = CronTrigger.from_crontab(cron_expr)
    except Exception as e:
        logger.warning("Invalid SCHEDULER_CRON=%r (%s); falling back to default twice-daily", cron_expr, e)
        cron_expr = "0 9,21 * * *"
        trigger = CronTrigger.from_crontab(cron_expr)

    scheduler.add_job(
        job_news_then_analyze,
        trigger,
        id="news_then_analyze",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Scheduler started: cron=%s — news ingest + per-user analysis", cron_expr)


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown(wait=False)
