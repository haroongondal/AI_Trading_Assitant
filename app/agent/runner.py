"""
ReAct-style agent: LLM with tools, stream tokens to client; when LLM calls a tool, run it and continue.
JS parallel: like an async pipeline that yields chunks and handles side effects (tool runs).
"""
import logging
from collections.abc import AsyncGenerator
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.tools import BaseTool

from app.services.ollama_client import get_llm
from app.tools.rag import query_rag
from app.tools.memory import memory_tools
from app.tools.web_search import web_search_tool
from app.tools.portfolio import (
    get_portfolio,
    add_position,
    delete_position,
    update_position,
    set_portfolio_goal,
)

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a helpful AI trading assistant. You have access to these tools:
- query_rag: search the knowledge base for crypto/forex news and analysis
- remember: store a fact or preference the user wants you to remember
- recall: recall stored facts and recent conversation
- search_web: search the web for current market info
- get_portfolio: get the user's portfolio positions and their stated goal (includes position id per row)
- add_position: add a new position (symbol, quantity, optional notes). Use when the user asks to add a coin.
- delete_position: remove a position by symbol. Use when the user asks to remove or sell a coin.
- update_position: change an existing position by id (position_id, optional quantity, entry_price, notes). Use when the user asks to change quantity or entry price of an existing position (e.g. "update BTC 0.002 to 0.003", "change position id 2 to 0.005"). Call get_portfolio first to get position ids if needed.
- set_portfolio_goal: update the user's portfolio goal (text). Use when the user states what they want to achieve.

When the user asks to update their portfolio (e.g. "add 2 ETH", "remove BTC", "update BTC quantity to 0.003", "my goal is long-term growth"), call the appropriate tool then confirm. Be concise and professional."""

TOOLS: list[BaseTool] = [
    query_rag,
    web_search_tool,
    get_portfolio,
    add_position,
    delete_position,
    update_position,
    set_portfolio_goal,
    *memory_tools,
]
TOOL_MAP = {t.name: t for t in TOOLS}


async def _run_tool(name: str, args: dict) -> str:
    """Invoke a tool by name with given args. Handles async tools."""
    tool = TOOL_MAP.get(name)
    if not tool:
        return f"Unknown tool: {name}"
    try:
        if hasattr(tool, "ainvoke"):
            result = await tool.ainvoke(args)
        else:
            result = tool.invoke(args)
        return str(result) if result is not None else "Done."
    except Exception as e:
        logger.exception("Tool %s error: %s", name, e)
        return f"Tool error: {e}"


async def stream_agent_response(
    message: str,
    history: list[dict],
) -> AsyncGenerator[str | dict, None]:
    """
    Run agent with tools; yield content tokens. When LLM returns tool_calls, run them and continue.
    Yields: content chunks (strings) for the assistant message, or dict with event/data for status (e.g. tool progress).
    """
    llm = get_llm().bind_tools(TOOLS)
    messages: list = [SystemMessage(content=SYSTEM_PROMPT)]
    for h in history:
        role, content = h.get("role", ""), h.get("content", "")
        if role == "user":
            messages.append(HumanMessage(content=content))
        elif role == "assistant":
            messages.append(AIMessage(content=content))
    messages.append(HumanMessage(content=message))

    max_turns = 8
    turn = 0
    while turn < max_turns:
        turn += 1
        chunks: list[AIMessageChunk] = []
        async for chunk in llm.astream(messages):
            if isinstance(chunk, AIMessageChunk):
                if chunk.content:
                    yield chunk.content
                chunks.append(chunk)

        # Merge chunks to get full tool_calls (streaming may send partial tool_call_chunks)
        merged = chunks[0] if chunks else None
        for c in chunks[1:]:
            merged = merged + c if merged else c
        current_tool_calls = getattr(merged, "tool_calls", []) or []
        full_content = (getattr(merged, "content", "") or "") if merged else ""

        if not current_tool_calls:
            break

        # Send tool status as a separate event so the client can show it apart from the answer
        yield {"event": "status", "data": "*Checking portfolio and tools...*"}
        # Run tool calls and append results to messages
        tool_messages = []
        for tc in current_tool_calls:
            name = tc.get("name", "") if isinstance(tc, dict) else getattr(tc, "name", "")
            args = tc.get("args", {}) if isinstance(tc, dict) else getattr(tc, "args", {}) or {}
            tid = tc.get("id", "") if isinstance(tc, dict) else getattr(tc, "id", "")
            result = await _run_tool(name, args)
            tool_messages.append(ToolMessage(content=result, tool_call_id=tid or name))
        messages.append(AIMessage(content=full_content, tool_calls=current_tool_calls))
        messages.extend(tool_messages)

    # If we broke out with no content yielded (e.g. only tool calls), yield a minimal response
    # (already yielded content above during the stream)
    return
