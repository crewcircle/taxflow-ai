"""Tests for RERANK_MODE re-ranking (Task C1) and firm+global merge (Task C4)."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from taxflow.config import settings
from taxflow.services.agents.research import ResearchAgent
from taxflow.services.knowledge import retrieval


def _cands(n):
    return [
        {"id": str(i), "citation": f"c{i}", "content": f"body {i}", "source_url": "", "score": 1.0 / (i + 1)}
        for i in range(n)
    ]


# --- Task C1: off / rrf_only must NEVER call the LLM --------------------------


@pytest.mark.asyncio
async def test_rerank_off_never_calls_llm(monkeypatch):
    monkeypatch.setattr(settings, "RERANK_MODE", "off")
    with patch.object(retrieval, "_llm_rerank", new=AsyncMock()) as mock_llm:
        out = await retrieval.rerank_candidates("q", _cands(5))
    mock_llm.assert_not_awaited()
    assert len(out) == 5


@pytest.mark.asyncio
async def test_rerank_rrf_only_never_calls_llm(monkeypatch):
    monkeypatch.setattr(settings, "RERANK_MODE", "rrf_only")
    with patch.object(retrieval, "_llm_rerank", new=AsyncMock()) as mock_llm:
        out = await retrieval.rerank_candidates("q", _cands(5))
    mock_llm.assert_not_awaited()
    # rrf_only preserves the RRF order unchanged.
    assert [c["id"] for c in out] == ["0", "1", "2", "3", "4"]


@pytest.mark.asyncio
async def test_rerank_llm_mode_calls_llm_once(monkeypatch):
    monkeypatch.setattr(settings, "RERANK_MODE", "llm")
    with patch.object(retrieval, "_llm_rerank", new=AsyncMock(return_value=_cands(3))) as mock_llm:
        await retrieval.rerank_candidates("q", _cands(3))
    mock_llm.assert_awaited_once()


@pytest.mark.asyncio
async def test_llm_rerank_single_batched_call_and_reorders(monkeypatch):
    monkeypatch.setattr(settings, "RERANK_DEPTH", 3)
    cands = _cands(3)

    fake_response = MagicMock()
    block = MagicMock()
    block.type = "text"
    block.text = '{"0": 0.1, "1": 0.9, "2": 0.5}'
    fake_response.content = [block]

    fake_client = MagicMock()
    fake_client.messages.create = AsyncMock(return_value=fake_response)

    with patch("anthropic.AsyncAnthropic", return_value=fake_client):
        out = await retrieval._llm_rerank("q", cands)

    # Exactly ONE Anthropic call over the whole batch (not one per candidate).
    fake_client.messages.create.assert_awaited_once()
    # Re-ordered by the returned relevance score, descending.
    assert [c["id"] for c in out[:3]] == ["1", "2", "0"]


@pytest.mark.asyncio
async def test_llm_rerank_falls_back_to_input_order_on_error():
    cands = _cands(3)
    fake_client = MagicMock()
    fake_client.messages.create = AsyncMock(side_effect=RuntimeError("boom"))
    with patch("anthropic.AsyncAnthropic", return_value=fake_client):
        out = await retrieval._llm_rerank("q", cands)
    assert out == cands


def test_normalise_query_section_and_synonym(monkeypatch):
    monkeypatch.setattr(settings, "QUERY_NORMALISE_ENABLED", True)
    assert "section 8-1" in retrieval.normalise_query("what about s8-1?")
    assert "capital gains tax" in retrieval.normalise_query("CGT discount")


def test_normalise_query_disabled_is_identity(monkeypatch):
    monkeypatch.setattr(settings, "QUERY_NORMALISE_ENABLED", False)
    assert retrieval.normalise_query("s8-1 CGT") == "s8-1 CGT"


# --- Task C4: firm + global merged into ONE ranked pool -----------------------


@pytest.mark.asyncio
async def test_retrieve_context_merges_firm_and_global_by_score(monkeypatch):
    monkeypatch.setattr(settings, "RERANK_MODE", "rrf_only")
    monkeypatch.setattr(settings, "RETRIEVAL_GLOBAL_POOL", 8)
    monkeypatch.setattr(settings, "RETRIEVAL_TOP_K", 10)
    agent = ResearchAgent()

    global_cands = [
        {"id": "g1", "citation": "G1", "content": "x", "source_url": "", "score": 0.10},
        {"id": "g2", "citation": "G2", "content": "x", "source_url": "", "score": 0.02},
    ]
    # Firm chunk with a high weighted score must rank ABOVE the weak global chunk,
    # not be blindly appended after global truncation.
    firm_cands = [
        {"id": "f1", "citation": "Firm knowledge: notes", "content": "x", "source_url": "", "score": 0.08},
    ]

    with patch(
        "taxflow.services.agents.research.generate_candidates",
        new=AsyncMock(return_value=global_cands),
    ), patch.object(agent, "_firm_knowledge_search", new=AsyncMock(return_value=firm_cands)):
        chunks, signals = await agent._retrieve_context("q", "cid", embedding=[0.1] * 1536)

    ids = [c["id"] for c in chunks]
    # firm chunk ranked by merged score, sits between the two global chunks.
    assert ids == ["g1", "f1", "g2"]
    # routing signals derive from the GLOBAL pool only.
    assert signals["num_chunks"] == 2
    assert signals["top_score"] == 0.10


@pytest.mark.asyncio
async def test_firm_knowledge_search_uses_configurable_weight(monkeypatch):
    monkeypatch.setattr(settings, "FIRM_CHUNK_WEIGHT", 2.0)
    agent = ResearchAgent()

    fake_cur = MagicMock()
    fake_cur.fetchall.return_value = [{"id": 1, "file_name": "n", "content": "c", "sim": 0.5}]
    fake_conn = MagicMock()
    fake_conn.cursor.return_value = fake_cur
    fake_conn.__enter__ = MagicMock(return_value=fake_conn)
    fake_conn.__exit__ = MagicMock(return_value=False)
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=fake_conn)
    cm.__exit__ = MagicMock(return_value=False)

    with patch("taxflow.db.get_pg_conn", return_value=cm):
        rows = await agent._firm_knowledge_search("q", "cid", top_k=2, embedding=[0.2] * 1536)

    assert rows[0]["score"] == pytest.approx(0.5 * 2.0)
