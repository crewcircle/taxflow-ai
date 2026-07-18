"""Tests for the LiteLLM embedding adapter + dimension guard (Task A2).

``litellm.aembedding`` is monkeypatched (patched where used, in the adapter
module) so no real API calls are made. We assert ``embed`` returns the vector,
``embed_batch`` chunks by 100 (250 texts -> 3 aembedding calls), ``dimension``,
and that the startup dimension guard raises on a wrong-length vector.
"""

from __future__ import annotations

import pytest

from taxflow import providers
from taxflow.adapters.embedding import litellm_adapter
from taxflow.adapters.embedding.litellm_adapter import LiteLLMEmbeddingAdapter
from taxflow.ports.embedding import EmbeddingPort

EMBED_DIM = 1536


# --- fakes -------------------------------------------------------------------
class _EmbeddingResponse:
    """Stands in for LiteLLM's embedding response (``.data`` is a list)."""

    def __init__(self, data):
        self.data = data


class _EmbeddingItemObj:
    """A ``data`` item exposing ``.embedding`` (object shape)."""

    def __init__(self, embedding):
        self.embedding = embedding


def _fake_aembedding(vector, capture: dict, *, item_style="dict"):
    """Return a fake ``aembedding`` that echoes one vector per input item."""

    async def _inner(**kwargs):
        capture.setdefault("calls", []).append(kwargs)
        raw = kwargs["input"]
        items = raw if isinstance(raw, list) else [raw]
        if item_style == "dict":
            data = [{"embedding": list(vector)} for _ in items]
        else:
            data = [_EmbeddingItemObj(list(vector)) for _ in items]
        return _EmbeddingResponse(data)

    return _inner


# --- embed -------------------------------------------------------------------
@pytest.mark.asyncio
async def test_embed_returns_vector_dict_shape(monkeypatch):
    capture: dict = {}
    vec = [0.1] * EMBED_DIM
    monkeypatch.setattr(
        litellm_adapter.litellm, "aembedding", _fake_aembedding(vec, capture)
    )

    adapter = LiteLLMEmbeddingAdapter()
    result = await adapter.embed("hello")

    assert result == vec
    assert len(capture["calls"]) == 1
    assert capture["calls"][0]["input"] == "hello"
    # openai provider -> bare model string passed through
    assert capture["calls"][0]["model"] == "text-embedding-3-small"


@pytest.mark.asyncio
async def test_embed_returns_vector_object_shape(monkeypatch):
    capture: dict = {}
    vec = [0.2] * EMBED_DIM
    monkeypatch.setattr(
        litellm_adapter.litellm,
        "aembedding",
        _fake_aembedding(vec, capture, item_style="object"),
    )

    adapter = LiteLLMEmbeddingAdapter()
    result = await adapter.embed("hello")

    assert result == vec


@pytest.mark.asyncio
async def test_embed_truncates_long_input(monkeypatch):
    capture: dict = {}
    monkeypatch.setattr(
        litellm_adapter.litellm, "aembedding", _fake_aembedding([0.0] * EMBED_DIM, capture)
    )

    adapter = LiteLLMEmbeddingAdapter()
    long_text = "x" * (litellm_adapter.MAX_INPUT_TOKENS * 4 + 500)
    await adapter.embed(long_text)

    sent = capture["calls"][0]["input"]
    assert len(sent) == litellm_adapter.MAX_INPUT_TOKENS * 4


# --- embed_batch -------------------------------------------------------------
@pytest.mark.asyncio
async def test_embed_forwards_api_key(monkeypatch):
    """The composition root injects the configured OPENAI_API_KEY; the adapter
    must forward it to litellm.aembedding (BaseSettings env_file does not export
    into os.environ, so implicit env lookup would break key-only-in-.env runs)."""
    capture: dict = {}
    monkeypatch.setattr(
        litellm_adapter.litellm, "aembedding", _fake_aembedding([0.0] * EMBED_DIM, capture)
    )

    adapter = LiteLLMEmbeddingAdapter(api_key="sk-test-openai")
    await adapter.embed("hello")

    assert capture["calls"][0]["api_key"] == "sk-test-openai"


