"""
Chat endpoint with LLM response streaming via SSE.
JS parallel: like a route that does res.write(chunk) in a loop; here we yield chunks to EventSourceResponse.
"""
import logging
from fastapi import APIRouter, HTTPException
from sse_starlette.sse import EventSourceResponse

from app.core.config import settings
from app.models.schemas import ChatRequest
from app.agent.runner import stream_agent_response
from app.tools.memory import add_to_conversation

logger = logging.getLogger(__name__)
router = APIRouter()


async def _sse_stream(message: str, history: list[dict]):
    """Async generator: yield SSE events for each token from the agent (with tools)."""
    try:
        async for token in stream_agent_response(message, history):
            yield {"data": token}
        # Optionally persist to memory for recall
        add_to_conversation(settings.DEFAULT_USER_ID, "user", message)
        # Assistant message was streamed; we don't have full text here easily; recall uses conversation buffer
        # So we append assistant content in a simple way: we could accumulate in stream_agent_response and call add_to_conversation at the end, but for minimal change we skip storing assistant reply (recall still has user messages and stored facts).
    except Exception as e:
        logger.exception("Chat stream error: %s", e)
        yield {"data": f"[Error: {str(e)}]"}


@router.post("/stream")
async def chat_stream(request: ChatRequest):
    """Stream assistant reply as Server-Sent Events. Uses agent with RAG, memory, web search, portfolio tools."""
    try:
        history_dicts = [m.model_dump() for m in request.history]
        return EventSourceResponse(_sse_stream(request.message, history_dicts))
    except Exception as e:
        logger.exception("Chat stream error: %s", e)
        raise HTTPException(status_code=500, detail="Stream failed")
