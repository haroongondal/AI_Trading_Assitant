"""
Manual trigger for scheduled jobs (for demo/testing). Production would protect with auth.

Curl examples:
  # Run full pipeline (news + analysis + notification, same as cron):
  curl -X POST http://localhost:8000/api/jobs/trigger-analysis

  # Run only news fetch + RAG ingest:
  curl -X POST http://localhost:8000/api/jobs/trigger-news
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
    """Run news fetch + ingest first, then portfolio + news analysis and create notification (in-app and WhatsApp if configured). Same as the twice-daily cron job. Curl: curl -X POST http://localhost:8000/api/jobs/trigger-analysis"""
    await job_fetch_news_and_ingest()
    await job_analyze_and_notify()
    return {"ok": True, "message": "News fetched, then analysis and notification created."}
