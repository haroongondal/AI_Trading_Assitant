"""
Google OAuth login: redirect to Google, callback issues JWT in HttpOnly cookie, redirect to frontend.
"""
import hashlib
import logging
import secrets
from urllib.parse import urlencode
from urllib.parse import urlparse

import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import user_id_from_token
from app.core.config import settings
from app.db.session import async_session_factory, get_db
from app.db.models import User
from app.models.schemas import UserOut

logger = logging.getLogger(__name__)
router = APIRouter()


def _oauth_ready() -> bool:
    return bool(
        settings.GOOGLE_CLIENT_ID.strip()
        and settings.GOOGLE_CLIENT_SECRET.strip()
        and settings.GOOGLE_REDIRECT_URI.strip()
        and settings.AUTH_JWT_SECRET.strip()
    )


def _oauth_misconfiguration_detail() -> str:
    missing = []
    if not settings.GOOGLE_CLIENT_ID.strip():
        missing.append("GOOGLE_CLIENT_ID")
    if not settings.GOOGLE_CLIENT_SECRET.strip():
        missing.append("GOOGLE_CLIENT_SECRET")
    if not settings.GOOGLE_REDIRECT_URI.strip():
        missing.append("GOOGLE_REDIRECT_URI")
    if not settings.AUTH_JWT_SECRET.strip():
        missing.append("AUTH_JWT_SECRET")
    return "Set in .env: " + ", ".join(missing)


def _auth_error_redirect_url() -> str:
    base = settings.FRONTEND_URL.rstrip("/")
    q = settings.AUTH_ERROR_REDIRECT_QUERY.strip()
    if not q:
        return f"{base}/"
    return f"{base}/?{q}"


def _internal_id_from_google_sub(google_sub: str) -> str:
    return hashlib.sha256(f"google:{google_sub}".encode()).hexdigest()


def _create_jwt(user_id: str) -> str:
    from datetime import datetime, timedelta, timezone

    exp = datetime.now(timezone.utc) + timedelta(days=settings.AUTH_JWT_EXPIRE_DAYS)
    return jwt.encode(
        {"sub": user_id, "exp": exp},
        settings.AUTH_JWT_SECRET,
        algorithm=settings.AUTH_JWT_ALGORITHM,
    )


def _cookie_policy_for_request(request: Request) -> tuple[str, bool]:
    """
    Derive cookie SameSite/Secure policy.
    For cross-site frontend<->backend setups, browsers require SameSite=None + Secure.
    """
    configured = (settings.AUTH_COOKIE_SAMESITE or "lax").strip().lower()
    secure = bool(settings.AUTH_COOKIE_SECURE)
    frontend_host = (urlparse(settings.FRONTEND_URL).hostname or "").lower()
    backend_host = (request.url.hostname or "").lower()
    cross_site = bool(frontend_host and backend_host and frontend_host != backend_host)
    if configured == "none" or cross_site:
        return "none", True
    return configured, secure


def _set_auth_cookie(response: RedirectResponse | JSONResponse, jwt_value: str, request: Request) -> None:
    same_site, secure = _cookie_policy_for_request(request)
    response.set_cookie(
        key=settings.AUTH_ACCESS_COOKIE_NAME,
        value=jwt_value,
        httponly=True,
        max_age=settings.AUTH_JWT_EXPIRE_DAYS * 86400,
        samesite=same_site,  # type: ignore[arg-type]
        path=settings.AUTH_COOKIE_PATH,
        secure=secure,
    )


def _set_oauth_state_cookie(response: RedirectResponse, state: str, request: Request) -> None:
    same_site, secure = _cookie_policy_for_request(request)
    response.set_cookie(
        key=settings.OAUTH_STATE_COOKIE_NAME,
        value=state,
        httponly=True,
        max_age=settings.OAUTH_STATE_COOKIE_MAX_AGE,
        samesite=same_site,  # type: ignore[arg-type]
        path=settings.AUTH_COOKIE_PATH,
        secure=secure,
    )


