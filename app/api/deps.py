"""
Resolve authenticated user id from JWT (cookie or Authorization: Bearer).
"""
import jwt
from fastapi import Request

from app.core.config import settings


def _token_from_request(request: Request) -> str | None:
    auth = request.headers.get("Authorization") or ""
    if auth.startswith("Bearer "):
        return auth[7:].strip() or None
    c = request.cookies.get(settings.AUTH_ACCESS_COOKIE_NAME)
    return c.strip() if c else None


def user_id_from_token(token: str | None) -> str | None:
    if not token or not settings.AUTH_JWT_SECRET.strip():
        return None
    try:
        payload = jwt.decode(
            token,
            settings.AUTH_JWT_SECRET,
            algorithms=[settings.AUTH_JWT_ALGORITHM],
            options={"require": ["exp", "sub"]},
        )
        sub = payload.get("sub")
        return str(sub) if sub else None
    except jwt.PyJWTError:
        return None


def resolve_effective_user_id(request: Request) -> str:
    uid = user_id_from_token(_token_from_request(request))
    return uid if uid else settings.DEFAULT_USER_ID
