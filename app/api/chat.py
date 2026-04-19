"""
Chat endpoint with LLM response streaming via SSE.
JS parallel: like a route that does res.write(chunk) in a loop; here we yield chunks to EventSourceResponse.
"""
import logging
from fastapi import APIRouter, HTTPException, Request
from sse_starlette.sse import EventSourceResponse

from app.api.deps import resolve_effective_user_id
from app.core.auth_context import reset_current_user_id, set_current_user_id
from app.models.schemas import ChatRequest
from app.agent.runner import stream_agent_response
from app.services.model_registry import (
    chat_fallback_chain,
    classify_model_error,
    extract_error_status_code,
    list_frontend_models,
)
from app.tools.memory import add_to_conversation

logger = logging.getLogger(__name__)
router = APIRouter()


async def _sse_stream(message: str, history: list[dict], user_id: str, model_id: str | None):
    """Async generator: yield SSE events. Status events (e.g. tool progress) use event type 'status'; message chunks use default event."""
    token = set_current_user_id(user_id)
    try:
        chain = chat_fallback_chain(model_id)
        logger.info("chat_fallback_start user=%s selected=%s chain=%s", user_id, model_id, chain)
        for idx, candidate in enumerate(chain):
            try:
                logger.info(
                    "chat_model_attempt user=%s attempt=%s/%s model=%s",
                    user_id,
                    idx + 1,
                    len(chain),
                    candidate,
                )
                async for item in stream_agent_response(message, history, candidate):
                    if isinstance(item, dict) and "event" in item and "data" in item:
                        yield {"event": item["event"], "data": item["data"]}
                    else:
                        yield {"data": item}
                logger.info("chat_model_success user=%s model=%s", user_id, candidate)
                add_to_conversation(user_id, "user", message)
                return
            except Exception as e:
                status_code = extract_error_status_code(e)
                category = classify_model_error(e)
                logger.warning(
                    "chat_model_failed user=%s attempt=%s/%s model=%s status=%s category=%s err=%s",
                    user_id,
                    idx + 1,
                    len(chain),
                    candidate,
                    status_code,
                    category,
                    e,
                )
                if category == "quota_or_rate_limit" or status_code == 429:
                    yield {
                        "event": "rate_limit",
                        "data": (
                            f"Rate limit reached for {candidate}. Please wait a moment and try again, "
                            "or switch to another model."
                        ),
                    }
                    return
                if category == "context_too_large" or status_code == 413:
                    yield {
                        "data": (
                            f"That model rejected the request as too large (often a long chat or large paste). "
                            f"Try {candidate} with a shorter message, start a new thread, or pick a tool-capable model like Groq GPT-OSS 120B."
                        ),
                    }
                    return
                if idx == len(chain) - 1:
                    raise
                continue
    except Exception as e:
        logger.exception("Chat stream error: %s", e)
        yield {"data": "Something went wrong. Please try again."}
    finally:
        reset_current_user_id(token)


@router.post("/stream")
async def chat_stream(request: Request, chat_req: ChatRequest):
    """Stream assistant reply as Server-Sent Events. Uses agent with RAG, memory, web search, portfolio tools."""
    try:
        user_id = resolve_effective_user_id(request)
        history_dicts = [m.model_dump() for m in chat_req.history]
        return EventSourceResponse(
            _sse_stream(chat_req.message, history_dicts, user_id, chat_req.model_id),
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )
    except Exception as e:
        logger.exception("Chat stream error: %s", e)
        raise HTTPException(status_code=500, detail="Stream failed")


@router.get("/models")
async def chat_models():
    return {"models": list_frontend_models()}
