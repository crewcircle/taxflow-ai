"""LiteLLM adapter implementing :class:`taxflow.ports.embedding.EmbeddingPort` (Task A2).

LiteLLM gives us a single vendor-neutral client (``litellm.aembedding``) that
routes to OpenAI today (``text-embedding-3-small``) and to any other provider by
changing the ``model`` string. This adapter preserves today's embedder behaviour:
the ``text[:MAX_INPUT_TOKENS*4]`` char truncation and the 100-item batch chunking.

LiteLLM's embedding response ``data`` items may be dicts (``item["embedding"]``)
or objects (``item.embedding``); ``_extract_embedding`` handles both shapes.
"""

from __future__ import annotations

import asyncio
from typing import Any

from taxflow.config import settings

import litellm

# Preserved from the previous embedder.py implementation.
EMBEDDING_MODEL = "text-embedding-3-small"
MAX_INPUT_TOKENS = 8192

# Batch chunk size, matching today's embedder (100 items per request).
_BATCH_SIZE = 100

# Number of attempts (with exponential backoff) on provider rate-limit (429)
# errors before giving up.
_MAX_RETRIES = 5


def _model_string() -> str:
    """Build the LiteLLM model string from the configured provider + model.

    For ``openai`` LiteLLM treats a bare ``text-embedding-3-small`` as OpenAI, so
    passing it directly works; other providers get the ``<provider>/<model>``
    route so LiteLLM can dispatch correctly.
    """
    provider = settings.EMBEDDING_PROVIDER
    model = settings.EMBEDDING_MODEL
    if provider == "openai":
        return model
    return f"{provider}/{model}"


def _truncate(text: str) -> str:
    return text[: MAX_INPUT_TOKENS * 4]


def _extract_embedding(item: Any) -> list[float]:
    """Pull the embedding vector from a LiteLLM ``data`` item.

    Items may be dict-like (``{"embedding": [...]}`` ) or objects exposing an
    ``.embedding`` attribute; support both robustly.
    """
    if isinstance(item, dict):
        return item["embedding"]
    return item.embedding


class LiteLLMEmbeddingAdapter:
    """Concrete :class:`EmbeddingPort` backed by ``litellm.aembedding``."""

    def __init__(self, api_key: str | None = None) -> None:
        # See LiteLLMAdapter.__init__: Pydantic ``BaseSettings(env_file=...)``
        # does not export keys into ``os.environ``, so the composition root
        # injects ``settings.OPENAI_API_KEY`` explicitly (None falls back to
        # LiteLLM's implicit env lookup).
        self._api_key = api_key or None

    async def _aembedding_with_retry(self, input_: Any):
        """Call ``litellm.aembedding`` with exponential backoff on 429s.

        Large ingest runs (a whole Act's worth of chunks, hundreds of batches
        back to back) can burst past the account's tokens-per-minute limit even
        though any single batch is well within it — this was previously uncaught
        and aborted the whole ingest partway through.
        """
        for attempt in range(_MAX_RETRIES):
            try:
                return await litellm.aembedding(
                    model=_model_string(), input=input_, api_key=self._api_key
                )
            except litellm.exceptions.RateLimitError:
                if attempt == _MAX_RETRIES - 1:
                    raise
                await asyncio.sleep(2**attempt)
        raise AssertionError("unreachable")

    async def embed(self, text: str) -> list[float]:
        response = await self._aembedding_with_retry(_truncate(text))
        return _extract_embedding(response.data[0])

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        results: list[list[float]] = []
        for i in range(0, len(texts), _BATCH_SIZE):
            batch = [_truncate(t) for t in texts[i : i + _BATCH_SIZE]]
            response = await self._aembedding_with_retry(batch)
            results.extend(_extract_embedding(item) for item in response.data)
        return results

    @property
    def dimension(self) -> int:
        return settings.EMBEDDING_DIMENSION
