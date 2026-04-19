"""
ReAct-style agent: LLM with tools, stream tokens to client; when LLM calls a tool, run it and continue.
"""
import asyncio
import logging
from collections.abc import AsyncGenerator

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool

from app.agent.stream_sanitize import sanitize_assistant_visible_text, stream_safe_text_delta
from app.core.config import settings
from app.services.ollama_client import get_llm
from app.services.model_registry import (
    classify_model_error,
    extract_error_status_code,
    get_model_spec,
    model_log_meta,
    supports_tools,
)
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
from app.tools.quote import get_quote

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a helpful AI trading assistant for crypto, US equities (e.g. NASDAQ/NYSE tickers like AAPL), Pakistan Stock Exchange (PSX) tickers, forex, and other markets the user mentions.

Tools:
- query_rag: search the knowledge base for news and analysis
- remember / recall: store and retrieve user facts and recent conversation context
- search_web: current market info (prices, headlines) when RAG is not enough
- get_quote: live spot price (USD) for a single ticker — crypto via CoinGecko, equities/PSX via web search. Use this BEFORE add_position/update_position whenever you need to derive a missing quantity or entry price from a cash amount.
- get_portfolio: user's positions (symbol, quantity, entry price, id) and their stated goal
- add_position: add a holding. symbol is a ticker (BTC, ETH, AAPL, PSX symbols, etc.).
- delete_position: remove a position by symbol
- update_position: change quantity, entry_price, or notes by position id (use get_portfolio for ids)
- set_portfolio_goal: free-text investment goal only (e.g. "double in 6 months", "grow to $800")

CRITICAL rules for portfolio tools:
- add_position quantity is ONLY what the user CURRENTLY OWNS (coins, shares, lots)—never a target multiple. If they say "double in a year", that is a GOAL: call set_portfolio_goal with that text and add_position with their ACTUAL holding (e.g. 0.01 BTC means quantity=0.01, NOT 0.02).
- If the user provides entry/buy price (e.g. "bought at 2600"), pass it as add_position.entry_price or update_position.entry_price.
- If the user provides rationale/context (e.g. "long-term hold", "DCA"), preserve that in notes (add_position.notes or update_position.notes).
- set_portfolio_goal is for targets and time horizons only—not for duplicating quantity.
- When the user states both a holding and a goal in one message, call the appropriate tools in the same turn (e.g. add_position + set_portfolio_goal). Do not ask for confirmation if quantities are explicit.

AUTO-CALCULATE QUANTITY OR ENTRY PRICE (very important):
- If the user gives **total cash per ticker** (e.g. "20k PKR in HBL", "bought AAPL for $500", "$400 of BTC") **without** number of shares, you have enough to size the position. **Do NOT** ask for "price per share", "purchase price per share", or "what did each share cost" — that is redundant and wrong UX.
- **Listed stocks in PKR** (e.g. Pakistan / PSX, amounts in rupees): call `get_quote` for each ticker. When the tool or snippets give **PKR per share**, compute `quantity = total_pkr_invested / pkr_per_share` (round to whole shares unless fractional is clearly allowed). Set `entry_price` to that **PKR per share** float. Put in `notes`: total PKR invested and that sizing used same-day spot; optional USD notional from a fresh USD/PKR reference only as context—not as entry_price.
- **Crypto or USD-denominated buys**: call `get_quote`, then `quantity = amount_usd / usd_spot`, `entry_price = usd_spot`, document in `notes`.
- **Multiple tickers in one message**: call `get_quote` once per ticker, then `add_position` for each, then `get_portfolio` if needed for analysis—still in the same turn where possible.
- If the user states a **share count** but no entry price, e.g. "I have 10 AAPL shares": call `get_quote`, use spot as `entry_price`, and note in `notes` that it is a spot proxy.
- Only if `get_quote` / snippets truly contain **no** usable price may you ask one short clarifying question—never ask for per-share price when they already gave total PKR invested.
- After portfolio changes, add 1–2 sentences of general, educational risk-aware tips (not personalized investment advice).

