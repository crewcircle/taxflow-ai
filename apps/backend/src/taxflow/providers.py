"""Composition root / provider registry for the ports-and-adapters architecture.

Business/service code depends on the port Protocols in ``taxflow.ports``; this
module is the ONE place that maps configuration to a concrete vendor adapter and
memoises it. Accessors are lazy so importing this module never constructs a
vendor client, and tests can monkeypatch ``taxflow.providers.get_*`` or clear the
cache with :func:`reset_providers`.

Each accessor picks its adapter from the corresponding ``settings.*_PROVIDER``
knob, defaulting to today's stack (Anthropic + OpenAI + Postgres/pgvector +
Supabase Auth + Stripe + R2 + APScheduler). Domain adapters register themselves
by being imported inside the accessor (keeps optional deps out of import time).
"""

from __future__ import annotations

from functools import lru_cache

from taxflow.config import settings


# --- model tier resolution ---------------------------------------------------
def resolve_model(tier: str) -> str:
    """Map an abstract model tier ("haiku"/"sonnet") to a concrete model string.

    Prefers ``settings.MODEL_TIER_MAP``; falls back to the legacy
    ``ANTHROPIC_*_MODEL`` fields so behaviour is unchanged when the map is absent.
    """
    mapped = settings.MODEL_TIER_MAP.get(tier)
    if mapped:
        return mapped
    legacy = {
        "haiku": settings.ANTHROPIC_HAIKU_MODEL,
        "sonnet": settings.ANTHROPIC_SONNET_MODEL,
    }
    if tier in legacy:
        # Legacy fields are bare Claude IDs; prefix so LiteLLM routes to Anthropic.
        model = legacy[tier]
        return model if "/" in model else f"anthropic/{model}"
    # Unknown tier: treat it as an explicit model string.
    return tier


# --- AI core ports (Workstream A) --------------------------------------------
@lru_cache(maxsize=1)
def get_llm():
    """Return the configured LLMPort adapter (memoised)."""
    if settings.LLM_PROVIDER == "anthropic" or settings.LLM_PROVIDER == "litellm":
        from taxflow.adapters.llm.litellm_adapter import LiteLLMAdapter

        return LiteLLMAdapter(api_key=settings.ANTHROPIC_API_KEY)
    raise ValueError(f"Unknown LLM_PROVIDER: {settings.LLM_PROVIDER}")


@lru_cache(maxsize=1)
def get_embedder():
    """Return the configured EmbeddingPort adapter (memoised)."""
    if settings.EMBEDDING_PROVIDER in ("openai", "litellm"):
        from taxflow.adapters.embedding.litellm_adapter import LiteLLMEmbeddingAdapter

        return LiteLLMEmbeddingAdapter(api_key=settings.OPENAI_API_KEY or None)
    raise ValueError(f"Unknown EMBEDDING_PROVIDER: {settings.EMBEDDING_PROVIDER}")


@lru_cache(maxsize=1)
def get_vector_store():
    """Return the configured VectorStorePort adapter (memoised)."""
    if settings.RELATIONAL_PROVIDER == "postgres":
        from taxflow.adapters.vectorstore.pgvector import PgVectorStore

        return PgVectorStore()
    raise ValueError(f"Unknown vector store provider: {settings.RELATIONAL_PROVIDER}")


# --- infrastructure ports (Workstream B) -------------------------------------
@lru_cache(maxsize=1)
def get_relational_data():
    """Return the RelationalDataPort facade (repositories)."""
    if settings.RELATIONAL_PROVIDER == "postgres":
        from taxflow.adapters.db.repositories import Repositories

        return Repositories()
    raise ValueError(f"Unknown RELATIONAL_PROVIDER: {settings.RELATIONAL_PROVIDER}")


@lru_cache(maxsize=1)
def get_object_storage():
    """Return the configured ObjectStoragePort adapter (memoised)."""
    if settings.OBJECT_STORAGE_PROVIDER in ("r2", "s3"):
        from taxflow.adapters.storage.s3 import S3ObjectStorageAdapter

        return S3ObjectStorageAdapter()
    raise ValueError(f"Unknown OBJECT_STORAGE_PROVIDER: {settings.OBJECT_STORAGE_PROVIDER}")


@lru_cache(maxsize=1)
def get_auth_port():
    """Return the configured AuthPort adapter (memoised)."""
    if settings.AUTH_PROVIDER == "supabase":
        from taxflow.adapters.auth.supabase import SupabaseAuthAdapter

        return SupabaseAuthAdapter()
    raise ValueError(f"Unknown AUTH_PROVIDER: {settings.AUTH_PROVIDER}")


@lru_cache(maxsize=1)
def get_billing_port():
    """Return the configured BillingPort adapter (memoised)."""
    if settings.BILLING_PROVIDER == "stripe":
        from taxflow.adapters.billing.stripe import StripeBillingAdapter

        return StripeBillingAdapter()
    raise ValueError(f"Unknown BILLING_PROVIDER: {settings.BILLING_PROVIDER}")


@lru_cache(maxsize=1)
def get_scheduler_port():
    """Return the configured SchedulerPort adapter (memoised)."""
    if settings.SCHEDULER_PROVIDER == "apscheduler":
        from taxflow.adapters.scheduler.apscheduler import APSchedulerAdapter

        return APSchedulerAdapter()
    raise ValueError(f"Unknown SCHEDULER_PROVIDER: {settings.SCHEDULER_PROVIDER}")


@lru_cache(maxsize=1)
def get_scraper_registry():
    """Return the source-scraper registry (list of SourceScraperPort classes)."""
    from taxflow.adapters.scrapers import SCRAPER_REGISTRY

    return SCRAPER_REGISTRY


@lru_cache(maxsize=1)
def get_document_renderer():
    """Return the configured DocumentRenderPort adapter (memoised)."""
    if settings.DOCUMENT_RENDER_PROVIDER == "docx_pdf":
        from taxflow.adapters.render.docx_pdf import DocxPdfRenderer

        return DocxPdfRenderer()
    raise ValueError(f"Unknown DOCUMENT_RENDER_PROVIDER: {settings.DOCUMENT_RENDER_PROVIDER}")


@lru_cache(maxsize=1)
def get_tokenizer():
    """Return the configured TokenizerPort adapter (memoised)."""
    if settings.TOKENIZER_PROVIDER == "tiktoken":
        from taxflow.adapters.tokenizer.tiktoken import TiktokenTokenizer

        return TiktokenTokenizer()
    raise ValueError(f"Unknown TOKENIZER_PROVIDER: {settings.TOKENIZER_PROVIDER}")


def reset_providers() -> None:
    """Clear all memoised adapters (test helper; use after monkeypatching config)."""
    for fn in (
        get_llm,
        get_embedder,
        get_vector_store,
        get_relational_data,
        get_object_storage,
        get_auth_port,
        get_billing_port,
        get_scheduler_port,
        get_scraper_registry,
        get_document_renderer,
        get_tokenizer,
    ):
        fn.cache_clear()
