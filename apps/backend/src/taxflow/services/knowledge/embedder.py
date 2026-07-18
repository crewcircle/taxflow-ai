"""Text embedding helpers.

The concrete embedding API call now lives in the LiteLLM embedding adapter
(:class:`taxflow.adapters.embedding.litellm_adapter.LiteLLMEmbeddingAdapter`).
These module-level functions delegate to the configured ``EmbeddingPort`` via
``providers.get_embedder()`` so existing callers keep importing ``embed`` /
``embed_batch`` from here unchanged.

``EMBEDDING_MODEL`` and ``MAX_INPUT_TOKENS`` are kept for back-compat (some
callers/tests import them).
"""

from taxflow import providers

EMBEDDING_MODEL = "text-embedding-3-small"
MAX_INPUT_TOKENS = 8192


async def embed(text: str) -> list[float]:
    return await providers.get_embedder().embed(text)


async def embed_batch(texts: list[str]) -> list[list[float]]:
    return await providers.get_embedder().embed_batch(texts)
