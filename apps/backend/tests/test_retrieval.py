"""Tests for retrieval embedding reuse and pgvector probes tuning (Tasks A4/A5)."""
from unittest.mock import AsyncMock, patch

import pytest

from taxflow import providers
from taxflow.services.knowledge import retrieval


class _FakeVectorStore:
    """Fake VectorStorePort with the async search methods (Tasks A3 / B2)."""

    def __init__(self, semantic=None, textual=None, firm=None, historical=None):
        self.semantic_search = AsyncMock(return_value=semantic or [])
        self.text_search = AsyncMock(return_value=textual or [])
        self.firm_search = AsyncMock(return_value=firm or [])
        self.historical_search = AsyncMock(return_value=historical or [])
        self.engagement_search = AsyncMock(return_value=[])


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


@pytest.mark.asyncio
async def test_generate_historical_candidates_delegates_with_limit():
    """generate_historical_candidates delegates to the port's historical_search
    with the passed limit and maps rows carrying superseded_by/score."""
    store = _FakeVectorStore(
        historical=[
            {
                "id": 7,
                "citation": "TR 2015/1 (withdrawn)",
                "content": "old ruling text",
                "source_url": "http://ato/tr2015-1",
                "source_object_key": None,
                "source_type": "ruling",
                "last_scraped_at": None,
                "superseded_by": "TR 2022/3",
                "cosine_sim": 0.55,
            }
        ]
    )
    with patch.object(providers, "get_vector_store", return_value=store):
        cands = await retrieval.generate_historical_candidates(
            "q", embedding=[0.1] * 1536, limit=5
        )

    store.historical_search.assert_awaited_once()
    assert store.historical_search.await_args.kwargs["limit"] == 5
    # Reused the caller-supplied embedding — no delegated text/semantic search.
    assert cands[0]["id"] == "7"
    assert cands[0]["superseded_by"] == "TR 2022/3"
    assert cands[0]["score"] == pytest.approx(0.55)


@pytest.mark.asyncio
async def test_generate_historical_candidates_embeds_when_no_embedding():
    store = _FakeVectorStore()
    with patch.object(
        retrieval, "embed", new=AsyncMock(return_value=[0.0] * 1536)
    ) as mock_embed, patch.object(providers, "get_vector_store", return_value=store):
        await retrieval.generate_historical_candidates("q", limit=3)

    mock_embed.assert_awaited_once()
    assert store.historical_search.await_args.kwargs["limit"] == 3


# --- Retrieval-merge: historical pool appended after authoritative top-K (B2) --


def _authoritative(n):
    return [
        {"id": str(i), "citation": f"c{i}", "content": "x", "source_url": "", "score": 0.9 - i * 0.01}
        for i in range(n)
    ]


@pytest.mark.asyncio
async def test_retrieve_context_appends_downweighted_tagged_historical():
    from taxflow.config import settings
    from taxflow.services.agents import research

    agent = research.ResearchAgent()
    auth = _authoritative(3)
    historical = [
        {"id": "h1", "citation": "TR 2015/1", "content": "old", "source_url": "",
         "source_type": "ruling", "superseded_by": "TR 2022/3", "score": 0.6},
        {"id": "h2", "citation": "TR 2010/2", "content": "older", "source_url": "",
         "source_type": "ruling", "superseded_by": "TR 2015/1", "score": 0.5},
    ]

    with patch.object(research, "generate_candidates", new=AsyncMock(return_value=list(auth))), \
        patch.object(research, "rerank_candidates", new=AsyncMock(side_effect=lambda q, c, **k: c)), \
        patch.object(research, "generate_historical_candidates", new=AsyncMock(return_value=historical)), \
        patch.object(agent, "_firm_knowledge_search", new=AsyncMock(return_value=[])):
        chunks, signals = await agent._retrieve_context("q", "cid", embedding=[0.1] * 1536)

    # Authoritative top-K come first, in order; historical appended after them.
    assert [c["id"] for c in chunks[:3]] == ["0", "1", "2"]
    hist = chunks[3:]
    assert [c["id"] for c in hist] == ["h1", "h2"]
    # Each historical chunk is down-weighted and tagged.
    assert hist[0]["score"] == pytest.approx(0.6 * settings.SUPERSEDED_CHUNK_WEIGHT)
    assert hist[1]["score"] == pytest.approx(0.5 * settings.SUPERSEDED_CHUNK_WEIGHT)
    assert all(c["is_historical"] and c["is_superseded"] for c in hist)
    assert hist[0]["superseded_by"] == "TR 2022/3"
    # Signals are derived from the global pool only — no historical influence.
    assert signals["num_chunks"] == 3
    assert signals["top_score"] == pytest.approx(0.9)


@pytest.mark.asyncio
async def test_retrieve_context_no_historical_when_disabled(monkeypatch):
    from taxflow.config import settings
    from taxflow.services.agents import research

    monkeypatch.setattr(settings, "SUPERSEDED_RETRIEVAL_ENABLED", False)
    agent = research.ResearchAgent()
    auth = _authoritative(3)
    hist_mock = AsyncMock(return_value=[{"id": "h1", "citation": "x", "content": "y",
                                         "source_url": "", "superseded_by": None, "score": 0.6}])

    with patch.object(research, "generate_candidates", new=AsyncMock(return_value=list(auth))), \
        patch.object(research, "rerank_candidates", new=AsyncMock(side_effect=lambda q, c, **k: c)), \
        patch.object(research, "generate_historical_candidates", new=hist_mock), \
        patch.object(agent, "_firm_knowledge_search", new=AsyncMock(return_value=[])):
        chunks, _ = await agent._retrieve_context("q", "cid", embedding=[0.1] * 1536)

    # Flag off → no historical fetch, no historical chunks.
    hist_mock.assert_not_awaited()
    assert [c["id"] for c in chunks] == ["0", "1", "2"]
    assert all(not c.get("is_historical") for c in chunks)