@pytest.mark.asyncio
async def test_embed_batch_chunks_by_100(monkeypatch):
    capture: dict = {}
    vec = [0.3] * EMBED_DIM
    monkeypatch.setattr(
        litellm_adapter.litellm, "aembedding", _fake_aembedding(vec, capture)
    )

    adapter = LiteLLMEmbeddingAdapter()
    texts = [f"text-{i}" for i in range(250)]
    results = await adapter.embed_batch(texts)

    # 250 texts -> 3 aembedding calls (100 + 100 + 50)
    assert len(capture["calls"]) == 3
    batch_sizes = [len(c["input"]) for c in capture["calls"]]
    assert batch_sizes == [100, 100, 50]
    assert len(results) == 250
    assert all(r == vec for r in results)


@pytest.mark.asyncio
async def test_embed_batch_truncates_per_item(monkeypatch):
    capture: dict = {}
    monkeypatch.setattr(
        litellm_adapter.litellm, "aembedding", _fake_aembedding([0.0] * EMBED_DIM, capture)
    )

    adapter = LiteLLMEmbeddingAdapter()
    long_text = "y" * (litellm_adapter.MAX_INPUT_TOKENS * 4 + 100)
    await adapter.embed_batch([long_text, "short"])

    sent = capture["calls"][0]["input"]
    assert len(sent[0]) == litellm_adapter.MAX_INPUT_TOKENS * 4
    assert sent[1] == "short"


# --- dimension + protocol ----------------------------------------------------
def test_dimension_is_1536():
    assert LiteLLMEmbeddingAdapter().dimension == EMBED_DIM


def test_adapter_satisfies_embedding_port():
    assert isinstance(LiteLLMEmbeddingAdapter(), EmbeddingPort)


# --- module-level delegating functions ---------------------------------------
@pytest.mark.asyncio
async def test_embedder_module_functions_delegate(monkeypatch):
    from taxflow.services.knowledge import embedder

    capture: dict = {}
    vec = [0.4] * EMBED_DIM
    monkeypatch.setattr(
        litellm_adapter.litellm, "aembedding", _fake_aembedding(vec, capture)
    )
    providers.reset_providers()

    assert await embedder.embed("hi") == vec
    batch = await embedder.embed_batch(["a", "b"])
    assert batch == [vec, vec]
    # back-compat constants preserved
    assert embedder.EMBEDDING_MODEL == "text-embedding-3-small"
    assert embedder.MAX_INPUT_TOKENS == 8192

    providers.reset_providers()


# --- startup dimension guard -------------------------------------------------
class _FakeEmbedder:
    def __init__(self, length: int):
        self._length = length

    async def embed(self, text: str) -> list[float]:
        return [0.0] * self._length

    async def embed_batch(self, texts):
        return [[0.0] * self._length for _ in texts]

    @property
    def dimension(self) -> int:
        return self._length


@pytest.mark.asyncio
async def test_startup_guard_raises_on_wrong_dimension(monkeypatch):
    from taxflow import main

    monkeypatch.setattr(
        providers, "get_embedder", lambda: _FakeEmbedder(1024)
    )

    with pytest.raises(RuntimeError, match="dimension mismatch"):
        await main._assert_embedding_dimension()


@pytest.mark.asyncio
async def test_startup_guard_passes_on_correct_dimension(monkeypatch):
    from taxflow import main

    monkeypatch.setattr(
        providers, "get_embedder", lambda: _FakeEmbedder(EMBED_DIM)
    )

    # Should not raise.
    await main._assert_embedding_dimension()


@pytest.mark.asyncio
async def test_lifespan_guard_raises_on_wrong_dimension(monkeypatch):
    """The guard is wired into lifespan (before start_scheduler) and honours the
    EMBEDDING_DIM_GUARD_ENABLED flag."""
    from taxflow import main
    from taxflow.config import settings

    monkeypatch.setattr(settings, "EMBEDDING_DIM_GUARD_ENABLED", True)
    monkeypatch.setattr(providers, "get_embedder", lambda: _FakeEmbedder(1024))
    # Guard runs before start_scheduler -> scheduler must never be reached.
    called = {"scheduler": False}
    monkeypatch.setattr(main, "start_scheduler", lambda: called.__setitem__("scheduler", True))
    monkeypatch.setattr(main, "stop_scheduler", lambda: None)

    with pytest.raises(RuntimeError, match="dimension mismatch"):
        async with main.lifespan(main.app):
            pass
    assert called["scheduler"] is False
