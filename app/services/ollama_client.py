"""
Ollama LLM client. JS parallel: like a small service that calls fetch(ollamaUrl) and returns/streams the response.
"""
import logging
from langchain_ollama import ChatOllama

from app.core.config import settings
from app.services.model_registry import get_model_spec

logger = logging.getLogger(__name__)


def get_llm(model_id: str | None = None):
    """Return a configured chat model client for the selected provider."""
    spec = get_model_spec(model_id)
    if spec.transport == "ollama":
        kwargs: dict = {
            "base_url": spec.base_url or settings.OLLAMA_BASE_URL,
            "model": spec.model or settings.OLLAMA_MODEL,
            "temperature": settings.OLLAMA_TEMPERATURE,
        }
        if settings.OLLAMA_NUM_CTX is not None:
            kwargs["num_ctx"] = settings.OLLAMA_NUM_CTX
        return ChatOllama(**kwargs)

    if spec.transport == "openai_compatible":
        if not spec.api_key:
            raise ValueError(f"Model '{spec.id}' is not configured: missing API key.")
        try:
            from langchain_openai import ChatOpenAI
        except Exception as e:
            raise ValueError(
                "OpenAI-compatible providers require 'langchain-openai'. "
                "Run `pip install -e .` in backend/ to install updated dependencies."
            ) from e
        # Groq OpenAI-compat extras: strip chain-of-thought ("harmony" reasoning channel)
        # from streamed content so visible output is the final answer only (fixes gpt-oss
        # draft-redraft leaks). Also cap reasoning budget for reasoning models.
        extra_body: dict = {}
        base_url_lower = (spec.base_url or "").lower()
        model_lower = (spec.model or "").lower()
        # Only gpt-oss accepts reasoning_format; other Groq models return 400 if it is sent.
        if "groq.com" in base_url_lower and "gpt-oss" in model_lower:
            extra_body["reasoning_format"] = "hidden"
            extra_body["reasoning_effort"] = "medium"
        kwargs: dict = {
            "model": spec.model,
            "base_url": spec.base_url,
            "api_key": spec.api_key,
            "temperature": settings.OLLAMA_TEMPERATURE,
            "streaming": True,
        }
        if extra_body:
            kwargs["extra_body"] = extra_body
        return ChatOpenAI(**kwargs)

    raise ValueError(f"Unsupported transport for model '{spec.id}'")
