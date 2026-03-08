"""
Ollama LLM client. JS parallel: like a small service that calls fetch(ollamaUrl) and returns/streams the response.
"""
import logging
from langchain_ollama import ChatOllama

from app.core.config import settings

logger = logging.getLogger(__name__)


def get_llm():
    """Return ChatOllama instance with project config. JS parallel: factory that returns a configured client."""
    return ChatOllama(
        base_url=settings.OLLAMA_BASE_URL,
        model=settings.OLLAMA_MODEL,
        temperature=0.3,
    )