Goals and “how do I make $X” questions: Do NOT refuse or say you cannot help. The user chose this trading assistant to reason about markets and their portfolio. For questions like “earn $500 in three months from my portfolio”, call get_portfolio first, then optionally search_web or query_rag for context. Answer with an educational, informational breakdown: implied return or rough scenarios, risk (volatility, drawdowns), time horizon realism, diversification and costs, and what would need to happen in percentage terms—not guarantees. You may discuss general approaches people read about (DCA, rebalancing, risk limits) as concepts, not as a command to act. End with a short disclaimer that you are not a financial advisor and they should consult a licensed professional for personalized advice—but only after you have given substantive help.

Humor / roast requests: If the user explicitly asks to roast, mock, or humorously critique their OWN portfolio, comply in a playful, non-hateful way. Keep it witty but constructive: include concrete portfolio observations (concentration, risk, diversification, time horizon mismatch, cost basis realism), avoid slurs/abuse, and end with practical improvement suggestions.

Be concise and professional. Never output raw tool syntax, JSON tool calls, or markup like <|...|> to the user—only natural language.

Formatting rules:
- Do not output LaTeX/TeX math delimiters (\\[...\\], \\(...\\), $$...$$, or $...$). Use plain text math only.
- Keep equations readable in normal text, e.g. "Price per ETH = 415 / 0.0509 ~= 8126.73 USD"."""

TOOLS: list[BaseTool] = [
    query_rag,
    web_search_tool,
    get_quote,
    get_portfolio,
    add_position,
    delete_position,
    update_position,
    set_portfolio_goal,
    *memory_tools,
]
TOOL_MAP = {t.name: t for t in TOOLS}

TOOL_STATUS_LABELS: dict[str, str] = {
    "query_rag": "Searching knowledge base…",
    "search_web": "Searching the web…",
    "get_quote": "Fetching live price…",
    "get_portfolio": "Loading your portfolio…",
    "add_position": "Updating your portfolio…",
    "delete_position": "Updating your portfolio…",
    "update_position": "Updating your portfolio…",
    "set_portfolio_goal": "Updating your portfolio…",
    "remember": "Using memory…",
    "recall": "Using memory…",
}


def _turn_start_status(turn: int) -> str:
    if turn <= 1:
        return "Thinking…"
    if turn == 2:
        return "Analyzing…"
    return "Working…"


def _turn_wait_status(turn: int, wait_tick: int) -> str:
    if turn <= 1:
        if wait_tick == 1:
            return "Analyzing…"
        if wait_tick == 2:
            return "Still thinking…"
        return "Thinking through details…"
    if turn == 2:
        if wait_tick == 1:
            return "Analyzing…"
        if wait_tick == 2:
            return "Planning next moves…"
        return "Reasoning through results…"
    if wait_tick == 1:
        return "Working…"
    if wait_tick == 2:
        return "Composing…"
    return "Finishing…"


def _should_prefetch_portfolio(message: str) -> bool:
    """Heuristic: prefetch portfolio context when user asks about their holdings."""
    text = (message or "").lower()
    if not text:
        return False
    keywords = (
        "portfolio",
        "holdings",
        "positions",
        "investments",
        "my stocks",
        "my crypto",
        "my coins",
        "my shares",
        "roast",
        "mock",
        "review my",
        "analyze my",
        "i bought",
        "i just bought",
        "i purchased",
        "i own",
        "i hold",
        "i have ",
        "add ",
        "update ",
    )
    return any(k in text for k in keywords)


def _should_prefetch_web(message: str) -> bool:
    """Heuristic: prefetch live web context for real-time market/news prompts."""
    text = (message or "").lower()
    if not text:
        return False
    keywords = (
        "latest",
        "current",
        "today",
        "right now",
        "price",
        "market news",
        "breaking",
        "what happened",
        "headline",
        "update on",
        "search web",
        "look up",
    )
    return any(k in text for k in keywords)


def _is_meta_agent_behavior_question(message: str) -> bool:
    """Detect prompts about the assistant's own prior behavior; these should avoid web search."""
    text = (message or "").lower().strip()
    if not text:
        return False
    return (
        ("why" in text or "how" in text)
        and ("you " in text or "assistant" in text or "agent" in text)
        and (
            "added" in text
            or "update" in text
            or "portfolio" in text
            or "wrong" in text
            or "did that" in text
            or "did this" in text
        )
    )


