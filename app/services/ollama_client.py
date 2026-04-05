"""
Ollama LLM client. JS parallel: like a small service that calls fetch(ollamaUrl) and returns/streams the response.
"""
import logging
from langchain_ollama import ChatOllama

from app.core.config import settings

logger = logging.getLogger(__name__)


def get_llm():
    """Return ChatOllama instance with project config. JS parallel: factory that returns a configured client."""
    kwargs: dict = {
        "base_url": settings.OLLAMA_BASE_URL,
        "model": settings.OLLAMA_MODEL,
        "temperature": settings.OLLAMA_TEMPERATURE,
    }
    if settings.OLLAMA_NUM_CTX is not None:
        kwargs["num_ctx"] = settings.OLLAMA_NUM_CTX
    return ChatOllama(**kwargs)
