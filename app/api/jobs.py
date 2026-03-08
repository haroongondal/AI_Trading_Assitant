"""
Manual trigger for scheduled jobs (for demo/testing). Production would protect with auth.
"""
import logging
from fastapi import APIRouter

from app.jobs.scheduler import job_fetch_news_and_ingest, job_analyze_and_notify

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/trigger-news")
async def trigger_news():
    """Run news fetch + RAG ingest once. Useful for demo."""
    await job_fetch_news_and_ingest()
    return {"ok": True, "message": "News fetch and ingest completed."}


@router.post("/trigger-analysis")
async def trigger_analysis():
    """Run portfolio + news analysis and create notification once. Useful for demo."""
    await job_analyze_and_notify()
    return {"ok": True, "message": "Analysis and notification created."}
