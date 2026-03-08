"""
APScheduler: fetch news, ingest into RAG, then run portfolio + news analysis and create notifications.
JS parallel: like setInterval or node-cron jobs that run in the background.
"""
import logging
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

from app.core.config import settings
from app.db.session import async_session_factory
from app.db.models import PortfolioPosition, Notification, User
from app.services.news_fetcher import fetch_news
from app.services.rag_ingest import ingest_documents
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
            # Ensure user exists
            r = await db.execute(select(User).where(User.id == settings.DEFAULT_USER_ID))
            user = r.scalar_one_or_none()
            if not user:
                user = User(id=settings.DEFAULT_USER_ID, name="Demo User")
                db.add(user)
                await db.flush()

            # Portfolio summary
            r = await db.execute(select(PortfolioPosition).where(PortfolioPosition.user_id == settings.DEFAULT_USER_ID))
            positions = r.scalars().all()
            portfolio_text = "No positions." if not positions else "\n".join(
                f"- {p.symbol}: {p.quantity} @ {p.entry_price}" for p in positions
            )

            # Latest news context from RAG
            retriever = get_rag_retriever()
            try:
                docs = retriever.invoke("latest crypto and forex news market impact")
                news_context = "\n\n".join(d.page_content[:500] for d in docs[:5]) if docs else "No recent news in knowledge base."
            except Exception:
                news_context = "News retrieval failed."

            prompt = f"""Based on the following portfolio and recent news context, write a short analysis and one suggested next step for the user.
Keep it to 2-3 sentences for the analysis and one clear suggested action.

Portfolio:
{portfolio_text}

Recent news context:
{news_context[:3000]}

Respond in this exact format (no extra labels):
ANALYSIS: <your 2-3 sentence analysis>
SUGGESTED ACTION: <one clear suggested next step>"""

            llm = get_llm()
            messages = [SystemMessage(content="You are a concise trading analyst. Output only the ANALYSIS and SUGGESTED ACTION lines."), HumanMessage(content=prompt)]
            response = await llm.ainvoke(messages)
            text = (response.content or "").strip()

            # Parse into title, body, suggested_action
            title = "Portfolio & market update"
            body = text
            suggested_action = None
            if "SUGGESTED ACTION:" in text:
                parts = text.split("SUGGESTED ACTION:")
                body = parts[0].replace("ANALYSIS:", "").strip()
                suggested_action = parts[1].strip() if len(parts) > 1 else None
            elif "ANALYSIS:" in text:
                body = text.replace("ANALYSIS:", "").strip()

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
    except Exception as e:
        logger.exception("Analysis job error: %s", e)


def start_scheduler():
    """Schedule jobs: news+ingest and analyze+notify 2x daily (e.g. 08:00 and 18:00)."""
    scheduler.add_job(
        job_fetch_news_and_ingest,
        CronTrigger(hour=8, minute=0),
        id="fetch_news",
    )
    scheduler.add_job(
        job_fetch_news_and_ingest,
        CronTrigger(hour=18, minute=0),
        id="fetch_news_evening",
    )
    scheduler.add_job(
        job_analyze_and_notify,
        CronTrigger(hour=8, minute=15),
        id="analyze_notify",
    )
    scheduler.add_job(
        job_analyze_and_notify,
        CronTrigger(hour=18, minute=15),
        id="analyze_notify_evening",
    )
    scheduler.start()
    logger.info("Scheduler started (news 08:00/18:00, analysis 08:15/18:15)")


def stop_scheduler():
    scheduler.shutdown(wait=False)