@router.get("/google/login")
async def google_login(request: Request):
    if not _oauth_ready():
        raise HTTPException(
            status_code=503,
            detail=f"Google OAuth is not fully configured. {_oauth_misconfiguration_detail()}",
        )
    state = secrets.token_urlsafe(32)
    params = {
        "client_id": settings.GOOGLE_CLIENT_ID.strip(),
        "redirect_uri": settings.GOOGLE_REDIRECT_URI.strip(),
        "response_type": "code",
        "scope": settings.GOOGLE_OAUTH_SCOPES.strip(),
        "state": state,
        "access_type": "online",
        "prompt": "select_account",
    }
    url = f"{settings.GOOGLE_OAUTH_AUTHORIZATION_URL.strip()}?{urlencode(params)}"
    redirect = RedirectResponse(url=url, status_code=302)
    _set_oauth_state_cookie(redirect, state, request)
    return redirect


@router.get("/google/callback")
async def google_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
):
    if error:
        logger.warning("Google OAuth error param: %s", error)
        return RedirectResponse(url=_auth_error_redirect_url(), status_code=302)
    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing code or state")

    cookie_state = request.cookies.get(settings.OAUTH_STATE_COOKIE_NAME)
    if not cookie_state or cookie_state != state:
        raise HTTPException(status_code=400, detail="Invalid OAuth state")

    if not _oauth_ready():
        raise HTTPException(status_code=503, detail=_oauth_misconfiguration_detail())

    token_url = settings.GOOGLE_OAUTH_TOKEN_URL.strip()
    userinfo_url = settings.GOOGLE_OAUTH_USERINFO_URL.strip()
    redirect_uri = settings.GOOGLE_REDIRECT_URI.strip()

    async with httpx.AsyncClient() as client:
        token_res = await client.post(
            token_url,
            data={
                "code": code,
                "client_id": settings.GOOGLE_CLIENT_ID.strip(),
                "client_secret": settings.GOOGLE_CLIENT_SECRET.strip(),
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=30.0,
        )
        if token_res.status_code != 200:
            logger.error("Google token exchange failed: %s", token_res.text)
            raise HTTPException(status_code=502, detail="Token exchange failed")
        tokens = token_res.json()
        access = tokens.get("access_token")
        if not access:
            raise HTTPException(status_code=502, detail="No access token")

        ui = await client.get(
            userinfo_url,
            headers={"Authorization": f"Bearer {access}"},
            timeout=30.0,
        )
        if ui.status_code != 200:
            logger.error("Google userinfo failed: %s", ui.text)
            raise HTTPException(status_code=502, detail="User info failed")
        profile = ui.json()

    google_sub = profile.get("id")
    if not google_sub:
        raise HTTPException(status_code=502, detail="No user id from Google")

    email = profile.get("email")
    name = (profile.get("name") or email or "User")[:255]
    internal_id = _internal_id_from_google_sub(str(google_sub))
    sub_str = str(google_sub)[:255]

    async with async_session_factory() as db:
        r = await db.execute(select(User).where(User.google_sub == sub_str))
        user = r.scalar_one_or_none()
        if user:
            user.name = name
            user.email = email[:255] if email else user.email
        else:
            user = User(
                id=internal_id,
                name=name,
                email=email[:255] if email else None,
                google_sub=sub_str,
            )
            db.add(user)
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            r = await db.execute(select(User).where(User.google_sub == sub_str))
            user = r.scalar_one_or_none()
            if not user:
                raise HTTPException(status_code=500, detail="Could not create user")
            user.name = name
            user.email = email[:255] if email else user.email
            await db.commit()

        final_id = user.id

    jwt_str = _create_jwt(final_id)
    redirect = RedirectResponse(url=settings.FRONTEND_URL.rstrip("/") + "/", status_code=302)
    redirect.delete_cookie(settings.OAUTH_STATE_COOKIE_NAME, path=settings.AUTH_COOKIE_PATH)
    _set_auth_cookie(redirect, jwt_str, request)
    return redirect


@router.post("/logout")
async def logout():
    r = JSONResponse({"ok": True})
    r.delete_cookie(settings.AUTH_ACCESS_COOKIE_NAME, path=settings.AUTH_COOKIE_PATH)
    return r


@router.get("/me", response_model=UserOut | None)
async def me(request: Request, db: AsyncSession = Depends(get_db)):
    token = None
    auth = request.headers.get("Authorization") or ""
    if auth.startswith("Bearer "):
        token = auth[7:].strip() or None
    if not token:
        token = request.cookies.get(settings.AUTH_ACCESS_COOKIE_NAME)
    uid = user_id_from_token(token)
    if not uid:
        return None
    result = await db.execute(select(User).where(User.id == uid))
    user = result.scalar_one_or_none()
    if not user:
        return None
    return UserOut(id=user.id, name=user.name, email=user.email)
