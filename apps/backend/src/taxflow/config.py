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

    # --- Retrieval re-ranking (Task C1) ---------------------------------------
    # RRF stays a cheap candidate generator: we widen the semantic/text candidate
    # pools (RERANK_CANDIDATE_POOL each) and re-rank the merged candidates before
    # truncating to top_k, per RERANK_MODE:
    #   - "off"      : plain RRF merge, take top_k. No re-rank, no LLM.
    #   - "rrf_only" : widen pools, merge by RRF score, take top_k. No LLM. (default)
    #   - "llm"      : ONE batched Haiku relevance-scoring call over the merged
    #                  candidates (RERANK_DEPTH of them), re-order by score.
    # "off"/"rrf_only" MUST NOT call any LLM. We deliberately avoid a local
    # cross-encoder on the 2 vCPU / 4GB droplet. Deploy-time flag.
    RERANK_MODE: str = "rrf_only"
    # How many candidates to pull from EACH of the semantic/text searches before
    # merging (widened from the historical 20).
    RERANK_CANDIDATE_POOL: int = 40
    # How many merged candidates the LLM re-ranker scores in its single batched
    # call (only used when RERANK_MODE == "llm"). Kept small to bound cost/latency.
    RERANK_DEPTH: int = 20
    # Lightweight query normalisation (section-number / synonym) before search.
    QUERY_NORMALISE_ENABLED: bool = True

    # --- Firm + global merged ranking (Task C4) -------------------------------
    # research._retrieve_context merges global + firm candidates into ONE pool and
    # ranks them together instead of appending firm chunks after global truncation.
    # The firm weight multiplies the firm chunk's score so it participates in the
    # merged ranking (was a dead 1.5x that never ranked).
    RETRIEVAL_TOP_K: int = 10
    RETRIEVAL_GLOBAL_POOL: int = 8
    RETRIEVAL_FIRM_POOL: int = 4
    FIRM_CHUNK_WEIGHT: float = 1.5

    # --- Verify gating (Task B2 / C3) -----------------------------------------
    # Verification no longer runs on every answer. It runs ONLY on risky answers:
    # low estimated confidence, few/zero parsed citations, or the "insufficient
    # information" phrase. The default verify model is Haiku; Sonnet is reserved
    # for flagged (risky) answers. Deploy-time flags.
    VERIFY_MODEL: str = "claude-haiku-4-5"
    VERIFY_CONFIDENCE_THRESHOLD: float = 0.60
    VERIFY_MIN_CITATIONS: int = 1
    # When True, a needs_correction/unreliable verification (or a critical issue)
    # triggers ONE bounded corrective regeneration pass (no loops).
    CORRECTIVE_PASS_ENABLED: bool = True

    # --- Per-client answer cache (Task B3) ------------------------------------
    # DB-backed answer cache keyed on (normalised question, client_id,
    # knowledge_version). DB-backed (not in-process) because prod runs 2 uvicorn
    # workers; an ingest bumps knowledge_version so all workers invalidate
    # atomically. Short TTL is a backstop. Deploy-time flags.
    ANSWER_CACHE_ENABLED: bool = True
    ANSWER_CACHE_TTL_SECONDS: int = 3600


settings = Settings()  # type: ignore[call-arg]