def _looks_like_web_deferral(text: str) -> bool:
    """Detect assistant replies that defer instead of calling search_web."""
    t = (text or "").lower()
    if not t:
        return False
    phrases = (
        "i need to search the web",
        "i need to search web",
        "i should search the web",
        "i should search web",
        "i need to look this up",
        "i need to browse",
        "i don't have real-time",
        "i dont have real-time",
        "i don't have realtime",
        "i dont have realtime",
        "i can't access real-time",
        "i cant access real-time",
        "i can't access realtime",
        "i cant access realtime",
    )
    return any(p in t for p in phrases)


def _normalize_user_prompt_for_model(message: str) -> str:
    """
    Preserve user intent while avoiding wording that some models hard-refuse.
    """
    text = (message or "").strip()
    low = text.lower()
    humor_words = ("mock", "mocking", "roast", "roasting")
    portfolio_words = ("portfolio", "holdings", "investments", "positions")
    if any(w in low for w in humor_words) and any(w in low for w in portfolio_words):
        return (
            "Give a playful, witty, but constructive critique of my portfolio in one paragraph. "
            "Use light humor, avoid abuse, and include practical improvement suggestions."
        )
    return text


async def _run_tool(name: str, args: dict) -> str:
    try:
        tool = TOOL_MAP.get(name)
        if not tool:
            return f"Unknown tool: {name}"
        if hasattr(tool, "ainvoke"):
            result = await tool.ainvoke(args)
        else:
            result = await asyncio.to_thread(tool.invoke, args)
        return str(result) if result is not None else "Done."
    except Exception as e:
        logger.exception("Tool %s error: %s", name, e)
        return f"Tool error: {e}"


def _tool_call_meta(tc) -> tuple[str, dict, str]:
    if isinstance(tc, dict):
        return tc.get("name", ""), tc.get("args", {}) or {}, tc.get("id", "") or ""
    return (
        getattr(tc, "name", "") or "",
        getattr(tc, "args", {}) or {},
        getattr(tc, "id", "") or "",
    )


def _flatten_messages_for_plain_completion(messages: list) -> list:
    """
    Turn tool-call transcripts into plain text for a final completion pass.

    Groq returns ``Tool choice is none, but model called a tool`` if the model
    keeps emitting tool calls after a long in-context tool trace while the
    request has no tools bound. Stripping ``tool_calls`` and inlining tool
    outputs as system text avoids that failure mode.
    """
    out: list = []
    for m in messages:
        if isinstance(m, (SystemMessage, HumanMessage)):
            out.append(m)
        elif isinstance(m, AIMessage):
            tool_calls = getattr(m, "tool_calls", None) or []
            content = m.content
            if isinstance(content, list):
                parts: list[str] = []
                for part in content:
                    if isinstance(part, str):
                        parts.append(part)
                    elif isinstance(part, dict) and part.get("type") == "text":
                        parts.append(str(part.get("text", "") or ""))
                content = "".join(parts)
            if not isinstance(content, str):
                content = str(content) if content is not None else ""
            # Always drop tool_calls / provider extras — Groq errors if any tool trace leaks into a no-tools completion.
            out.append(AIMessage(content=content, tool_calls=[]))
        elif isinstance(m, ToolMessage):
            name = getattr(m, "name", None) or "tool"
            body = str(m.content or "")
            if len(body) > 16000:
                body = body[:16000] + "\n… [truncated]"
            out.append(
                SystemMessage(
                    content=(
                        f"[Earlier `{name}` tool result — use this context only; "
                        f"respond in plain text, do not call tools:]\n{body}"
                    )
                )
            )
        else:
            out.append(m)
    return out


