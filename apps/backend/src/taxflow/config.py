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

    # --- Structure-aware / hierarchical chunking (Workstream C) ---------------
    # When enabled, ingest splits AU-tax documents on logical units (Part/
    # Division/Section/subsection, numbered ruling paragraphs) with heading
    # breadcrumbs, storing each child chunk alongside its full parent-unit text.
    # When on, retrieval may expand a retrieved child to its parent unit at
    # answer time. Both flags default False = today's exact flat behaviour.
    HIERARCHICAL_CHUNKING_ENABLED: bool = False
    PARENT_EXPANSION_ENABLED: bool = False

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
    #   - ROUTE_MIN_TOP_RRF_SCORE: the top RRF score must clear this.
    #   - ROUTE_MIN_RERANK_SCORE: when RERANK_MODE == "llm", the top rerank score
    #     (a 0-1 relevance score, a DIFFERENT scale from RRF) must clear this to
    #     count as strong. Judged on its own scale so a weak rerank score can't
    #     pass the much smaller RRF threshold and route a weak result to Haiku.
    # When hybrid search returns nothing (the "insufficient information" situation),
    # we always route to Sonnet.
    ROUTE_MIN_STRONG_CHUNKS: int = 5
    ROUTE_MIN_TOP_RRF_SCORE: float = 0.03
    ROUTE_MIN_RERANK_SCORE: float = 0.5

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

    # --- Historical / superseded retrieval pool (Task B2) ---------------------
    # Superseded knowledge chunks (is_current = false) are retrieved as a
    # DOWN-WEIGHTED historical pool and APPENDED after the authoritative top-K —
    # they are never cited as current law and never displace current sources.
    # SUPERSEDED_CHUNK_WEIGHT < 1.0 so a historical chunk always ranks below
    # equivalent current law.
    SUPERSEDED_RETRIEVAL_ENABLED: bool = True
    SUPERSEDED_CHUNK_WEIGHT: float = 0.4
    SUPERSEDED_POOL_SIZE: int = 3

    # --- Engagement context store (Task C4) -----------------------------------
    # Approved client-facing documents are embedded on save into the separate
    # engagement_context table and retrieved as advisory context for future
    # research queries scoped to the SAME client_ref. ENGAGEMENT_CHUNK_WEIGHT > 1.0
    # so a prior engagement memo (highly specific to this client engagement)
    # ranks above equivalent global sources when it matches.
    ENGAGEMENT_CONTEXT_ENABLED: bool = True
    RETRIEVAL_ENGAGEMENT_POOL: int = 4
    ENGAGEMENT_CHUNK_WEIGHT: float = 1.3

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

    # --- Per-client profile injection (Task D1) -------------------------------
    # Build a compact client-profile string (business_type, state, firm_style
    # highlights) once per request and inject it as ADVISORY steering context into
    # the research + ATO drafter prompts. Advisory, never a hard filter, so it
    # cannot starve correct general-law answers. Deploy-time flag; default on.
    PROFILE_INJECTION_ENABLED: bool = True

    # --- source_types soft boost (Task D2) ------------------------------------
    # A source_types hint is derived from the question intent and the client's
    # active_modules, then applied as a SOFT BOOST by default: the candidate pool
    # is retrieved UNFILTERED (so the one relevant doc is never dropped) and
    # matching source_types get their score multiplied by
    # (1 + SOURCE_TYPE_BOOST_WEIGHT) before the merged ranking / re-rank.
    #   - SOURCE_TYPE_FILTER_MODE == "soft" (default): boost only, no exclusion.
    #   - SOURCE_TYPE_FILTER_MODE == "hard": opt-in HARD SQL filter (may exclude
    #     non-matching docs — use with care).
    SOURCE_TYPE_FILTER_MODE: str = "soft"
    SOURCE_TYPE_BOOST_WEIGHT: float = 0.25

    # --- Session memory (Task D3) ---------------------------------------------
    # When a request carries an explicit session_id, the last N prior queries for
    # that (client_id, session_id) are loaded (question + a truncated answer
    # summary) and prepended as a compact "conversation so far" block. Auto-
    # injected ONLY within the same session_id, never across sessions or clients.
    # Summarised at read time (each prior answer truncated to SESSION_SUMMARY_CHARS)
    # to protect the token budget. Single-shot queries (no session_id) are
    # unaffected. Deploy-time flags.
    SESSION_MEMORY_ENABLED: bool = True
    SESSION_HISTORY_N: int = 5
    SESSION_SUMMARY_CHARS: int = 300
    # Each prior QUESTION is also truncated (a few very long prior questions
    # could otherwise blow up the block despite the answer summary cap), and the
    # whole block is capped at SESSION_BLOCK_MAX_CHARS — once the budget is
    # reached we stop adding older turns, so the session context can never grow
    # unbounded regardless of SESSION_HISTORY_N.
    SESSION_QUESTION_CHARS: int = 200
    SESSION_BLOCK_MAX_CHARS: int = 2000

    # --- Ports-and-adapters provider selection (hexagonal refactor) -----------
    # Each coupled subsystem is chosen by a provider knob so the concrete vendor
    # adapter is swappable via config, not code. Defaults reproduce today's stack.
    LLM_PROVIDER: str = "anthropic"
    # Optional LiteLLM base URL + keys for routing generation to an OpenAI-
    # compatible gateway (e.g. OpenCode). Empty LLM_API_BASE => Anthropic default
    # (OpenCode strictly opt-in). Key-resolution precedence lives in
    # providers.get_llm() and is documented in docs/model-routing.md.
    LLM_API_BASE: str = ""
    LLM_API_KEY: str = ""
    OPENCODE_API_KEY: str = ""
    EMBEDDING_PROVIDER: str = "openai"
    RELATIONAL_PROVIDER: str = "postgres"
    AUTH_PROVIDER: str = "supabase"
    BILLING_PROVIDER: str = "stripe"
    OBJECT_STORAGE_PROVIDER: str = "r2"
    SCHEDULER_PROVIDER: str = "apscheduler"
    DOCUMENT_RENDER_PROVIDER: str = "docx_pdf"
    TOKENIZER_PROVIDER: str = "tiktoken"

    # Embedding model + dimension moved out of embedder.py so a provider/model
    # swap is config-driven. The DB vector() columns (migrations 003/006) and
    # seed.sql are 1536-dim, so changing EMBEDDING_DIMENSION is a breaking change
    # requiring an ALTER + reindex + full re-embed. A startup probe guard asserts
    # the live model's real output length equals EMBEDDING_DIMENSION.
    EMBEDDING_MODEL: str = "text-embedding-3-small"
    EMBEDDING_DIMENSION: int = 1536
    EMBEDDING_DIM_GUARD_ENABLED: bool = True

    # Provider-neutral model tiers. route_model()/verify keep emitting the
    # abstract tier names ("haiku"/"sonnet"); resolve_model(tier) maps a tier to
    # a LiteLLM model string (provider/model). Falls back to the legacy
    # ANTHROPIC_*_MODEL fields when a tier is absent from the map.
    MODEL_TIER_MAP: dict[str, str] = {
        "haiku": "anthropic/claude-haiku-4-5",
        "sonnet": "anthropic/claude-sonnet-4-6",
        # Named per-agent tiers (all Anthropic today; concrete OpenCode IDs are
        # set per-deployment in Doppler). resolve_model() also falls back through
        # _TIER_ALIAS so an agent tier still resolves when omitted here.
        "draft": "anthropic/claude-haiku-4-5",
        "verify": "anthropic/claude-haiku-4-5",
        "rerank": "anthropic/claude-haiku-4-5",
        "classify": "anthropic/claude-haiku-4-5",
        "verify_strong": "anthropic/claude-sonnet-4-6",
    }

    # Tokenizer used for chunk sizing (was hard-coded tiktoken cl100k_base).
    TOKENIZER_MODEL: str = "cl100k_base"

    # Optional confidence-gated single re-retrieval inside the bounded agent loop
    # (LangGraph). Off by default so cost/behaviour is unchanged out of the box.
    RE_RETRIEVE_ENABLED: bool = False
    RE_RETRIEVE_MIN_TOP_SCORE: float = 0.03

    # --- Phase 4: clarifying questions (dark launch, default OFF) -------------
    # A cheap deterministic pre-filter (should_clarify, mirroring should_verify)
    # gates a Haiku ambiguity classifier; when it fires the graph short-circuits
    # to a terminal `clarify` outcome (NO generation) and the UI re-submits on
    # the same session with the selected clarifications. Flag-gated OFF pending
    # eval, mirroring RE_RETRIEVE_ENABLED.
    #   - CLARIFY_CONFIDENCE_THRESHOLD: the classifier must clear this to clarify;
    #     below it we answer directly (fail-open, tunable like VERIFY threshold).
    #   - CLARIFY_MAX_QUESTIONS / CLARIFY_MAX_OPTIONS: anti-annoyance caps.
    CLARIFY_ENABLED: bool = False
    CLARIFY_CONFIDENCE_THRESHOLD: float = 0.70
    CLARIFY_MAX_QUESTIONS: int = 2
    CLARIFY_MAX_OPTIONS: int = 4

    # --- Phase 4: suggested follow-ups (dark launch, default OFF) -------------
    # FOLLOW_UP_STRATEGY "inline" (chosen path) folds 2-3 follow-up questions
    # into the SINGLE generate call as a trailing delimited block (ZERO extra
    # LLM calls), parsed out tolerantly and emitted as a separate `follow_ups`
    # SSE event after `final`. "async" is the documented alternative (a separate
    # gated Haiku call). Flag-gated OFF pending eval.
    FOLLOW_UP_ENABLED: bool = False
    FOLLOW_UP_COUNT: int = 3
    FOLLOW_UP_STRATEGY: str = "inline"

    # Reviewer-driven widened retrieval (Task C3): when the inline corrective
    # pass runs, retrieval is re-run with a widened candidate pool (pool_scale=2)
    # threaded as a per-call PARAMETER — never by mutating the global pool
    # settings, so concurrent requests can never inherit a widened pool.
    REVIEWER_WIDEN_ENABLED: bool = True

    # --- Feedback-triggered async re-research (Task C2) -----------------------
    # A user thumbs-down WITH a note enqueues a background re-research job (see
    # re_research_jobs). A scheduler interval job drains the queue (leader-guarded
    # so only one worker runs it), re-running the answer with the user's stated
    # issue and a widened retrieval pool, then notifies the user. Reviewer/verify
    # flags stay SYNCHRONOUS (the inline corrective pass) and are never enqueued.
    #   - RE_RESEARCH_POLL_SECONDS: drain interval.
    #   - RE_RESEARCH_MAX_ATTEMPTS: bounded retry ceiling before terminal 'failed'.
    #   - RE_RESEARCH_BACKOFF_SECONDS: delay added to next_attempt_at on a requeue.
    RE_RESEARCH_ENABLED: bool = True
    RE_RESEARCH_POLL_SECONDS: int = 30
    RE_RESEARCH_MAX_ATTEMPTS: int = 3
    RE_RESEARCH_BACKOFF_SECONDS: int = 120

    # --- Approval-gated learning loop (Task C5) -------------------------------
    # A thumbs-up or a saved advice_memo creates a PENDING knowledge_suggestion
    # rather than writing straight into the authoritative firm_knowledge store;
    # a partner approves (embeds into firm_knowledge) or rejects it. Also gates
    # the cited-firm-chunk usage_count increment on the answer flow.
    LEARNING_LOOP_ENABLED: bool = True

    # --- Firm-level editable document templates (Phase 5) --------------------
    # When enabled, the drafting sites resolve the system prompt for a document
    # type from the firm's stored document_templates row (if present) else the
    # code-owned system default. Default OFF so the feature ships dark and
    # behaviour is byte-identical to today until a firm opts in.
    DOCUMENT_TEMPLATES_ENABLED: bool = False

    # --- Eval harness (Workstream B) -----------------------------------------
    # The LLM-as-judge resolves its model through providers.resolve_model, same
    # as every production call-site, so it follows the model-routing invariant
    # (Workstream A) — EVAL_JUDGE_TIER is a TIER name, never a bare model string.
    EVAL_JUDGE_TIER: str = "sonnet"
    # Per-tier token pricing in USD per 1M tokens. `input`/`output` are the base
    # rates; `cache_read`/`cache_creation` cover Anthropic prompt-cache pricing
    # (cache reads are ~10% of input, cache writes ~125%). Used by cost.run_cost.
    EVAL_MODEL_PRICING: dict[str, dict[str, float]] = {
        "haiku": {"input": 1.00, "output": 5.00, "cache_read": 0.10, "cache_creation": 1.25},
        "sonnet": {"input": 3.00, "output": 15.00, "cache_read": 0.30, "cache_creation": 3.75},
    }
    # k used for recall@k / nDCG@k in the eval harness (mirrors retrieval depth).
    EVAL_RECALL_K: int = RETRIEVAL_TOP_K
    # Regression tolerance (absolute metric delta) below which a run-over-run
    # change is treated as noise rather than a regression.
    EVAL_REGRESSION_TOLERANCE: float = 0.05
    # Eval-only: when True, ResearchAgent.run() echoes the EXACT rendered context
    # string it generated from back on the result (``eval_context``) so the
    # LLM-as-judge grades against the sources the answer actually saw — not a
    # re-derived candidate list. Default False keeps production output unchanged;
    # only the paid eval runner flips it on.
    EVAL_CAPTURE_CONTEXT: bool = False

    # --- Production drift monitor (Task 3a-1 / 3a-2) --------------------------
    # A daily leader-guarded job aggregates the trailing production window and
    # diffs it against a longer baseline window (services.eval.drift), persists a
    # snapshot, and raises an ops alert on regression. DRIFT_MONITOR_ENABLED
    # gates the whole job; the two window sizes bound the [start, end) ranges the
    # job passes to QueriesRepo.stats (current = trailing DRIFT_WINDOW_DAYS,
    # baseline = the DRIFT_BASELINE_WINDOW_DAYS window ending where the current
    # window begins).
    DRIFT_MONITOR_ENABLED: bool = True
    DRIFT_WINDOW_DAYS: int = 1
    DRIFT_BASELINE_WINDOW_DAYS: int = 7
    # Per-metric drift tolerances (absolute delta below which a window-over-
    # window change is noise, not a regression). Rate metrics (0-1 fractions /
    # 0-5 confidence) reuse the eval regression tolerance so eval + drift agree
    # on what "meaningful" means; cost + latency need their own units (USD and
    # milliseconds), so they are explicit.
    DRIFT_FEEDBACK_DOWN_RATE_TOLERANCE: float = EVAL_REGRESSION_TOLERANCE
    DRIFT_VERIFICATION_FAILURE_RATE_TOLERANCE: float = EVAL_REGRESSION_TOLERANCE
    DRIFT_CONFIDENCE_TOLERANCE: float = EVAL_REGRESSION_TOLERANCE
    DRIFT_CITATION_VALIDITY_RATE_TOLERANCE: float = EVAL_REGRESSION_TOLERANCE
    DRIFT_COST_TOLERANCE_USD: float = 0.05
    DRIFT_LATENCY_TOLERANCE_MS: float = 500.0

    # Object storage (S3-compatible / Cloudflare R2). Moved out of os.environ in
    # services/storage/r2.py into config. Empty defaults preserve the graceful
    # "storage unconfigured -> None" degradation.
    R2_ACCOUNT_ID: str = ""
    R2_ACCESS_KEY_ID: str = ""
    R2_SECRET_ACCESS_KEY: str = ""
    R2_BUCKET_NAME: str = ""

    # --- Admin / operator observability endpoint (Task 2b) --------------------
    # Bearer-style shared secret guarding the operator-global ``/admin/*``
    # endpoints (checked with secrets.compare_digest against the X-Admin-Token
    # header). Empty (the default) DISABLES the feature entirely: require_admin
    # returns 404 so the endpoints are invisible until an operator sets a token.
    ADMIN_API_TOKEN: str = ""


settings = Settings()  # type: ignore[call-arg]
