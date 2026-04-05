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

from app.jobs.scheduler import job_fetch_news_and_ingest, job_analyze_and_notify, job_news_then_analyze

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/trigger-news")
async def trigger_news():
    """Run news fetch + RAG ingest once. Useful for demo."""
    await job_fetch_news_and_ingest()
    return {"ok": True, "message": "News fetch and ingest completed."}


@router.post("/trigger-analysis")
async def trigger_analysis():
    """Same pipeline as the scheduled job (news ingest, then per-user analysis and notifications). Curl: curl -X POST http://localhost:8000/api/jobs/trigger-analysis"""
    await job_news_then_analyze()
    return {"ok": True, "message": "News fetched, then analysis and notification created."}
