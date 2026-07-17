"""Tests for Wave D personalisation (Tasks D1-D4).

All mocked — no real OpenAI/Anthropic/DB calls:
  D1 profile string built from business_type/state appears in the prompt.
  D2 source_types is a SOFT boost, not a hard filter (non-matching doc stays).
  D3 session memory loads only same (client_id, session_id) rows; single-shot
     (no session_id) is unchanged; never cross-session/cross-client.
  D4 firm-knowledge error is logged, not swallowed silently, and still returns [].
"""
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from taxflow.config import settings
from taxflow.services.agents.research import (
    ResearchAgent,
    build_client_profile,
    build_session_block,
    derive_source_type_hint,
)
from taxflow.services.knowledge import retrieval


# --- Task D1: profile string ---------------------------------------------------


def test_profile_string_includes_business_type_and_state():
    client = {"business_type": "dental", "state": "NSW"}
    profile = build_client_profile(client)
    assert "dental" in profile
    assert "NSW" in profile
    assert "advisory" in profile.lower()  # kept advisory, not a hard filter


def test_profile_string_includes_firm_style_highlights():
    client = {"business_type": "legal", "state": "VIC", "firm_style": {"tone": "formal"}}
    profile = build_client_profile(client)
    assert "tone: formal" in profile


def test_profile_string_empty_when_disabled():
    client = {"business_type": "dental", "state": "NSW"}
    with patch.object(settings, "PROFILE_INJECTION_ENABLED", False):
        assert build_client_profile(client) == ""


def test_profile_string_empty_for_no_client():
    assert build_client_profile(None) == ""
    assert build_client_profile({}) == ""


@pytest.mark.asyncio
async def test_profile_appears_in_generation_prompt():
    """The advisory profile must reach the actual user message sent to the model."""
    agent = ResearchAgent()
    client = {"business_type": "dental", "state": "QLD"}

    captured = {}

    async def fake_generate(question, context, model, steering=""):
        captured["steering"] = steering
        return "Answer [1]", {
            "input_tokens": 1, "output_tokens": 1,
            "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0,
        }

    strong_chunks = [
        {"id": str(i), "citation": f"c{i}", "content": "x", "source_url": "", "score": 0.5}
        for i in range(6)
    ]
    with patch.object(
        agent, "_retrieve_context",
        new=AsyncMock(return_value=(strong_chunks, {"num_chunks": 6, "top_score": 0.5, "insufficient": False})),
    ), patch.object(agent, "_generate", new=fake_generate):
        await agent.run(question="q", client_id="cid", client=client)

    assert "dental" in captured["steering"]
    assert "QLD" in captured["steering"]
    # And _user_content actually embeds the steering ahead of the question.
    content = agent._user_content("q", "ctx", captured["steering"])
    assert "dental" in content
    assert content.index("dental") < content.index("Question:")


# --- Task D2: source_types SOFT boost, not a hard filter -----------------------


def test_derive_source_type_hint_from_intent():
    hint = derive_source_type_hint("What does section 8-1 of the ITAA say?", None)
    assert hint is not None
    assert "legislation" in hint


def test_derive_source_type_hint_from_active_modules():
    hint = derive_source_type_hint("generic question", ["ato_correspondence"])
    assert hint is not None
    assert "ato_ruling" in hint


def test_derive_source_type_hint_none_when_no_match():
    assert derive_source_type_hint("generic question", None) is None


def test_source_type_boost_keeps_non_matching_docs_retrievable():
    """A SOFT boost must re-order, never drop: the non-matching doc is still present."""
    candidates = [
        {"id": "a", "source_type": "ato_news", "score": 0.10},
        {"id": "b", "source_type": "legislation", "score": 0.09},
    ]
    boosted = retrieval.apply_source_type_boost(candidates, ["legislation"])
    ids = {c["id"] for c in boosted}
    # Non-matching "ato_news" doc must NOT be excluded (unlike a hard filter).
    assert ids == {"a", "b"}
    # The matching legislation doc gets boosted above the non-matching one.
    assert boosted[0]["id"] == "b"


