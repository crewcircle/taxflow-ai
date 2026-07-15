from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# apps/backend/.env - used for local dev; in production Doppler injects real env vars,
# which take precedence over the file.
_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(case_sensitive=False, extra="ignore", env_file=_ENV_FILE)

    # Required - fail fast if missing
    SUPABASE_URL: str
    SUPABASE_SERVICE_ROLE_KEY: str
    SUPABASE_ANON_KEY: str
    ANTHROPIC_API_KEY: str
    STRIPE_SECRET_KEY: str
    STRIPE_WEBHOOK_SECRET: str
    DATABASE_URL: str

    # Optional - have defaults
    ENVIRONMENT: str = "production"
    APP_NAME: str = "taxflow"
    LOG_LEVEL: str = "INFO"
    ANTHROPIC_HAIKU_MODEL: str = "claude-haiku-4-5"
    ANTHROPIC_SONNET_MODEL: str = "claude-sonnet-4-6"
    HAIKU_CONFIDENCE_THRESHOLD: float = 0.72
    MAX_RETRIEVAL_CHUNKS: int = 10
    CHUNK_SIZE_TOKENS: int = 512
    CHUNK_OVERLAP_TOKENS: int = 64
    OPENAI_API_KEY: str = ""

    # Postgres connection pool (per uvicorn worker; see db.py). maxconn is sized
    # so 2 workers (~2 x 8 = 16 connections) stay under Supabase's connection cap.
    POOL_MIN_CONN: int = 1
    POOL_MAX_CONN: int = 8


settings = Settings()  # type: ignore[call-arg]
