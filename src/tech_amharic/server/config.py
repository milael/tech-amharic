from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration from environment variables prefixed ``TAM_`` (or a .env file)."""

    model_config = SettingsConfigDict(env_prefix="TAM_", env_file=".env", extra="ignore")

    # SQLite is fine for local development and tests; production uses
    # PostgreSQL, e.g. postgresql+psycopg://tam:secret@db:5432/tam
    database_url: str = "sqlite:///./tech_amharic.db"
    # Create tables on startup. Convenient locally; in production run
    # `alembic upgrade head` instead and leave this off.
    auto_create_tables: bool = False
    # Send the session cookie only over HTTPS. Turn off for plain-http dev.
    secure_cookies: bool = True
    # Write requests allowed per user per minute (per process).
    write_rate_per_minute: int = 60
    max_body_bytes: int = 64_000
    release_version: str = "0.1.0-dev"

    # Chat (termbase-grounded answers). Any OpenAI-compatible endpoint works:
    # Ollama locally (default), vLLM, or a hosted API.
    chat_enabled: bool = True
    llm_base_url: str = "http://localhost:11434/v1"
    llm_model: str = "gemma4:e4b"
    llm_api_key: str = "ollama"
    # Proposed (unreviewed) terms help while the termbase is young; switch
    # off once enough terms are reviewed.
    chat_include_unreviewed: bool = True
    chat_rate_per_minute: int = 10


@lru_cache
def get_settings() -> Settings:
    return Settings()
