from fastapi import APIRouter
from .health import router as health_router
from .chat import router as chat_router
from .portfolio import router as portfolio_router
from .notifications import router as notifications_router
from .jobs import router as jobs_router
from .coins import router as coins_router

api_router = APIRouter()
api_router.include_router(health_router, prefix="/health", tags=["health"])
api_router.include_router(chat_router, prefix="/chat", tags=["chat"])
api_router.include_router(portfolio_router, prefix="/portfolio", tags=["portfolio"])
api_router.include_router(notifications_router, prefix="/notifications", tags=["notifications"])
api_router.include_router(jobs_router, prefix="/jobs", tags=["jobs"])
api_router.include_router(coins_router, prefix="/coins", tags=["coins"])
