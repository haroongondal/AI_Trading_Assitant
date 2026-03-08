"""
Memory tools: remember facts and recall conversation context. JS parallel: like a key-value store + conversation buffer the agent can query.
"""
from langchain_core.tools import tool

# In-memory per "session" (we use default user id for single-user). Production would use DB or Redis.
_user_memory: dict[str, list[str]] = {}  # user_id -> list of "fact" strings
_user_conversation: dict[str, list[dict]] = {}  # user_id -> [{role, content}, ...]


def _get_user_id() -> str:
    from app.core.config import settings
    return settings.DEFAULT_USER_ID


@tool
def remember(fact: str) -> str:
    """Store a fact or preference the user wants you to remember. Input should be a clear sentence describing what to remember (e.g. 'User prefers conservative risk' or 'User holds BTC and ETH')."""
    uid = _get_user_id()
    if uid not in _user_memory:
        _user_memory[uid] = []
    _user_memory[uid].append(fact)
    return f"Remembered: {fact}"


@tool
def recall(query: str) -> str:
    """Recall what you have stored about the user or what was discussed. Use when the user asks what you know about them, their preferences, or past conversation points."""
    uid = _get_user_id()
    facts = _user_memory.get(uid, [])
    recent = _user_conversation.get(uid, [])[-10:]  # last 10 messages
    if not facts and not recent:
        return "No stored memory or recent conversation."
    parts = []
    if facts:
        parts.append("Stored facts:\n" + "\n".join(f"- " + f for f in facts[-20:]))
    if recent:
        parts.append("Recent conversation:\n" + "\n".join(
            f"- {m.get('role', '')}: {m.get('content', '')[:200]}..." if len(m.get("content", "")) > 200 else f"- {m.get('role', '')}: {m.get('content', '')}"
            for m in recent
        ))
    return "\n\n".join(parts) if parts else "Nothing to recall."


def add_to_conversation(user_id: str, role: str, content: str):
    """Called by chat endpoint to keep conversation buffer for recall."""
    if user_id not in _user_conversation:
        _user_conversation[user_id] = []
    _user_conversation[user_id].append({"role": role, "content": content})


# Export as list for agent
memory_tools = [remember, recall]
