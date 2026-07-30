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
    derive_jurisdiction_hint,
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


# --- jurisdiction SOFT boost (RAG-quality audit follow-up) ---------------------
# Root cause: a question naming "New South Wales" retrieved a Western
# Australia ruling instead, because nothing in retrieval carried jurisdiction
# at all - state revenue offices publish near-identically-titled rulings
# independently per state.


def test_derive_jurisdiction_hint_from_full_state_name():
    assert derive_jurisdiction_hint("payroll tax grouping in New South Wales") == "NSW"


def test_derive_jurisdiction_hint_from_uppercase_abbreviation():
    assert derive_jurisdiction_hint("What is the NSW payroll tax threshold?") == "NSW"


def test_derive_jurisdiction_hint_ignores_lowercase_abbreviation():
    """Bare lowercase state codes are common English words ("act", "sa", "nt")
    - only an exact-uppercase abbreviation match is trusted, never lowercase."""
    assert derive_jurisdiction_hint("what act governs this deduction?") is None


def test_derive_jurisdiction_hint_none_for_federal_question():
    assert derive_jurisdiction_hint("What is the small business CGT concession?") is None


def test_jurisdiction_boost_keeps_non_matching_docs_retrievable():
    """A SOFT boost must re-order, never drop - the wrong-jurisdiction doc stays
    retrievable (a federal ITAA provision must never be excluded just because a
    state was named elsewhere in the question)."""
    candidates = [
        {"id": "wa", "jurisdiction": "WA", "score": 0.501},
        {"id": "nsw", "jurisdiction": "NSW", "score": 0.500},
    ]
    boosted = retrieval.apply_jurisdiction_boost(candidates, "NSW")
    ids = {c["id"] for c in boosted}
    assert ids == {"wa", "nsw"}
    # The matching-jurisdiction doc is boosted above the near-tied non-matching one.
    assert boosted[0]["id"] == "nsw"


def test_jurisdiction_boost_noop_when_no_hint():
    candidates = [{"id": "a", "jurisdiction": "WA", "score": 0.10}]
    assert retrieval.apply_jurisdiction_boost(candidates, None) == candidates


def test_jurisdiction_boost_noop_for_federal_docs_with_no_jurisdiction():
    """A federal document (jurisdiction=None) is simply never boosted - it's
    not penalised either, since the boost only ever multiplies matching docs."""
    candidates = [
        {"id": "fed", "jurisdiction": None, "score": 0.45},
        {"id": "nsw", "jurisdiction": "NSW", "score": 0.40},
    ]
    boosted = retrieval.apply_jurisdiction_boost(candidates, "NSW")
    assert boosted[0]["id"] == "nsw"  # boosted above the higher-scoring federal doc


# --- per-source-url diversity cap (RAG-quality audit follow-up) ----------------
# Root cause: a single long ruling chunked with overlapping windows can place
# many near-duplicate chunks at the top of the pool, crowding out a different,
# more precisely on-point source from ever reaching the merged pool.


def test_cap_per_source_url_limits_dominant_document():
    candidates = (
        [{"id": f"dup-{i}", "source_url": "http://a", "score": 1.0 - i * 0.01} for i in range(6)]
        + [{"id": "other", "source_url": "http://b", "score": 0.5}]
    )
    capped = retrieval.cap_per_source_url(candidates, max_per_url=4)
    from_a = [c for c in capped if c["source_url"] == "http://a"]
    assert len(from_a) == 4
    # The best 4 (highest score, already in rank order) are kept, not an
    # arbitrary subset.
    assert [c["id"] for c in from_a] == ["dup-0", "dup-1", "dup-2", "dup-3"]
    # The different source is still present - the cap doesn't drop it.
    assert any(c["id"] == "other" for c in capped)


def test_cap_per_source_url_noop_when_disabled():
    candidates = [{"id": "a", "source_url": "http://a", "score": 1.0}]
    assert retrieval.cap_per_source_url(candidates, max_per_url=0) == candidates


# --- section-title soft boost (RAG-quality audit precision follow-up #2) ------
# Root cause: retrieval repeatedly landed in the right Division but the WRONG
# sibling Section (e.g. ITAA 1997 Subdivision 292-C "Excess non-concessional
# contributions tax" instead of 292-B's concessional cap, for a question about
# the CONCESSIONAL cap).


def test_leaf_title_extracts_last_parenthetical():
    heading = (
        "Chapter 3 > Part 3-30 (Superannuation) > Division 292 "
        "(Excess non-concessional contributions) > Section 292-105 (CGT cap amount)"
    )
    assert retrieval._leaf_title(heading) == "CGT cap amount"


def test_leaf_title_none_when_no_heading_path():
    assert retrieval._leaf_title(None) is None
    assert retrieval._leaf_title("") is None


