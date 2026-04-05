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
from app.tools.memory import add_to_conversation

logger = logging.getLogger(__name__)
router = APIRouter()


async def _sse_stream(message: str, history: list[dict], user_id: str):
    """Async generator: yield SSE events. Status events (e.g. tool progress) use event type 'status'; message chunks use default event."""
    token = set_current_user_id(user_id)
    try:
        async for item in stream_agent_response(message, history):
            if isinstance(item, dict) and "event" in item and "data" in item:
                yield {"event": item["event"], "data": item["data"]}
            else:
                yield {"data": item}
        add_to_conversation(user_id, "user", message)
    except Exception as e:
        logger.exception("Chat stream error: %s", e)
        yield {"data": f"[Error: {str(e)}]"}
    finally:
        reset_current_user_id(token)


@router.post("/stream")
async def chat_stream(request: Request, chat_req: ChatRequest):
    """Stream assistant reply as Server-Sent Events. Uses agent with RAG, memory, web search, portfolio tools."""
    try:
        user_id = resolve_effective_user_id(request)
        history_dicts = [m.model_dump() for m in chat_req.history]
        return EventSourceResponse(
            _sse_stream(chat_req.message, history_dicts, user_id),
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )
    except Exception as e:
        logger.exception("Chat stream error: %s", e)
        raise HTTPException(status_code=500, detail="Stream failed")
