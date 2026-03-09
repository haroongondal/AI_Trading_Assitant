"""
Configuration loaded from environment variables.
JS parallel: like reading process.env in Node; pydantic-settings validates and types them.
"""
from pydantic import field_validator
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

    # Database (SQLite for dev; use POSTGRES_DSN for production)
    DATABASE_URL: str = "sqlite+aiosqlite:///./data/trading_assistant.db"

    # App
    API_V1_PREFIX: str = "/api"
    # Comma-separated in .env (e.g. CORS_ORIGINS=http://localhost:3000,http://localhost:3001) or leave unset for defaults
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

    # Demo user (single-user mode for weekend project)
    DEFAULT_USER_ID: str = "default-user"

    # RAG / vector store
    CHROMA_PERSIST_DIR: str = "./data/chroma"
    RAG_TOP_K: int = 8

    # Scheduler: twice daily (cron)
    SCHEDULER_HOUR_1: int = 8
    SCHEDULER_MINUTE_1: int = 0
    SCHEDULER_HOUR_2: int = 18
    SCHEDULER_MINUTE_2: int = 0

    # WhatsApp (Meta Cloud API trial). Leave empty to skip WhatsApp delivery.
    WHATSAPP_ACCESS_TOKEN: str = ""
    WHATSAPP_PHONE_NUMBER_ID: str = ""
    WHATSAPP_RECIPIENT_PHONE: str = ""  # E.164, e.g. 1234567890
    WHATSAPP_TEMPLATE_NAME: str = "hello_world"  # Approved template for business-initiated


settings = Settings()