def test_source_type_boost_noop_when_no_hint():
    candidates = [{"id": "a", "source_type": "ato_news", "score": 0.10}]
    assert retrieval.apply_source_type_boost(candidates, None) == candidates


@pytest.mark.asyncio
async def test_retrieve_context_soft_mode_does_not_pass_sql_filter():
    """In soft mode (default), the SQL layer receives source_types=None (unfiltered)."""
    agent = ResearchAgent()
    captured = {}

    async def fake_generate_candidates(question, source_types=None, embedding=None):
        captured["source_types"] = source_types
        return [{"id": "x", "source_type": "ato_news", "score": 0.5}]

    with patch.object(settings, "SOURCE_TYPE_FILTER_MODE", "soft"), patch(
        "taxflow.services.agents.research.generate_candidates", new=fake_generate_candidates
    ), patch(
        "taxflow.services.agents.research.rerank_candidates",
        new=AsyncMock(side_effect=lambda q, c: c),
    ), patch.object(agent, "_firm_knowledge_search", new=AsyncMock(return_value=[])):
        await agent._retrieve_context("q", "cid", source_type_hint=["legislation"])

    # Soft mode: never a hard SQL exclusion.
    assert captured["source_types"] is None


@pytest.mark.asyncio
async def test_retrieve_context_hard_mode_passes_sql_filter():
    agent = ResearchAgent()
    captured = {}

    async def fake_generate_candidates(question, source_types=None, embedding=None):
        captured["source_types"] = source_types
        return []

    with patch.object(settings, "SOURCE_TYPE_FILTER_MODE", "hard"), patch(
        "taxflow.services.agents.research.generate_candidates", new=fake_generate_candidates
    ), patch(
        "taxflow.services.agents.research.rerank_candidates",
        new=AsyncMock(side_effect=lambda q, c: c),
    ), patch.object(agent, "_firm_knowledge_search", new=AsyncMock(return_value=[])):
        await agent._retrieve_context("q", "cid", source_type_hint=["legislation"])

    # Opt-in hard mode forwards the hint as a SQL filter.
    assert captured["source_types"] == ["legislation"]


# --- Task D3: session memory ---------------------------------------------------


def test_build_session_block_truncates_answers():
    long_answer = "x" * 1000
    block = build_session_block([{"question": "q1", "answer": long_answer}])
    assert "conversation so far" in block.lower()
    assert "q1" in block
    # Answer truncated to the configured summary length (+ ellipsis).
    assert len(block) < 1000
    assert "…" in block


def test_build_session_block_empty_for_no_history():
    assert build_session_block([]) == ""


@pytest.mark.asyncio
async def test_load_session_history_scopes_to_client_and_session():
    """The SQL WHERE must pin BOTH client_id and session_id (never cross-scope)."""
    agent = ResearchAgent()

    fake_cur = MagicMock()
    fake_cur.fetchall.return_value = [
        {"question": "q2", "final_answer": "a2"},
        {"question": "q1", "final_answer": "a1"},
    ]
    fake_conn = MagicMock()
    fake_conn.cursor.return_value = fake_cur
    fake_conn.__enter__ = MagicMock(return_value=fake_conn)
    fake_conn.__exit__ = MagicMock(return_value=False)
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=fake_conn)
    cm.__exit__ = MagicMock(return_value=False)

    with patch("taxflow.db.get_pg_conn", return_value=cm):
        history = await agent._load_session_history("client-1", "sess-1")

    sql = fake_cur.execute.call_args_list[0].args[0]
    params = fake_cur.execute.call_args_list[0].args[1]
    assert "client_id = %s" in sql
    assert "session_id = %s" in sql
    assert params[0] == "client-1"
    assert params[1] == "sess-1"
    # Rows are returned oldest-first (SQL DESC then reversed).
    assert [h["question"] for h in history] == ["q1", "q2"]


