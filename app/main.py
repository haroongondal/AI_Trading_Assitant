"""
FastAPI application entry. JS parallel: like Express app in index.js - CORS, router mounting.
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.api import api_router
from app.db.session import init_db
from app.jobs import start_scheduler, stop_scheduler

# Structured logging for production-style debugging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: init DB and scheduler. Shutdown: stop scheduler."""
    await init_db()
    logger.info("Database initialized")
    start_scheduler()
    yield
    stop_scheduler()
    logger.info("Shutting down")


app = FastAPI(
    title="AI Trading Assistant API",
    description="Production-grade AI trading assistant with RAG, memory, tools, and streaming.",
    version="1.0.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["*"],
)
app.include_router(api_router, prefix=settings.API_V1_PREFIX)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Structured error response for production debugging. JS parallel: like Express error middleware."""
    logger.exception("Unhandled error: %s", exc)
    return JSONResponse(
        status_code=500,
        content={"detail": str(exc), "type": type(exc).__name__},
    )


@app.get("/health")
async def root_health():
    """Simple liveness probe for Docker/K8s."""
    return {"status": "ok"}
