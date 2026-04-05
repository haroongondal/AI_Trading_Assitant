"""
Request-scoped user id for agent tools (portfolio, memory) during chat streaming.
"""
from contextvars import ContextVar

from app.core.config import settings

_current_user_id: ContextVar[str | None] = ContextVar("current_user_id", default=None)


def get_effective_user_id() -> str:
    """User id for tools and memory; falls back to DEFAULT_USER_ID if context not set."""
    uid = _current_user_id.get()
    return uid if uid else settings.DEFAULT_USER_ID


def set_current_user_id(user_id: str):
    """Returns the token for reset_current_user_id."""
    return _current_user_id.set(user_id)


def reset_current_user_id(token) -> None:
    _current_user_id.reset(token)
