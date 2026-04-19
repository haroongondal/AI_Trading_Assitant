from dataclasses import dataclass
from importlib.util import find_spec
from typing import Any

from app.core.config import settings


@dataclass(frozen=True)
class ModelSpec:
    id: str
    provider: str
    label: str
    model: str
    speed_tag: str
    transport: str  # "ollama" | "openai_compatible"
    base_url: str | None = None
    api_key: str | None = None
    enabled: bool = True
    supports_tools: bool = True


def _k(v: str) -> str | None:
    return v.strip() or None


def get_model_specs() -> list[ModelSpec]:
    has_openai_compat = find_spec("langchain_openai") is not None
    groq_key = _k(settings.GROQ_API_KEY)

    specs = [
        ModelSpec(
            id="local-llama31",
            provider="Local Hosted",
            label="Llama 3.1",
            model=settings.OLLAMA_HOSTED_LLAMA31_MODEL,
            speed_tag="very slow",
            transport="ollama",
            base_url=settings.OLLAMA_BASE_URL,
            enabled=True,
            supports_tools=True,
        ),
        ModelSpec(
            id="google-gemini-2.0-flash",
            provider="Google AI Studio",
            label="Gemini 2.0 Flash",
            model="gemini-2.0-flash",
            speed_tag="fast",
            transport="openai_compatible",
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            api_key=_k(settings.GOOGLE_AI_STUDIO_API_KEY),
            enabled=bool(_k(settings.GOOGLE_AI_STUDIO_API_KEY)) and has_openai_compat,
            supports_tools=True,
        ),
        ModelSpec(
            id="groq-gpt-oss-120b",
            provider="Groq",
            label="GPT-OSS 120B (reasoning)",
            model="openai/gpt-oss-120b",
            speed_tag="fast",
            transport="openai_compatible",
            base_url="https://api.groq.com/openai/v1",
            api_key=groq_key,
            enabled=bool(groq_key) and has_openai_compat,
            supports_tools=True,
        ),
        ModelSpec(
            id="groq-gpt-oss-20b",
            provider="Groq",
            label="GPT-OSS 20B",
            model="openai/gpt-oss-20b",
            speed_tag="very fast",
            transport="openai_compatible",
            base_url="https://api.groq.com/openai/v1",
            api_key=groq_key,
            enabled=bool(groq_key) and has_openai_compat,
            supports_tools=True,
        ),
        ModelSpec(
            id="groq-llama-3.3-70b",
            provider="Groq",
            label="Llama 3.3 70B Versatile",
            model="llama-3.3-70b-versatile",
            speed_tag="very fast",
            transport="openai_compatible",
            base_url="https://api.groq.com/openai/v1",
            api_key=groq_key,
            enabled=bool(groq_key) and has_openai_compat,
            supports_tools=True,
        ),
        ModelSpec(
            id="groq-llama-3.1-8b",
            provider="Groq",
            label="Llama 3.1 8B Instant",
            model="llama-3.1-8b-instant",
            speed_tag="very fast",
            transport="openai_compatible",
            base_url="https://api.groq.com/openai/v1",
            api_key=groq_key,
            enabled=bool(groq_key) and has_openai_compat,
            supports_tools=True,
        ),
    ]
    return specs


def default_model_id() -> str:
    visible = _visible_specs()
    preferred_non_local = next((m for m in visible if m.id != "local-llama31"), None)
    if preferred_non_local:
        return preferred_non_local.id
    return "local-llama31"


def _is_allowed_model(model_id: str) -> bool:
    allowed = set(settings.CHAT_MODEL_WHITELIST or [])
    return model_id in allowed


def _visible_specs() -> list[ModelSpec]:
    allowed = [m for m in get_model_specs() if _is_allowed_model(m.id)]
    if settings.CHAT_MODELS_SHOW_CONFIGURED_ONLY:
        return [m for m in allowed if m.enabled]
    return allowed


def get_model_spec(model_id: str | None) -> ModelSpec:
    wanted = (model_id or "").strip() or default_model_id()
    all_by_id = {m.id: m for m in get_model_specs()}
    visible_by_id = {m.id: m for m in _visible_specs()}
    if wanted in visible_by_id:
        return visible_by_id[wanted]
    # Safe fallback to local model if visible/allowed; otherwise first visible.
    local = visible_by_id.get(default_model_id())
    if local:
        return local
    # If all models are hidden/misconfigured, return local spec for a clear runtime message.
    return all_by_id[default_model_id()]


def list_frontend_models() -> list[dict]:
    return [
        {
            "id": m.id,
            "provider": m.provider,
            "label": m.label,
            "speed_tag": m.speed_tag,
            "enabled": m.enabled,
            "supports_tools": m.supports_tools,
        }
        for m in _visible_specs()
    ]


def supports_tools(model_id: str | None) -> bool:
    return bool(get_model_spec(model_id).supports_tools)


def chat_fallback_chain(selected_model_id: str | None) -> list[str]:
    """Return a single chat model ID (no runtime fallback)."""
    visible = _visible_specs()
    ids = [m.id for m in visible]
    picked = (selected_model_id or "").strip()
    if picked and picked in ids:
        return [picked]

    default_id = default_model_id()
    if default_id in ids:
        return [default_id]
    if ids:
        return [ids[0]]
    return [default_id]


def extract_error_status_code(err: Exception) -> int | None:
    code = getattr(err, "status_code", None)
    if isinstance(code, int):
        return code
    response = getattr(err, "response", None)
    if response is not None:
        status = getattr(response, "status_code", None)
        if isinstance(status, int):
            return status
    body = str(err)
    for token in ("401", "403", "404", "429"):
        if f" {token} " in f" {body} ":
            return int(token)
    return None


def classify_model_error(err: Exception) -> str:
    code = extract_error_status_code(err)
    if code in (401, 403):
        return "auth_error"
    if code == 404:
        return "model_not_found"
    if code == 429:
        return "quota_or_rate_limit"
    if code == 413:
        return "context_too_large"
    msg = str(err).lower()
    if "invalid api key" in msg:
        return "auth_error"
    if "quota" in msg or "rate limit" in msg:
        return "quota_or_rate_limit"
    if "not found" in msg:
        return "model_not_found"
    if "too large" in msg or "413" in msg:
        return "context_too_large"
    if "failed to connect to ollama" in msg:
        return "local_backend_unreachable"
    return "unknown_error"


def model_log_meta(model_id: str | None) -> dict[str, Any]:
    spec = get_model_spec(model_id)
    return {
        "model_id": spec.id,
        "provider": spec.provider,
        "model": spec.model,
        "base_url": spec.base_url,
        "supports_tools": spec.supports_tools,
    }
