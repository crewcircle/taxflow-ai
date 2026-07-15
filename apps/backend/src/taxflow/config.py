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

    # --- Pre-generation model routing (Task A3) -------------------------------
    # research.run() picks Haiku or Sonnet BEFORE the single generation call using
    # retrieval signals only (no LLM call). We bias toward Sonnet when signals are
    # ambiguous, so these gates describe the "strong retrieval -> Haiku is enough"
    # case; anything below routes to Sonnet.
    #   - ROUTE_MIN_STRONG_CHUNKS: how many retrieved chunks we need to trust Haiku.
    #   - ROUTE_MIN_TOP_RRF_SCORE: the top RRF (or re-rank) score must clear this.
    # When hybrid search returns nothing (the "insufficient information" situation),
    # we always route to Sonnet.
    ROUTE_MIN_STRONG_CHUNKS: int = 5
    ROUTE_MIN_TOP_RRF_SCORE: float = 0.03

    # --- pgvector index tuning (Task A5) --------------------------------------
    # ivfflat.probes for the ANN scan. Higher = better recall, more latency. Set
    # transaction-locally alongside the vector SELECT (SET LOCAL no-ops outside an
    # explicit transaction on a pooled connection).
    IVFFLAT_PROBES: int = 10

    # --- Anthropic prompt caching (Task B1) -----------------------------------
    # Toggle cache_control breakpoints on the large static system prompts. Deploy-
    # time flag (loaded at process start).
    PROMPT_CACHE_ENABLED: bool = True


settings = Settings()  # type: ignore[call-arg]