def test_section_title_boost_favours_matching_sibling():
    question = "What is the SMSF concessional contributions cap?"
    candidates = [
        {
            "id": "292-C",
            "score": 0.50,
            "heading_path": "... > Subdivision 292-C (Excess non-concessional contributions tax)",
        },
        {
            "id": "292-B",
            "score": 0.48,
            "heading_path": "... > Subdivision 292-B (Concessional contributions cap)",
        },
    ]
    out = retrieval.apply_section_title_boost(candidates, question)
    # 292-B starts slightly behind on raw score but its title shares far more
    # content words with the question ("concessional", "contributions", "cap")
    # than 292-C's ("non-concessional", "contributions", "tax") - it must end
    # up ranked first.
    assert out[0]["id"] == "292-B"


def test_section_title_boost_noop_for_non_legislation_candidates():
    """A ruling with no heading_path is never boosted - never penalised
    either, since the boost only ever multiplies a matching candidate up."""
    candidates = [{"id": "a", "score": 0.5, "heading_path": None}]
    out = retrieval.apply_section_title_boost(candidates, "some question")
    assert out[0]["score"] == 0.5


def test_section_title_boost_noop_when_weight_disabled(monkeypatch):
    monkeypatch.setattr(settings, "SECTION_TITLE_BOOST_WEIGHT", 0)
    candidates = [{"id": "a", "score": 0.5, "heading_path": "... > Section 1 (Concessional cap)"}]
    assert retrieval.apply_section_title_boost(candidates, "concessional cap") == candidates


@pytest.mark.asyncio
async def test_retrieve_context_soft_mode_does_not_pass_sql_filter():
    """In soft mode (default), the SQL layer receives source_types=None (unfiltered)."""
    agent = ResearchAgent()
    captured = {}

    async def fake_generate_candidates(question, source_types=None, embedding=None, pool_scale=1):
        captured["source_types"] = source_types
        return [{"id": "x", "source_type": "ato_news", "score": 0.5}]

    with patch.object(settings, "SOURCE_TYPE_FILTER_MODE", "soft"), patch(
        "taxflow.services.agents.research.generate_candidates", new=fake_generate_candidates
    ), patch(
        "taxflow.services.agents.research.rerank_candidates",
        new=AsyncMock(side_effect=lambda q, c, pool_scale=1: c),
    ), patch(
        "taxflow.services.agents.research.generate_historical_candidates",
        new=AsyncMock(return_value=[]),
    ), patch.object(agent, "_firm_knowledge_search", new=AsyncMock(return_value=[])):
        await agent._retrieve_context("q", "cid", source_type_hint=["legislation"])

    # Soft mode: never a hard SQL exclusion.
    assert captured["source_types"] is None


@pytest.mark.asyncio
async def test_retrieve_context_hard_mode_passes_sql_filter():
    agent = ResearchAgent()
    captured = {}

    async def fake_generate_candidates(question, source_types=None, embedding=None, pool_scale=1):
        captured["source_types"] = source_types
        return []

    with patch.object(settings, "SOURCE_TYPE_FILTER_MODE", "hard"), patch(
        "taxflow.services.agents.research.generate_candidates", new=fake_generate_candidates
    ), patch(
        "taxflow.services.agents.research.rerank_candidates",
        new=AsyncMock(side_effect=lambda q, c, pool_scale=1: c),
    ), patch(
        "taxflow.services.agents.research.generate_historical_candidates",
        new=AsyncMock(return_value=[]),
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
    """The repo query must pin BOTH client_id and session_id (never cross-scope)."""
    agent = ResearchAgent()

    repos = MagicMock()
    # Repo returns newest-first rows; the agent reverses to oldest-first.
    repos.queries.list_session_history.return_value = [
        {"question": "q2", "final_answer": "a2"},
        {"question": "q1", "final_answer": "a1"},
    ]

    with patch("taxflow.providers.get_relational_data", return_value=repos):
        history = await agent._load_session_history("client-1", "sess-1")

    # Scoping is enforced by passing BOTH client_id and session_id to the repo,
    # whose SQL carries the WHERE client_id = %s AND session_id = %s predicate.
    call = repos.queries.list_session_history.call_args
    assert call.args[0] == "client-1"
    assert call.args[1] == "sess-1"
    # Rows are returned oldest-first (repo returns DESC, agent reverses).
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

    fake_store = MagicMock()
    fake_store.firm_search = AsyncMock(side_effect=psycopg2.OperationalError("connection refused"))

    with patch("taxflow.providers.get_vector_store", return_value=fake_store):
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

    fake_store = MagicMock()
    fake_store.firm_search = AsyncMock(return_value=[])

    with patch("taxflow.providers.get_vector_store", return_value=fake_store), patch(
        "taxflow.services.knowledge.embedder.embed", new=AsyncMock()
    ) as mock_embed:
        await agent._firm_knowledge_search("q", "cid", top_k=2, embedding=vec)

    # The single embedding passed down (Task A4) is reused: no re-embed here.
    mock_embed.assert_not_awaited()
    # And the reused vector is what the vector query binds.
    assert fake_store.firm_search.await_args.kwargs["embedding"] == vec
