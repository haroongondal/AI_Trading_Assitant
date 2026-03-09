"""
APScheduler: fetch news, ingest into RAG, then run portfolio + news analysis and create notifications.
JS parallel: like setInterval or node-cron jobs that run in the background.
"""
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.db.session import async_session_factory
from app.db.models import PortfolioPosition, Notification, User
from app.services.news_fetcher import fetch_news
from app.services.rag_ingest import ingest_documents
from app.services.price_fetcher import fetch_crypto_prices, format_prices_for_prompt
from app.services.whatsapp import send_notification as send_whatsapp
from app.tools.rag import get_rag_retriever
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


async def job_analyze_and_notify():
    """Load user portfolio + latest RAG context, call LLM, create notification."""
    try:
        async with async_session_factory() as db:
            # Ensure user exists (handle race with portfolio/scheduler)
            r = await db.execute(select(User).where(User.id == settings.DEFAULT_USER_ID))
            user = r.scalar_one_or_none()
            if not user:
                try:
                    user = User(id=settings.DEFAULT_USER_ID, name="Demo User")
                    db.add(user)
                    await db.flush()
                except IntegrityError:
                    await db.rollback()
                    r = await db.execute(select(User).where(User.id == settings.DEFAULT_USER_ID))
                    user = r.scalar_one_or_none()
                    if not user:
                        raise

            # Portfolio summary and goal
            goal_text = f"User's goal: {user.portfolio_goal}" if user.portfolio_goal else "User has not set a goal."
            r = await db.execute(select(PortfolioPosition).where(PortfolioPosition.user_id == settings.DEFAULT_USER_ID))
            positions = r.scalars().all()
            portfolio_text = "No positions." if not positions else "\n".join(
                f"- {p.symbol}: {p.quantity} @ {p.entry_price}" for p in positions
            )
            portfolio_text = goal_text + "\n" + portfolio_text

            # Current market prices (for context and recommendation)
            prices = fetch_crypto_prices()
            price_text = format_prices_for_prompt(prices)

            # Latest news context from RAG (run after news job so store is fresh)
            retriever = get_rag_retriever()
            try:
                docs = retriever.invoke("crypto forex news market price impact analysis")
                # Deduplicate by source URL so we don't pass the same article multiple times
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

            prompt = f"""You are a concise crypto trading analyst. Use the data below to produce a short update.

Portfolio (user holdings):
{portfolio_text}

{price_text}

Recent news context:
{news_context[:3000]}

Provide:
1) A short analysis (2-4 sentences) that mentions current price for any assets the user holds and an expected price range or direction for those assets in the next few days or weeks based on current news and market context.
2) A clear recommendation: SELL, BUY, or HOLD.
3) If your recommendation is BUY, list specific coins to buy (e.g. ETH, SOL, ADA) and a brief reason or expected upside for each. If SELL or HOLD, skip this.
4) One concrete suggested action (e.g. "Buy 0.5 ETH in the next dip" or "Hold current positions" or "Sell 30% of BTC").

Respond using exactly these labels (no extra text before/after):
ANALYSIS: <analysis with current and expected price outlook>
RECOMMENDATION: SELL | BUY | HOLD
COINS TO BUY: <only if BUY: list specific coins and brief reason, e.g. "ETH - upgrade catalyst; SOL - momentum">
SUGGESTED ACTION: <one clear next step>"""

            llm = get_llm()
            messages = [
                SystemMessage(content="You are a crypto trading analyst. Output only the four lines: ANALYSIS, RECOMMENDATION, COINS TO BUY (if BUY), SUGGESTED ACTION."),
                HumanMessage(content=prompt),
            ]
            response = await llm.ainvoke(messages)
            text = (response.content or "").strip()

            # Parse labelled sections (allow multiline content until next label)
            def _section(tag: str) -> str:
                if tag not in text:
                    return ""
                start = text.index(tag) + len(tag)
                rest = text[start:].strip()
                for other in ("ANALYSIS:", "RECOMMENDATION:", "COINS TO BUY:", "SUGGESTED ACTION:"):
                    if other in rest:
                        rest = rest.split(other)[0]
                return rest.strip()

            title = "Portfolio & market update"
            analysis = _section("ANALYSIS:")
            recommendation = _section("RECOMMENDATION:").split()[0] if _section("RECOMMENDATION:") else ""
            coins_to_buy = _section("COINS TO BUY:")
            suggested_action = _section("SUGGESTED ACTION:")

            body_parts = []
            if price_text and "unavailable" not in price_text.lower():
                body_parts.append(price_text)
            if analysis:
                body_parts.append("Analysis: " + analysis)
            if recommendation:
                body_parts.append("Recommendation: " + recommendation)
            if coins_to_buy and recommendation.upper() == "BUY":
                body_parts.append("Coins to consider: " + coins_to_buy)
            body = "\n\n".join(body_parts) if body_parts else text

            notif = Notification(
                user_id=settings.DEFAULT_USER_ID,
                title=title,
                body=body,
                suggested_action=suggested_action,
                read=False,
            )
            db.add(notif)
            await db.commit()
            logger.info("Analysis job: created notification for user %s", settings.DEFAULT_USER_ID)
            send_whatsapp(title, body, suggested_action)
    except Exception as e:
        logger.exception("Analysis job error: %s", e)


async def job_news_then_analyze():
    """Run news fetch + ingest first, then analysis, so the notification always uses latest news."""
    await job_fetch_news_and_ingest()
    await job_analyze_and_notify()


def start_scheduler():
    """Schedule jobs: twice daily (configurable). Manual trigger: POST /api/jobs/trigger-analysis"""
    h1, m1 = settings.SCHEDULER_HOUR_1, settings.SCHEDULER_MINUTE_1
    h2, m2 = settings.SCHEDULER_HOUR_2, settings.SCHEDULER_MINUTE_2
    scheduler.add_job(
        job_news_then_analyze,
        CronTrigger(hour=h1, minute=m1),
        id="news_then_analyze_1",
    )
    scheduler.add_job(
        job_news_then_analyze,
        CronTrigger(hour=h2, minute=m2),
        id="news_then_analyze_2",
    )
    scheduler.start()
    logger.info("Scheduler started (twice daily at %02d:%02d and %02d:%02d)", h1, m1, h2, m2)


def stop_scheduler():
    scheduler.shutdown(wait=False)
