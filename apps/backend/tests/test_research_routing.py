"""Tests for pre-generation model routing and single-embedding reuse (Tasks A3/A4/A5)."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from taxflow.config import settings
from taxflow.services.agents.research import ResearchAgent, route_model


# --- Task A3: route_model picks the model from retrieval signals only ---------


def test_route_model_strong_retrieval_picks_haiku():
    signals = {
        "num_chunks": settings.ROUTE_MIN_STRONG_CHUNKS,
        "top_score": settings.ROUTE_MIN_TOP_RRF_SCORE + 0.01,
        "insufficient": False,
    }
    assert route_model(signals) == "haiku"


def test_route_model_insufficient_information_picks_sonnet():
    signals = {"num_chunks": 0, "top_score": 0.0, "insufficient": True}
    assert route_model(signals) == "sonnet"


def test_route_model_weak_top_score_picks_sonnet():
    signals = {
        "num_chunks": settings.ROUTE_MIN_STRONG_CHUNKS,
        "top_score": settings.ROUTE_MIN_TOP_RRF_SCORE - 0.001,
        "insufficient": False,
    }
    assert route_model(signals) == "sonnet"


def test_route_model_few_chunks_picks_sonnet():
    signals = {
        "num_chunks": settings.ROUTE_MIN_STRONG_CHUNKS - 1,
        "top_score": 1.0,
        "insufficient": False,
    }
    assert route_model(signals) == "sonnet"


def test_route_model_ambiguous_biases_to_sonnet():
    # Empty / missing signals must not silently route a hard question to Haiku.
    assert route_model({}) == "sonnet"


def test_route_model_rerank_score_can_promote_to_haiku():
    # A weak RRF top_score but a strong C1 re-rank score should still qualify.
    signals = {
        "num_chunks": settings.ROUTE_MIN_STRONG_CHUNKS,
        "top_score": 0.0,
        "rerank_top_score": settings.ROUTE_MIN_TOP_RRF_SCORE + 0.5,
        "insufficient": False,
    }
    assert route_model(signals) == "haiku"


# --- Task A3: run() generates exactly once with the routed model --------------


@pytest.mark.asyncio
async def test_run_generates_once_with_routed_model():
    agent = ResearchAgent()
    strong_chunks = [
        {"id": str(i), "citation": f"c{i}", "content": "x", "source_url": "", "score": 0.5}
        for i in range(6)
    ]

    with patch.object(
        agent, "_retrieve_context", new=AsyncMock(return_value=(strong_chunks, {
            "num_chunks": 6, "top_score": 0.5, "insufficient": False,
        }))
    ), patch.object(
        agent,
        "_generate",
        new=AsyncMock(return_value=("Answer [1]", {
            "input_tokens": 10,
            "output_tokens": 5,
            "cache_read_input_tokens": 3,
            "cache_creation_input_tokens": 0,
        })),
    ) as mock_gen:
        result = await agent.run(question="q", client_id="cid")

    mock_gen.assert_awaited_once()  # exactly one generation call per query
    assert mock_gen.await_args.args[2] == settings.ANTHROPIC_HAIKU_MODEL
    assert result["model_used"] == "haiku"
    assert result["cache_read_input_tokens"] == 3


@pytest.mark.asyncio
async def test_run_routes_hard_question_to_sonnet_single_call():
    agent = ResearchAgent()

    with patch.object(
        agent, "_retrieve_context", new=AsyncMock(return_value=([], {
            "num_chunks": 0, "top_score": 0.0, "insufficient": True,
        }))
    ), patch.object(
        agent,
        "_generate",
        new=AsyncMock(return_value=("No sources", {
            "input_tokens": 1,
            "output_tokens": 1,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
        })),
    ) as mock_gen:
        result = await agent.run(question="q", client_id="cid")

    mock_gen.assert_awaited_once()
    assert mock_gen.await_args.args[2] == settings.ANTHROPIC_SONNET_MODEL
    assert result["model_used"] == "sonnet"


# --- Task A4: the passed-in embedding is reused, not re-computed ---------------


@pytest.mark.asyncio
async def test_retrieve_context_reuses_embedding_without_re_embedding():
    agent = ResearchAgent()
    vec = [0.1] * 1536

    with patch(
        "taxflow.services.agents.research.hybrid_search", new=AsyncMock(return_value=[])
    ) as mock_hybrid, patch.object(
        agent, "_firm_knowledge_search", new=AsyncMock(return_value=[])
    ) as mock_firm, patch(
        "taxflow.services.knowledge.embedder.embed", new=AsyncMock()
    ) as mock_embed:
        await agent._retrieve_context("q", "cid", embedding=vec)

    # The pre-computed vector must flow through to both retrieval paths and the
    # embedder must never be called again inside retrieval.
    assert mock_hybrid.await_args.kwargs["embedding"] == vec
    assert mock_firm.await_args.kwargs["embedding"] == vec
    mock_embed.assert_not_awaited()


# --- Task A5: firm-knowledge search sets probes inside an explicit transaction -


@pytest.mark.asyncio
async def test_firm_knowledge_search_wraps_probes_in_transaction():
    agent = ResearchAgent()
    vec = [0.2] * 1536

    fake_cur = MagicMock()
    fake_cur.fetchall.return_value = []
    fake_conn = MagicMock()
    fake_conn.cursor.return_value = fake_cur
    # `with conn:` -> __enter__/__exit__ define the explicit transaction scope.
    fake_conn.__enter__ = MagicMock(return_value=fake_conn)
    fake_conn.__exit__ = MagicMock(return_value=False)

    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=fake_conn)
    cm.__exit__ = MagicMock(return_value=False)

    with patch("taxflow.db.get_pg_conn", return_value=cm):
        await agent._firm_knowledge_search("q", "cid", top_k=2, embedding=vec)

    # The connection-level transaction context must be entered so SET LOCAL applies.
    fake_conn.__enter__.assert_called_once()
    first_sql = fake_cur.execute.call_args_list[0].args[0]
    assert "SET LOCAL ivfflat.probes" in first_sql
    assert fake_cur.execute.call_args_list[0].args[1] == (settings.IVFFLAT_PROBES,)