async def stream_agent_response(
    message: str,
    history: list[dict],
    model_id: str | None = None,
) -> AsyncGenerator[str | dict, None]:
    """
    Run agent with tools; yield sanitized content or status dicts.
    """
    selected = get_model_spec(model_id)
    tool_capable = supports_tools(selected.id)
    logger.info("runner_model_selected %s", model_log_meta(selected.id))
    try:
        llm_no_tools = get_llm(selected.id)
    except Exception as e:
        logger.exception(
            "runner_model_init_failed model=%s status=%s category=%s err=%s",
            selected.id,
            extract_error_status_code(e),
            classify_model_error(e),
            e,
        )
        yield "Something went wrong. Please try again."
        await asyncio.sleep(0)
        return
    llm = llm_no_tools.bind_tools(TOOLS) if tool_capable else llm_no_tools
    tool_call_cache: dict[tuple[str, str], str] = {}

    def _tool_cache_key(name: str, args: dict | None) -> tuple[str, str]:
        try:
            import json as _json
            key = _json.dumps(args or {}, sort_keys=True, default=str)
        except Exception:
            key = str(args)
        return (name or "", key)

    messages: list = [SystemMessage(content=SYSTEM_PROMPT)]
    # Groq Compound and similar models have a small request budget — trim history and skip heavy prefetches.
    hist = history
    if not tool_capable and len(history) > 6:
        hist = history[-6:]
    for h in hist:
        role, content = h.get("role", ""), h.get("content", "")
        if role == "user":
            messages.append(HumanMessage(content=content))
        elif role == "assistant":
            messages.append(AIMessage(content=content))
    if tool_capable and _should_prefetch_portfolio(message):
        yield {"event": "status", "data": TOOL_STATUS_LABELS["get_portfolio"]}
        await asyncio.sleep(0)
        portfolio_snapshot = await _run_tool("get_portfolio", {})
        if len(portfolio_snapshot) > 8000:
            portfolio_snapshot = portfolio_snapshot[:8000] + "\n… [truncated]"
        tool_call_cache[_tool_cache_key("get_portfolio", {})] = portfolio_snapshot
        messages.append(
            SystemMessage(
                content=(
                    "Auto-fetched current user portfolio context:\n"
                    f"{portfolio_snapshot}\n\n"
                    "Use this context directly. Do not ask the user to repeat holdings unless the portfolio is empty. "
                    "Do NOT call get_portfolio again for this turn; the data above is current."
                )
            )
        )
    should_prefetch_web = (
        tool_capable
        and _should_prefetch_web(message)
        and not _is_meta_agent_behavior_question(message)
    )
    if should_prefetch_web:
        yield {"event": "status", "data": TOOL_STATUS_LABELS["search_web"]}
        await asyncio.sleep(0)
        web_snapshot = await _run_tool("search_web", {"query": message})
        if len(web_snapshot) > 6000:
            web_snapshot = web_snapshot[:6000] + "\n… [truncated]"
        tool_call_cache[_tool_cache_key("search_web", {"query": message})] = web_snapshot
        messages.append(
            SystemMessage(
                content=(
                    "Auto-fetched live web context for this user query:\n"
                    f"{web_snapshot}\n\n"
                    "Use this context directly and provide a concise answer. "
                    "Do NOT call search_web again for the same query; prefer answering from the snippets above."
                )
            )
        )
    # Keep the current user turn as the last message; some Ollama models may emit empty output
    # if a system message is appended after the user's input.
    if _is_meta_agent_behavior_question(message):
        messages.append(
            SystemMessage(
                content=(
                    "The user is asking about this assistant's previous behavior/actions. "
                    "Do not call search_web for this. Explain likely internal/tooling reason and provide a concrete correction path."
                )
            )
        )
    normalized_message = _normalize_user_prompt_for_model(message)
    messages.append(HumanMessage(content=normalized_message))
    max_turns = max(1, settings.AGENT_MAX_TURNS)
    turn = 0
    auto_web_fallback_used = False
    emitted_any_text = False
    while turn < max_turns:
        turn += 1
        turn_start_status = _turn_start_status(turn)
        yield {"event": "status", "data": turn_start_status}
        await asyncio.sleep(0)

        chunks: list = []
        buffer = ""
        last_safe_emitted = ""
        turn_emitted_text = False
        stream_aborted_bad_tool = False
        stream_iter = llm.astream(messages).__aiter__()
        pending_next: asyncio.Task | None = None
        wait_tick = 0
        while True:
            if pending_next is None:
                pending_next = asyncio.create_task(stream_iter.__anext__())
            try:
                chunk = await asyncio.wait_for(asyncio.shield(pending_next), timeout=3.0)
            except TimeoutError:
                wait_tick += 1
                status = _turn_wait_status(turn, wait_tick)
                yield {"event": "status", "data": status}
                await asyncio.sleep(0)
                continue
            except StopAsyncIteration:
                pending_next = None
                break
            except Exception as e:
                err_s = str(e).lower()
                if tool_capable and (
                    "failed to parse tool call" in err_s
                    or "parse tool call arguments" in err_s
                ):
                    logger.warning(
                        "runner_stream_recover_bad_tool_call model=%s err=%s",
                        selected.id,
                        e,
                    )
                    messages.append(
                        SystemMessage(
                            content=(
                                "The model emitted a malformed tool call. Answer in plain text only "
                                "(no tools) using the user message and any prior context you already have."
                            )
                        )
                    )
                    pending_next = None
                    stream_aborted_bad_tool = True
                    chunks = []
                    break
                logger.warning(
                    "runner_stream_chunk_error model=%s status=%s category=%s err=%s",
                    selected.id,
                    extract_error_status_code(e),
                    classify_model_error(e),
                    e,
                )
                pending_next = None
                raise

            wait_tick = 0
            pending_next = None
            chunk_content = getattr(chunk, "content", None)
            if chunk_content:
                if isinstance(chunk_content, str):
                    buffer += chunk_content
                else:
                    for part in chunk_content:
                        if isinstance(part, str):
                            buffer += part
                        elif isinstance(part, dict) and part.get("type") == "text":
                            buffer += part.get("text", "")
            chunks.append(chunk)
            delta, last_safe_emitted, did_resync = stream_safe_text_delta(buffer, last_safe_emitted)
            if did_resync:
                yield {"event": "replace", "data": delta}
                emitted_any_text = True
                turn_emitted_text = True
                await asyncio.sleep(0)
            elif delta:
                yield delta
                emitted_any_text = True
                turn_emitted_text = True
                await asyncio.sleep(0)

        if stream_aborted_bad_tool:
            continue

        merged = chunks[0] if chunks else None
        for c in chunks[1:]:
            try:
                merged = merged + c if merged is not None else c
            except Exception:
                # Some stream providers return non-addable chunk objects.
                merged = c
        current_tool_calls = getattr(merged, "tool_calls", []) or []
        full_content = (getattr(merged, "content", "") or "") if merged else ""
        if not buffer.strip() and full_content:
            buffer = full_content if isinstance(full_content, str) else str(full_content)
            delta, last_safe_emitted, did_resync = stream_safe_text_delta(buffer, last_safe_emitted)
            if did_resync:
                yield {"event": "replace", "data": delta}
                emitted_any_text = True
                turn_emitted_text = True
                await asyncio.sleep(0)
            elif delta:
                yield delta
                emitted_any_text = True
                turn_emitted_text = True
                await asyncio.sleep(0)

        if not current_tool_calls or not tool_capable:
            clean_assistant = sanitize_assistant_visible_text(buffer) or (full_content if isinstance(full_content, str) else "") or ""
            if clean_assistant and not turn_emitted_text:
                yield clean_assistant
                emitted_any_text = True
                turn_emitted_text = True
                await asyncio.sleep(0)
            if tool_capable and (not auto_web_fallback_used) and _looks_like_web_deferral(clean_assistant):
                auto_web_fallback_used = True
                yield {"event": "status", "data": TOOL_STATUS_LABELS["search_web"]}
                await asyncio.sleep(0)
                web_result = await _run_tool("search_web", {"query": message})
                messages.append(
                    SystemMessage(
                        content=(
                            "Auto web-search fallback triggered because the assistant deferred.\n"
                            f"User query: {message}\n"
                            f"Web context:\n{web_result}\n\n"
                            "Now answer directly without asking for permission to search."
                        )
                    )
                )
                continue
            break

        yield {"event": "status", "data": "Selecting tools…"}
        await asyncio.sleep(0)

        tool_names = [_tool_call_meta(tc)[0] for tc in current_tool_calls]
        if "search_web" in tool_names:
            tool_status = TOOL_STATUS_LABELS["search_web"]
        elif "get_portfolio" in tool_names:
            tool_status = TOOL_STATUS_LABELS["get_portfolio"]
        else:
            tool_line_labels = [TOOL_STATUS_LABELS.get(name, name or "tool") for name in tool_names]
            tool_status = " · ".join(tool_line_labels)
        yield {"event": "status", "data": tool_status}
        await asyncio.sleep(0)

        async def _run_bounded(tc):
            name, args, tid = _tool_call_meta(tc)
            cache_key = _tool_cache_key(name, args)
            if cache_key in tool_call_cache:
                logger.info("runner_tool_cache_hit tool=%s args=%s", name, cache_key[1])
                return tid or name, tool_call_cache[cache_key]
            res = await _run_tool(name, args)
            tool_call_cache[cache_key] = res
            return tid or name, res

        pairs = await asyncio.gather(*[_run_bounded(tc) for tc in current_tool_calls])

        tool_messages = [ToolMessage(content=result, tool_call_id=tid) for tid, result in pairs]

        clean_assistant = sanitize_assistant_visible_text(buffer) or (full_content if isinstance(full_content, str) else "") or ""
        messages.append(AIMessage(content=clean_assistant, tool_calls=current_tool_calls))
        messages.extend(tool_messages)

    if not emitted_any_text:
        # If tool-heavy turns consumed AGENT_MAX_TURNS, force one final no-tools answer.
        flat = _flatten_messages_for_plain_completion(messages)
        # Groq expects the last message to be `user` for some completions; ending with HumanMessage avoids
        # ``last message role must be 'user'`` and reduces spurious tool calls vs a trailing system line.
        final_messages = flat + [
            HumanMessage(
                content=(
                    "Using the conversation and any inlined tool results above, write the final reply for the user now. "
                    "Plain text only — do not call tools, output no JSON tool blocks, and do not ask permission to search."
                )
            )
        ]
        final_buffer = ""
        final_last_safe = ""
        final_llm = llm_no_tools
        try:
            final_llm = llm_no_tools.bind(tool_choice="none")
        except Exception:
            pass
        try:
            async for chunk in final_llm.astream(final_messages):
                chunk_content = getattr(chunk, "content", None)
                if chunk_content:
                    if isinstance(chunk_content, str):
                        final_buffer += chunk_content
                    else:
                        for part in chunk_content:
                            if isinstance(part, str):
                                final_buffer += part
                            elif isinstance(part, dict) and part.get("type") == "text":
                                final_buffer += part.get("text", "")
                delta, final_last_safe, did_resync = stream_safe_text_delta(final_buffer, final_last_safe)
                if did_resync:
                    yield {"event": "replace", "data": delta}
                    emitted_any_text = True
                    await asyncio.sleep(0)
                elif delta:
                    yield delta
                    emitted_any_text = True
                    await asyncio.sleep(0)
        except Exception:
            logger.exception("Final no-tools generation failed")

    if not emitted_any_text:
        yield "I could not generate a response just now. Please try again."
        await asyncio.sleep(0)

    return
