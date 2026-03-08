"""
Configuration loaded from environment variables.
JS parallel: like reading process.env in Node; pydantic-settings validates and types them.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    CORS_ORIGINS: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]

    # Demo user (single-user mode for weekend project)
    DEFAULT_USER_ID: str = "default-user"

    # RAG / vector store
    CHROMA_PERSIST_DIR: str = "./data/chroma"
    RAG_TOP_K: int = 4


settings = Settings()
