"""
Configuration loaded from environment variables.
JS parallel: like reading process.env in Node; pydantic-settings validates and types them.
"""
from urllib.parse import urlparse

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _parse_cors_origins(v: str | list[str]) -> list[str]:
    if isinstance(v, list):
        return [o.strip() for o in v if o and isinstance(o, str)]
    s = str(v).strip()
    if not s:
        return []
    return [o.strip() for o in s.split(",") if o.strip()]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Ollama (local LLM)
    OLLAMA_BASE_URL: str = "http://127.0.0.1:11434"
    OLLAMA_MODEL: str = "llama3.2"
    OLLAMA_EMBEDDING_MODEL: str = "nomic-embed-text"
    OLLAMA_TEMPERATURE: float = 0.3
    # Optional context window (unset = Ollama default)
    OLLAMA_NUM_CTX: int | None = None

    # Agent ReAct loop (each turn = one LLM stream + optional tools)
    AGENT_MAX_TURNS: int = 6

    # Database (SQLite for dev; use POSTGRES_DSN for production)
    DATABASE_URL: str = "sqlite+aiosqlite:///./data/trading_assistant.db"

    # App
    API_V1_PREFIX: str = "/api"
    # Root log level: DEBUG shows more detail; chat timing uses INFO on app.* loggers
    LOG_LEVEL: str = "INFO"
    # Comma-separated in .env (e.g. CORS_ORIGINS=http://localhost:3000,http://localhost:3001) or leave unset for defaults.
    # The origin derived from FRONTEND_URL is always appended if missing (browser fetch + credentials from the SPA).
    # You do NOT add accounts.google.com here — OAuth uses top-level redirects, not CORS.
    CORS_ORIGINS: list[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001",
        "http://[::1]:3000",
        "http://[::1]:3001",
        "http://0.0.0.0:3000",
        "http://0.0.0.0:3001",
    ]

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: str | list[str]) -> list[str]:
        default_origins = [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:3001",
            "http://127.0.0.1:3001",
            "http://[::1]:3000",
            "http://[::1]:3001",
            "http://0.0.0.0:3000",
            "http://0.0.0.0:3001",
        ]
        if v is None:
            return default_origins
        return _parse_cors_origins(v) if v else default_origins

    # Demo user when no JWT cookie / Bearer token is sent (local dev without Google)
    DEFAULT_USER_ID: str = "default-user"

    # Google OAuth (optional). When GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET are set, /api/auth/google/* enables sign-in.
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REDIRECT_URI: str = ""
    GOOGLE_OAUTH_AUTHORIZATION_URL: str = "https://accounts.google.com/o/oauth2/v2/auth"
    GOOGLE_OAUTH_TOKEN_URL: str = "https://oauth2.googleapis.com/token"
    GOOGLE_OAUTH_USERINFO_URL: str = "https://www.googleapis.com/oauth2/v2/userinfo"
    # Space-separated scopes (default openid email profile)
    GOOGLE_OAUTH_SCOPES: str = "openid email profile"

    # Post-login redirect base (no trailing path required)
    FRONTEND_URL: str = "http://localhost:3000"
    # Query appended to FRONTEND_URL when Google returns ?error= (e.g. ?auth_error=1)
    AUTH_ERROR_REDIRECT_QUERY: str = "auth_error=1"

    # Session JWT (required for signed-in users; leave empty to disable token validation / demo-only)
    AUTH_JWT_SECRET: str = ""
    AUTH_JWT_ALGORITHM: str = "HS256"
    AUTH_JWT_EXPIRE_DAYS: int = 7

    # HttpOnly cookies (names and browser policy)
    AUTH_ACCESS_COOKIE_NAME: str = "access_token"
    OAUTH_STATE_COOKIE_NAME: str = "oauth_state"
    OAUTH_STATE_COOKIE_MAX_AGE: int = 600
    AUTH_COOKIE_PATH: str = "/"
    AUTH_COOKIE_SAMESITE: str = "lax"
    # Set true behind HTTPS in production (required if frontend is on a different site and SameSite=None)
    AUTH_COOKIE_SECURE: bool = False

    @field_validator("OLLAMA_NUM_CTX", mode="before")
    @classmethod
    def empty_num_ctx_none(cls, v: object) -> int | None:
        if v is None or v == "":
            return None
        if isinstance(v, str) and not v.strip():
            return None
        if isinstance(v, int):
            return v
        return int(str(v).strip())

    @field_validator("AUTH_COOKIE_SAMESITE", mode="before")
    @classmethod
    def normalize_samesite(cls, v: object) -> str:
        if not isinstance(v, str):
            return "lax"
        s = v.strip().lower()
        return s if s in ("lax", "strict", "none") else "lax"

    # RAG / vector store
    CHROMA_PERSIST_DIR: str = "./data/chroma"
    RAG_TOP_K: int = 8

    # Scheduler control
    SCHEDULER_ENABLED: bool = False
    # Cron format: "minute hour day month day_of_week"
    # Default runs twice daily at 09:00 and 21:00 server time.
    SCHEDULER_CRON: str = "0 9,21 * * *"

    # WhatsApp (Meta Cloud API trial). Leave empty to skip WhatsApp delivery.
    WHATSAPP_ACCESS_TOKEN: str = ""
    WHATSAPP_PHONE_NUMBER_ID: str = ""
    WHATSAPP_RECIPIENT_PHONE: str = ""  # E.164, e.g. 1234567890
    WHATSAPP_TEMPLATE_NAME: str = "hello_world"  # Approved template for business-initiated

    # Email SMTP (Gmail-compatible). Leave creds empty to skip email delivery.
    EMAIL_SMTP_HOST: str = "smtp.gmail.com"
    EMAIL_SMTP_PORT: int = 587
    EMAIL_SMTP_STARTTLS: bool = True
    EMAIL_SMTP_USERNAME: str = ""
    EMAIL_SMTP_PASSWORD: str = ""  # For Gmail use an App Password, not account password
    EMAIL_FROM: str = ""  # Optional; defaults to EMAIL_SMTP_USERNAME
    EMAIL_DEFAULT_TO: str = ""  # Optional fallback when user.email is missing

    @model_validator(mode="after")
    def merge_frontend_origin_into_cors(self) -> "Settings":
        """Allow the SPA at FRONTEND_URL to call this API with credentials (fixes prod CORS after OAuth)."""
        fe = (self.FRONTEND_URL or "").strip()
        if not fe:
            return self
        if "://" not in fe:
            fe = f"https://{fe}"
        parsed = urlparse(fe)
        if not parsed.scheme or not parsed.netloc:
            return self
        origin = f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
        if origin in self.CORS_ORIGINS:
            return self
        return self.model_copy(update={"CORS_ORIGINS": [*self.CORS_ORIGINS, origin]})


settings = Settings()