@pytest.mark.asyncio
async def test_run_without_session_id_loads_no_history():
    """Single-shot query (no session_id) must NOT touch session history."""
    agent = ResearchAgent()
    strong_chunks = [
        {"id": str(i), "citation": f"c{i}", "content": "x", "source_url": "", "score": 0.5}
        for i in range(6)
    ]
    with patch.object(
        agent, "_retrieve_context",
        new=AsyncMock(return_value=(strong_chunks, {"num_chunks": 6, "top_score": 0.5, "insufficient": False})),
    ), patch.object(
        agent, "_generate",
        new=AsyncMock(return_value=("Answer [1]", {
            "input_tokens": 1, "output_tokens": 1,
            "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0,
        })),
    ), patch.object(agent, "_load_session_history", new=AsyncMock()) as mock_hist:
        await agent.run(question="q", client_id="cid")

    mock_hist.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_with_session_id_loads_history_and_injects_it():
    agent = ResearchAgent()
    captured = {}

    async def fake_generate(question, context, model, steering=""):
        captured["steering"] = steering
        return "Answer [1]", {
            "input_tokens": 1, "output_tokens": 1,
            "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0,
        }

    strong_chunks = [
        {"id": str(i), "citation": f"c{i}", "content": "x", "source_url": "", "score": 0.5}
        for i in range(6)
    ]
    with patch.object(
        agent, "_retrieve_context",
        new=AsyncMock(return_value=(strong_chunks, {"num_chunks": 6, "top_score": 0.5, "insufficient": False})),
    ), patch.object(agent, "_generate", new=fake_generate), patch.object(
        agent, "_load_session_history",
        new=AsyncMock(return_value=[{"question": "prior q", "answer": "prior a"}]),
    ) as mock_hist:
        await agent.run(question="q", client_id="cid", session_id="sess-1")

    mock_hist.assert_awaited_once_with("cid", "sess-1")
    assert "prior q" in captured["steering"]
    assert "conversation so far" in captured["steering"].lower()


# --- Task D4: firm-knowledge errors are logged, not swallowed silently ----------


@pytest.mark.asyncio
async def test_firm_knowledge_error_is_logged_and_returns_empty(caplog):
    import psycopg2

    agent = ResearchAgent()

    def _boom(*_a, **_k):
        raise psycopg2.OperationalError("connection refused")

    with patch("taxflow.db.get_pg_conn", side_effect=_boom):
        with caplog.at_level(logging.WARNING, logger="taxflow.services.agents.research"):
            result = await agent._firm_knowledge_search(
                "q", "cid", top_k=2, embedding=[0.1] * 1536
            )

    # Still non-fatal: returns [] so the query proceeds on global sources.
    assert result == []
    # But the failure is now observable (not the old silent `except Exception`).
    assert any("firm knowledge search failed" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_firm_knowledge_reuses_passed_embedding_no_reembed():
    agent = ResearchAgent()
    vec = [0.2] * 1536

    fake_cur = MagicMock()
    fake_cur.fetchall.return_value = []
    fake_conn = MagicMock()
    fake_conn.cursor.return_value = fake_cur
    fake_conn.__enter__ = MagicMock(return_value=fake_conn)
    fake_conn.__exit__ = MagicMock(return_value=False)
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=fake_conn)
    cm.__exit__ = MagicMock(return_value=False)

    with patch("taxflow.db.get_pg_conn", return_value=cm), patch(
        "taxflow.services.knowledge.embedder.embed", new=AsyncMock()
    ) as mock_embed:
        await agent._firm_knowledge_search("q", "cid", top_k=2, embedding=vec)

    # The single embedding passed down (Task A4) is reused: no re-embed here.
    mock_embed.assert_not_awaited()
    # And the reused vector is what the vector query binds.
    probe_params = fake_cur.execute.call_args_list[1].args[1]
    assert probe_params[0] == vec
