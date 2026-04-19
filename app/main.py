"""
FastAPI application entry. JS parallel: like Express app in index.js - CORS, router mounting.
"""
import os
import warnings

# Before chromadb (via RAG) loads: disable broken/noisy product telemetry in some envs.
os.environ.setdefault("ANONYMIZED_TELEMETRY", "0")
os.environ.setdefault("CHROMA_TELEMETRY_ENABLED", "false")
os.environ.setdefault("CHROMA_ANONYMIZED_TELEMETRY", "false")

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.api import api_router
from app.db.session import init_db
from app.jobs import start_scheduler, stop_scheduler

_root_level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
logging.basicConfig(
    level=_root_level,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logging.getLogger("app").setLevel(_root_level)
# Chroma/PostHog mismatch can spam ERROR on every import; telemetry is off above.
logging.getLogger("chromadb.telemetry").disabled = True
logging.getLogger("chromadb.telemetry.product.posthog").disabled = True
# Per-request GET lines from price tools drown real errors and make the app feel "stuck".
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("primp").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

warnings.filterwarnings(
    "ignore",
    message=".*Chroma.*deprecated.*",
    category=DeprecationWarning,
)


def _warn_if_oauth_frontend_url_misconfigured() -> None:
    """After Google login the API redirects to FRONTEND_URL; localhost there breaks production."""
    if not (
        settings.GOOGLE_CLIENT_ID.strip()
        and settings.GOOGLE_CLIENT_SECRET.strip()
        and settings.GOOGLE_REDIRECT_URI.strip()
    ):
        return
    fu = settings.FRONTEND_URL.strip().lower()
    gr = settings.GOOGLE_REDIRECT_URI.strip().lower()
    looks_local_frontend = "localhost" in fu or fu.startswith("http://127.")
    looks_prod_callback = gr.startswith("https://") and "localhost" not in gr and "127.0.0.1" not in gr
    if looks_local_frontend and looks_prod_callback:
        logger.warning(
            "FRONTEND_URL=%r but GOOGLE_REDIRECT_URI looks like production. "
            "Successful Google sign-in will redirect users to FRONTEND_URL — set it to your live site (https://...), "
            "restart the API, and use AUTH_COOKIE_SECURE=true behind HTTPS.",
            settings.FRONTEND_URL,
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: init DB and scheduler. Shutdown: stop scheduler."""
    await init_db()
    logger.info("Database initialized")
    logger.warning("CORS is open to all origins (allow_origin_regex=.*); tighten before production.")
    _warn_if_oauth_frontend_url_misconfigured()
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
# Temporary: permit any Origin (reflects request origin). Needed with allow_credentials=True;
# wildcard allow_origins=["*"] is invalid together with credentials per browser rules.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[],
    allow_origin_regex=".*",
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
