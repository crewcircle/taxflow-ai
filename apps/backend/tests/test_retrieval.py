"""Tests for retrieval embedding reuse and pgvector probes tuning (Tasks A4/A5)."""
from unittest.mock import AsyncMock, patch

import pytest

from taxflow import providers
from taxflow.services.knowledge import retrieval


class _FakeVectorStore:
    """Fake VectorStorePort with the three async methods (Task A3)."""

    def __init__(self, semantic=None, textual=None, firm=None):
        self.semantic_search = AsyncMock(return_value=semantic or [])
        self.text_search = AsyncMock(return_value=textual or [])
        self.firm_search = AsyncMock(return_value=firm or [])


@pytest.mark.asyncio
async def test_hybrid_search_reuses_provided_embedding():
    vec = [0.3] * 1536

    with patch.object(retrieval, "embed", new=AsyncMock()) as mock_embed, patch.object(
        providers, "get_vector_store", return_value=_FakeVectorStore()
    ):
        await retrieval.hybrid_search("q", top_k=8, embedding=vec)

    # A caller-supplied vector must be reused; no extra OpenAI embed round trip.
    mock_embed.assert_not_awaited()


@pytest.mark.asyncio
async def test_hybrid_search_embeds_when_no_embedding_given():
    with patch.object(retrieval, "embed", new=AsyncMock(return_value=[0.0] * 1536)) as mock_embed, patch.object(
        providers, "get_vector_store", return_value=_FakeVectorStore()
    ):
        await retrieval.hybrid_search("q", top_k=8)

    mock_embed.assert_awaited_once()


@pytest.mark.asyncio
async def test_generate_candidates_delegates_to_vector_store():
    """generate_candidates must call the port's semantic_search/text_search."""
    store = _FakeVectorStore()
    with patch.object(providers, "get_vector_store", return_value=store):
        await retrieval.generate_candidates("q", source_types=["legislation"], embedding=[0.1] * 1536)

    store.semantic_search.assert_awaited_once()
    store.text_search.assert_awaited_once()
    # source_types forwarded to both search methods.
    assert store.semantic_search.await_args.kwargs["source_types"] == ["legislation"]
    assert store.text_search.await_args.kwargs["source_types"] == ["legislation"]
