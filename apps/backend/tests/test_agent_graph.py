"""Tests for the LangGraph research agent-loop (Task A5).

These exercise the compiled graph end-to-end with FAKE ports (a fake LLMPort and
mocked retrieval / verify) so we assert control flow and the streaming contract
without any network calls:

  - strong retrieval → build_steering→retrieve→route_model→generate, verify SKIPPED;
  - a risky answer → gated verify FIRES;
  - a needs_correction verdict → corrective pass runs EXACTLY ONCE and is NOT
    re-verified (verify node call count == 1);
  - re_retrieve fires at most once when enabled and adds no second generate;
  - streaming vs non-streaming writer contract: ainvoke never streams tokens;
    astream(stream_mode="custom") emits custom token events.
"""
from __future__ import annotations

from typing import AsyncIterator
from unittest.mock import AsyncMock

import pytest

from taxflow.config import settings
from taxflow.ports.llm import LLMResult, StreamChunk, Usage
from taxflow.services.agents import graph as graph_mod


# --- fake LLMPort ------------------------------------------------------------


class FakeLLM:
    """Minimal LLMPort double.

    ``generate`` returns a fixed answer and tracks await count. ``stream`` yields
    the answer split into per-token chunks followed by a terminal usage chunk,
    and tracks whether it was consumed. This lets us assert the non-streaming
    path never touches the stream (and thus never the writer) and the streaming
    path emits token events.
    """

    def __init__(self, answer: str = "Answer [1][2][3][4]") -> None:
        self.answer = answer
        self.generate_calls = 0
        self.stream_calls = 0

    async def generate(self, **kwargs) -> LLMResult:
        self.generate_calls += 1
        return LLMResult(text=self.answer, usage=Usage(input_tokens=10, output_tokens=5))

    def stream(self, **kwargs) -> AsyncIterator[StreamChunk]:
        self.stream_calls += 1
        answer = self.answer

        async def _gen() -> AsyncIterator[StreamChunk]:
            for tok in answer.split(" "):
                yield StreamChunk(text=tok + " ")
            yield StreamChunk(usage=Usage(input_tokens=10, output_tokens=5), done=True)

        return _gen()


def _chunks(n: int) -> list[dict]:
    return [
        {"id": str(i), "citation": f"c{i}", "content": "x", "source_url": "", "score": 0.5}
        for i in range(1, n + 1)
    ]


STRONG_SIGNALS = {"num_chunks": 6, "top_score": 0.5, "insufficient": False}
WEAK_SIGNALS = {"num_chunks": 0, "top_score": 0.0, "insufficient": True}


@pytest.fixture
def base_state() -> dict:
    return {
        "question": "q",
        "client": None,
        "client_id": "cid",
        "session_id": None,
        "embedding": None,
        "corrective_count": 0,
        "re_retrieved": False,
        "streaming": False,
    }


@pytest.fixture(autouse=True)
def fake_llm(monkeypatch) -> FakeLLM:
    """Inject a fake LLM into the graph's ResearchAgent singleton and stub steering."""
    llm = FakeLLM()
    monkeypatch.setattr(graph_mod.research_agent, "_llm", llm)
    monkeypatch.setattr(
        graph_mod.research_agent,
        "_build_steering",
        AsyncMock(return_value=("", None, 0)),
    )
    return llm


# --- happy path: verify skipped on strong retrieval --------------------------


@pytest.mark.asyncio
async def test_strong_retrieval_skips_verify(monkeypatch, base_state, fake_llm):
    monkeypatch.setattr(
        graph_mod.research_agent,
        "_retrieve_context",
        AsyncMock(return_value=(_chunks(6), dict(STRONG_SIGNALS))),
    )
    verify_run = AsyncMock()
    monkeypatch.setattr(graph_mod.verifier, "run", verify_run)

    out = await graph_mod.research_graph.ainvoke(base_state)

    # Path build_steering→retrieve→route_model→generate, verify never runs.
    verify_run.assert_not_awaited()
    assert fake_llm.generate_calls == 1
    assert out["routed_tier"] == "haiku"  # strong retrieval routes to Haiku
    assert out["answer"] == "Answer [1][2][3][4]"
    assert out["citations"]  # citations parsed
    assert out.get("verification") is None


# --- gated verify fires on a risky answer ------------------------------------


@pytest.mark.asyncio
async def test_risky_answer_fires_verify(monkeypatch, base_state, fake_llm):
    # No-citation answer → should_verify fires.
    fake_llm.answer = "An answer with no citations"
    monkeypatch.setattr(
        graph_mod.research_agent,
        "_retrieve_context",
        AsyncMock(return_value=(_chunks(6), dict(STRONG_SIGNALS))),
    )
    verify_run = AsyncMock(return_value={"overall_status": "verified", "issues": []})
    monkeypatch.setattr(graph_mod.verifier, "run", verify_run)

    out = await graph_mod.research_graph.ainvoke(base_state)

    verify_run.assert_awaited_once()
    # Clean verdict → no corrective pass.
    assert out["corrective_count"] == 0
    assert out["verification"]["overall_status"] == "verified"


# --- corrective pass: exactly once, NOT re-verified --------------------------


@pytest.mark.asyncio
async def test_corrective_pass_runs_once_and_is_not_reverified(
    monkeypatch, base_state, fake_llm
):
    monkeypatch.setattr(settings, "CORRECTIVE_PASS_ENABLED", True)
    fake_llm.answer = "Risky answer with no citations"
    monkeypatch.setattr(
        graph_mod.research_agent,
        "_retrieve_context",
        AsyncMock(return_value=(_chunks(6), dict(STRONG_SIGNALS))),
    )
    verify_run = AsyncMock(
        return_value={
            "overall_status": "needs_correction",
            "issues": [{"claim": "c", "issue": "i"}],
        }
    )
    monkeypatch.setattr(graph_mod.verifier, "run", verify_run)
    regen = AsyncMock(
        return_value={
            "answer": "Corrected [1]",
            "citations": [{"citation": "x"}],
            "confidence": 0.8,
            "model_used": "sonnet",
            "re_retrieved": True,
            "re_retrieval": {"fired": True, "reason": "reviewer_flag"},
            "trace": {
                "retrieval": {"chunks_considered": 8, "candidates": []},
                "generation": {"model": "sonnet", "confidence": 0.8},
            },
        }
    )
    monkeypatch.setattr(graph_mod.research_agent, "regenerate_with_feedback", regen)

    out = await graph_mod.research_graph.ainvoke(base_state)

    # Corrective pass runs EXACTLY once, and verify runs exactly once (no
    # re-verification of the corrected answer — no edge back to verify).
    regen.assert_awaited_once()
    # The corrective pass must request the reviewer-driven widen (Task C3).
    assert regen.await_args.kwargs["widen"] is True
    assert verify_run.await_count == 1
    assert out["corrective_count"] == 1
    assert out["answer"] == "Corrected [1]"
    assert out["caveat"] is not None
    assert out["corrected_meta"]["model_used"] == "sonnet"
    # The corrected answer's trace REPLACES the top-level trace (stored answer is
    # the corrected one), and the reviewer widen is threaded into state.
    assert out["trace"]["generation"] == {"model": "sonnet", "confidence": 0.8}
    assert out["re_retrieved"] is True
    assert out["re_reason"] == "reviewer_flag"


# --- re_retrieve: at most once, no second generate ---------------------------


@pytest.mark.asyncio
async def test_re_retrieve_fires_at_most_once(monkeypatch, base_state, fake_llm):
    monkeypatch.setattr(settings, "RE_RETRIEVE_ENABLED", True)
    # Strong answer text so verify is skipped and we isolate the retrieve loop.
    fake_llm.answer = "Answer [1][2][3][4]"
    retrieve_mock = AsyncMock(return_value=(_chunks(4), dict(WEAK_SIGNALS)))
    monkeypatch.setattr(graph_mod.research_agent, "_retrieve_context", retrieve_mock)
    verify_run = AsyncMock(return_value={"overall_status": "verified", "issues": []})
    monkeypatch.setattr(graph_mod.verifier, "run", verify_run)

    out = await graph_mod.research_graph.ainvoke(base_state)

    # retrieve node (1) + re_retrieve node (1) = 2 retrieval calls, never more.
    assert retrieve_mock.await_count == 2
    assert out["re_retrieved"] is True
    # Exactly one generation despite the extra retrieval.
    assert fake_llm.generate_calls == 1


@pytest.mark.asyncio
async def test_re_retrieve_skipped_when_disabled(monkeypatch, base_state, fake_llm):
    monkeypatch.setattr(settings, "RE_RETRIEVE_ENABLED", False)
    retrieve_mock = AsyncMock(return_value=(_chunks(4), dict(WEAK_SIGNALS)))
    monkeypatch.setattr(graph_mod.research_agent, "_retrieve_context", retrieve_mock)
    monkeypatch.setattr(
        graph_mod.verifier,
        "run",
        AsyncMock(return_value={"overall_status": "verified", "issues": []}),
    )

    out = await graph_mod.research_graph.ainvoke(base_state)

    # No re-retrieval when the flag is off.
    assert retrieve_mock.await_count == 1
    assert out.get("re_retrieved") is False


# --- streaming vs non-streaming writer contract ------------------------------


@pytest.mark.asyncio
async def test_ainvoke_non_streaming_never_streams(monkeypatch, base_state, fake_llm):
    monkeypatch.setattr(
        graph_mod.research_agent,
        "_retrieve_context",
        AsyncMock(return_value=(_chunks(6), dict(STRONG_SIGNALS))),
    )
    monkeypatch.setattr(graph_mod.verifier, "run", AsyncMock())

    base_state["streaming"] = False
    await graph_mod.research_graph.ainvoke(base_state)

    # Non-streaming mode uses generate and NEVER touches the stream (thus never
    # the writer).
    assert fake_llm.generate_calls == 1
    assert fake_llm.stream_calls == 0


@pytest.mark.asyncio
async def test_astream_emits_custom_token_events(monkeypatch, base_state, fake_llm):
    monkeypatch.setattr(
        graph_mod.research_agent,
        "_retrieve_context",
        AsyncMock(return_value=(_chunks(6), dict(STRONG_SIGNALS))),
    )
    monkeypatch.setattr(graph_mod.verifier, "run", AsyncMock())

    base_state["streaming"] = True
    events = []
    async for event in graph_mod.research_graph.astream(base_state, stream_mode="custom"):
        events.append(event)

    # Streaming mode emits custom token events via the LangGraph stream writer,
    # and does not call the buffered generate path.
    assert fake_llm.stream_calls == 1
    assert fake_llm.generate_calls == 0
    tokens = [e["token"] for e in events if "token" in e]
    assert tokens  # astream MUST emit at least one custom token event
    assert "".join(tokens).strip() == "Answer [1][2][3][4]"


# --- A1: generate node builds the extended canonical trace -------------------


@pytest.mark.asyncio
async def test_generate_trace_extended_candidate_keys_null_safe(
    monkeypatch, base_state, fake_llm
):
    """The generate node's trace carries the extended candidate keys with
    null-safe defaults when chunks lack the B-owned lifecycle fields, and
    firm/session are absent when state omits them."""
    monkeypatch.setattr(
        graph_mod.research_agent,
        "_retrieve_context",
        AsyncMock(return_value=(_chunks(3), dict(STRONG_SIGNALS))),
    )
    monkeypatch.setattr(graph_mod.verifier, "run", AsyncMock())

    out = await graph_mod.research_graph.ainvoke(base_state)
    trace = out["trace"]

    # Every candidate carries the new lifecycle keys defaulted null-safe.
    assert trace["retrieval"]["candidates"], "expected candidates"
    for cand in trace["retrieval"]["candidates"]:
        assert cand["is_superseded"] is False
        assert cand["superseded_by"] is None
        assert cand["is_historical"] is False
        # Existing keys unchanged.
        assert "n" in cand and "citation" in cand and "cited_in_answer" in cand

    # retrieval-level A-owned defaults.
    assert trace["retrieval"]["knowledge_as_of"] is None
    assert trace["retrieval"]["historical_pool_size"] == 0
    assert trace["retrieval"]["firm_knowledge_used"] is None

    # firm/session omitted from state → absent from the trace (never empty dicts).
    assert "firm" not in trace
    assert "session" not in trace


@pytest.mark.asyncio
async def test_generate_trace_emits_firm_session_when_present(
    monkeypatch, base_state, fake_llm
):
    """When state supplies non-empty firm/session fragments and a
    knowledge_as_of stamp, the generate node threads them onto the trace."""
    monkeypatch.setattr(
        graph_mod.research_agent,
        "_retrieve_context",
        AsyncMock(return_value=(_chunks(3), dict(STRONG_SIGNALS))),
    )
    monkeypatch.setattr(graph_mod.verifier, "run", AsyncMock())

    base_state["firm"] = {"firm_items_used": 2}
    base_state["session"] = {"prior_turns_used": 1}
    base_state["knowledge_as_of"] = "2026-01-15"

    out = await graph_mod.research_graph.ainvoke(base_state)
    trace = out["trace"]

    assert trace["firm"] == {"firm_items_used": 2}
    assert trace["session"] == {"prior_turns_used": 1}
    assert trace["retrieval"]["knowledge_as_of"] == "2026-01-15"


@pytest.mark.asyncio
async def test_generate_trace_counts_historical_pool(monkeypatch, base_state, fake_llm):
    """historical_pool_size counts chunks flagged is_historical; the tagged
    candidate carries its lifecycle metadata through."""
    chunks = _chunks(3)
    chunks[2]["is_historical"] = True
    chunks[2]["is_superseded"] = True
    chunks[2]["superseded_by"] = "TR 2024/1"
    monkeypatch.setattr(
        graph_mod.research_agent,
        "_retrieve_context",
        AsyncMock(return_value=(chunks, dict(STRONG_SIGNALS))),
    )
    monkeypatch.setattr(graph_mod.verifier, "run", AsyncMock())

    out = await graph_mod.research_graph.ainvoke(base_state)
    trace = out["trace"]

    assert trace["retrieval"]["historical_pool_size"] == 1
    hist = trace["retrieval"]["candidates"][2]
    assert hist["is_historical"] is True
    assert hist["is_superseded"] is True
    assert hist["superseded_by"] == "TR 2024/1"


# --- C6: C-owned trace signals (session / firm profile / usage_trend) ---------


@pytest.mark.asyncio
async def test_generate_trace_session_counts_and_client_ref(
    monkeypatch, base_state, fake_llm
):
    """C6: the generate node populates trace.session with the prior-turn count
    (from build_steering), the engagement-memo count (from the retrieved pool)
    and the request client_ref — the C-owned trace.session field names."""
    # Real _build_steering reporting 2 prior turns.
    monkeypatch.setattr(
        graph_mod.research_agent,
        "_build_steering",
        AsyncMock(return_value=("", None, 2)),
    )
    chunks = _chunks(2)
    chunks.append(
        {
            "id": "e1",
            "citation": "Engagement memo: prior advice",
            "content": "x",
            "source_url": "",
            "score": 0.4,
        }
    )
    monkeypatch.setattr(
        graph_mod.research_agent,
        "_retrieve_context",
        AsyncMock(return_value=(chunks, dict(STRONG_SIGNALS))),
    )
    monkeypatch.setattr(graph_mod.verifier, "run", AsyncMock())

    base_state["client_ref"] = "Client A"
    out = await graph_mod.research_graph.ainvoke(base_state)

    assert out["trace"]["session"] == {
        "prior_turns_used": 2,
        "engagement_memos_used": 1,
        "client_ref": "Client A",
    }


@pytest.mark.asyncio
async def test_generate_trace_firm_profile_and_usage_trend(
    monkeypatch, base_state, fake_llm
):
    """C6: with a client carrying a profile + firm_style, trace.firm gets the
    C-owned profile_applied/voice_applied/profile_summary + usage_trend, and the
    usage_trend comes from FirmKnowledgeRepo.usage_trend via _firm_usage_trend."""
    monkeypatch.setattr(
        graph_mod.research_agent,
        "_retrieve_context",
        AsyncMock(return_value=(_chunks(3), dict(STRONG_SIGNALS))),
    )
    monkeypatch.setattr(graph_mod.verifier, "run", AsyncMock())
    monkeypatch.setattr(
        graph_mod.research_agent,
        "_firm_usage_trend",
        AsyncMock(return_value={"quarter_count": 4, "prior_count": 1}),
    )

    base_state["client"] = {
        "business_type": "dental",
        "state": "QLD",
        "firm_style": {"tone": "formal"},
    }
    out = await graph_mod.research_graph.ainvoke(base_state)
    firm = out["trace"]["firm"]

    assert firm["profile_applied"] is True
    assert firm["voice_applied"] is True
    assert firm["profile_summary"]
    assert firm["usage_trend"] == {"quarter_count": 4, "prior_count": 1}


@pytest.mark.asyncio
async def test_generate_trace_firm_fragment_merge_keeps_both_sides(
    monkeypatch, base_state, fake_llm
):
    """C6 firm-fragment MERGE: when BOTH the B fragment (firm_items/
    firm_items_used) and the C fragment (profile_applied/usage_trend) are
    present, trace.firm carries ALL keys — neither side overwrites the other."""
    # A firm-knowledge chunk cited in the answer → B fragment is non-empty.
    chunks = _chunks(3)
    chunks.append(
        {
            "id": "f1",
            "citation": "Firm knowledge: internal note",
            "content": "x",
            "source_url": "",
            "score": 0.9,
        }
    )
    # The fake LLM cites [1]..[4]; chunk index 4 (the firm chunk) is cited.
    fake_llm.answer = "Answer [1][2][3][4]"
    monkeypatch.setattr(
        graph_mod.research_agent,
        "_retrieve_context",
        AsyncMock(return_value=(chunks, dict(STRONG_SIGNALS))),
    )
    monkeypatch.setattr(graph_mod.verifier, "run", AsyncMock())
    monkeypatch.setattr(
        graph_mod.research_agent,
        "_increment_firm_usage",
        AsyncMock(),
    )
    monkeypatch.setattr(
        graph_mod.research_agent,
        "_firm_usage_trend",
        AsyncMock(return_value={"quarter_count": 2, "prior_count": 0}),
    )

    base_state["client"] = {
        "business_type": "dental",
        "state": "QLD",
        "firm_style": {"tone": "formal"},
    }
    out = await graph_mod.research_graph.ainvoke(base_state)
    firm = out["trace"]["firm"]

    # C-owned keys present.
    assert firm["profile_applied"] is True
    assert firm["voice_applied"] is True
    assert firm["usage_trend"] == {"quarter_count": 2, "prior_count": 0}
    # B-owned keys present — the merge did not drop them.
    assert firm["firm_items_used"] == 1
    assert any(
        item["citation"] == "Firm knowledge: internal note"
        for item in firm["firm_items"]
    )


# --- C3: first-pass snapshot + corrected top-level trace (POST/SSE parity) ----


def _corrective_setup(monkeypatch, fake_llm):
    """Wire a needs_correction verdict so the corrective pass runs, returning a
    corrected answer whose trace describes a DIFFERENT (sonnet) generation than
    the first (haiku) pass. Shared by the POST and SSE parity tests."""
    monkeypatch.setattr(settings, "CORRECTIVE_PASS_ENABLED", True)
    # First-pass answer has no citations → risky → verify fires.
    fake_llm.answer = "Risky first-pass answer with no citations"
    monkeypatch.setattr(
        graph_mod.research_agent,
        "_retrieve_context",
        AsyncMock(return_value=(_chunks(6), dict(STRONG_SIGNALS))),
    )
    monkeypatch.setattr(
        graph_mod.verifier,
        "run",
        AsyncMock(
            return_value={
                "overall_status": "needs_correction",
                "issues": [{"claim": "c", "issue": "i"}],
            }
        ),
    )
    regen = AsyncMock(
        return_value={
            "answer": "Corrected answer [1]",
            "citations": [{"citation": "x"}],
            "confidence": 0.85,
            "model_used": "sonnet",
            "re_retrieved": True,
            "re_retrieval": {"fired": True, "reason": "reviewer_flag"},
            "trace": {
                "retrieval": {"chunks_considered": 12, "candidates": []},
                "generation": {"model": "sonnet", "confidence": 0.85},
            },
        }
    )
    monkeypatch.setattr(graph_mod.research_agent, "regenerate_with_feedback", regen)
    return regen


@pytest.mark.asyncio
async def test_post_first_pass_snapshot_before_correction(monkeypatch, base_state, fake_llm):
    """POST path (ainvoke): state['first_pass'] captures the ORIGINAL (haiku)
    generation meta BEFORE the corrective pass overwrites confidence/model, and
    the top-level trace.generation describes the CORRECTED (sonnet) answer."""
    _corrective_setup(monkeypatch, fake_llm)
    base_state["streaming"] = False

    out = await graph_mod.research_graph.ainvoke(base_state)

    # first_pass snapshot holds the ORIGINAL first-pass meta (haiku), even though
    # state confidence/model were overwritten by the corrective pass.
    assert out["first_pass"]["model"] == "haiku"
    first_conf = out["first_pass"]["confidence"]
    # The corrective pass overwrote the live confidence to the corrected value…
    assert out["confidence"] == 0.85
    # …but the snapshot preserved the distinct first-pass confidence.
    assert first_conf != 0.85

    # Top-level trace describes the CORRECTED answer (the stored answer).
    assert out["trace"]["generation"] == {"model": "sonnet", "confidence": 0.85}


@pytest.mark.asyncio
async def test_sse_first_pass_snapshot_matches_post(monkeypatch, base_state, fake_llm):
    """SSE path (astream): the final state carries the SAME first_pass snapshot
    and corrected top-level trace as the POST path (streaming parity)."""
    _corrective_setup(monkeypatch, fake_llm)
    base_state["streaming"] = True

    final = {}
    async for mode, chunk in graph_mod.research_graph.astream(
        base_state, stream_mode=["custom", "values"]
    ):
        if mode == "values":
            final = chunk

    # Same contract as POST: first_pass holds the original meta, top-level trace
    # describes the corrected answer.
    assert final["first_pass"]["model"] == "haiku"
    assert final["confidence"] == 0.85
    assert final["first_pass"]["confidence"] != 0.85
    assert final["trace"]["generation"] == {"model": "sonnet", "confidence": 0.85}
    # The reviewer widen fired and is threaded through state on the SSE path too.
    assert final["re_retrieved"] is True
    assert final["re_reason"] == "reviewer_flag"


# --- Phase 4: clarify routing + follow-up parsing ----------------------------


@pytest.mark.asyncio
async def test_clarify_disabled_routes_straight_to_generate(monkeypatch, base_state, fake_llm):
    """Default (CLARIFY_ENABLED=False): the clarify node is never entered and
    generation runs exactly once — behaviour identical to pre-Phase-4."""
    monkeypatch.setattr(settings, "CLARIFY_ENABLED", False)
    monkeypatch.setattr(
        graph_mod.research_agent,
        "_retrieve_context",
        AsyncMock(return_value=(_chunks(6), dict(STRONG_SIGNALS))),
    )
    monkeypatch.setattr(graph_mod.verifier, "run", AsyncMock())
    clarify_run = AsyncMock()
    monkeypatch.setattr(graph_mod.clarifier, "run", clarify_run)

    out = await graph_mod.research_graph.ainvoke(base_state)

    clarify_run.assert_not_awaited()
    assert fake_llm.generate_calls == 1
    assert out["answer"] == "Answer [1][2][3][4]"


@pytest.mark.asyncio
async def test_clarify_fires_short_circuits_before_generate(monkeypatch, base_state, fake_llm):
    """When CLARIFY_ENABLED and the classifier needs clarification above the
    threshold, the graph short-circuits to END: NO generation runs."""
    monkeypatch.setattr(settings, "CLARIFY_ENABLED", True)
    monkeypatch.setattr(settings, "CLARIFY_CONFIDENCE_THRESHOLD", 0.70)
    monkeypatch.setattr(
        graph_mod.research_agent,
        "_retrieve_context",
        AsyncMock(return_value=(_chunks(6), dict(STRONG_SIGNALS))),
    )
    monkeypatch.setattr(graph_mod.verifier, "run", AsyncMock())
    # Force the pre-filter to flag a candidate and the classifier to clarify.
    monkeypatch.setattr(graph_mod, "should_clarify", lambda *a, **k: True)
    decision = {
        "needs_clarification": True,
        "confidence": 0.9,
        "questions": [{"prompt": "Which entity?", "options": [], "allow_free_text": True}],
    }
    monkeypatch.setattr(graph_mod.clarifier, "run", AsyncMock(return_value=decision))
    # No session cap counting when session_id is None.

    out = await graph_mod.research_graph.ainvoke(base_state)

    assert fake_llm.generate_calls == 0
    assert fake_llm.stream_calls == 0
    assert out["clarify_decision"]["needs_clarification"] is True
    assert "answer" not in out


@pytest.mark.asyncio
async def test_clarify_below_threshold_answers(monkeypatch, base_state, fake_llm):
    """A low-confidence ambiguity verdict fails open — the graph answers."""
    monkeypatch.setattr(settings, "CLARIFY_ENABLED", True)
    monkeypatch.setattr(settings, "CLARIFY_CONFIDENCE_THRESHOLD", 0.70)
    monkeypatch.setattr(
        graph_mod.research_agent,
        "_retrieve_context",
        AsyncMock(return_value=(_chunks(6), dict(STRONG_SIGNALS))),
    )
    monkeypatch.setattr(graph_mod.verifier, "run", AsyncMock())
    monkeypatch.setattr(graph_mod, "should_clarify", lambda *a, **k: True)
    decision = {"needs_clarification": True, "confidence": 0.4, "questions": []}
    monkeypatch.setattr(graph_mod.clarifier, "run", AsyncMock(return_value=decision))

    out = await graph_mod.research_graph.ainvoke(base_state)

    assert fake_llm.generate_calls == 1
    assert out["answer"] == "Answer [1][2][3][4]"


@pytest.mark.asyncio
async def test_clarify_skipped_when_clarifications_present(monkeypatch, base_state, fake_llm):
    """The round-trip answer (clarifications present) skips the gate entirely and
    generates once, even with CLARIFY_ENABLED."""
    monkeypatch.setattr(settings, "CLARIFY_ENABLED", True)
    monkeypatch.setattr(
        graph_mod.research_agent,
        "_retrieve_context",
        AsyncMock(return_value=(_chunks(6), dict(STRONG_SIGNALS))),
    )
    monkeypatch.setattr(graph_mod.verifier, "run", AsyncMock())
    clarify_run = AsyncMock()
    monkeypatch.setattr(graph_mod.clarifier, "run", clarify_run)

    base_state["clarifications"] = [{"prompt": "Which entity?", "value": "company"}]
    out = await graph_mod.research_graph.ainvoke(base_state)

    clarify_run.assert_not_awaited()
    assert fake_llm.generate_calls == 1
    assert out["answer"] == "Answer [1][2][3][4]"


@pytest.mark.asyncio
async def test_clarify_session_cap_forces_answer(monkeypatch, base_state, fake_llm):
    """When the session already asked a clarifying question, the verdict is forced
    to needs_clarification=False and the graph answers."""
    monkeypatch.setattr(settings, "CLARIFY_ENABLED", True)
    monkeypatch.setattr(settings, "CLARIFY_CONFIDENCE_THRESHOLD", 0.70)
    monkeypatch.setattr(
        graph_mod.research_agent,
        "_retrieve_context",
        AsyncMock(return_value=(_chunks(6), dict(STRONG_SIGNALS))),
    )
    monkeypatch.setattr(graph_mod.verifier, "run", AsyncMock())
    monkeypatch.setattr(graph_mod, "should_clarify", lambda *a, **k: True)
    decision = {"needs_clarification": True, "confidence": 0.9, "questions": []}
    monkeypatch.setattr(graph_mod.clarifier, "run", AsyncMock(return_value=decision))

    # Stub the session-clarify count to report a prior clarify round.
    from unittest.mock import MagicMock as _MM

    fake_rel = _MM()
    fake_rel.queries.count_session_clarifications = lambda cid, sid: 1
    monkeypatch.setattr(graph_mod.providers, "get_relational_data", lambda: fake_rel)

    base_state["session_id"] = "sess-1"
    out = await graph_mod.research_graph.ainvoke(base_state)

    assert fake_llm.generate_calls == 1
    assert out["answer"] == "Answer [1][2][3][4]"


@pytest.mark.asyncio
async def test_follow_ups_parsed_and_not_streamed(monkeypatch, base_state):
    """With FOLLOW_UP_ENABLED, the streamed token events contain NO sentinel text
    and the final state carries the parsed follow-ups."""
    from taxflow.services.agents.research import FOLLOW_UP_SENTINEL

    monkeypatch.setattr(settings, "FOLLOW_UP_ENABLED", True)
    monkeypatch.setattr(settings, "FOLLOW_UP_STRATEGY", "inline")
    monkeypatch.setattr(settings, "FOLLOW_UP_COUNT", 3)

    answer_with_block = (
        "Here is the answer [1][2][3][4].\n"
        + FOLLOW_UP_SENTINEL
        + "\nWhat about GST?\nHow is CGT applied?"
    )
    llm = FakeLLM(answer=answer_with_block)
    monkeypatch.setattr(graph_mod.research_agent, "_llm", llm)
    monkeypatch.setattr(
        graph_mod.research_agent,
        "_build_steering",
        AsyncMock(return_value=("", None, 0)),
    )
    monkeypatch.setattr(
        graph_mod.research_agent,
        "_retrieve_context",
        AsyncMock(return_value=(_chunks(6), dict(STRONG_SIGNALS))),
    )
    monkeypatch.setattr(graph_mod.verifier, "run", AsyncMock())

    base_state["streaming"] = True
    tokens = []
    final = {}
    async for mode, chunk in graph_mod.research_graph.astream(
        base_state, stream_mode=["custom", "values"]
    ):
        if mode == "custom":
            tokens.append(chunk["token"])
        elif mode == "values":
            final = chunk

    streamed = "".join(tokens)
    assert FOLLOW_UP_SENTINEL not in streamed
    assert "GST" not in streamed  # the follow-up block never leaks as tokens
    assert final["follow_ups"] == ["What about GST?", "How is CGT applied?"]
    assert final["answer"] == "Here is the answer [1][2][3][4]."


@pytest.mark.asyncio
async def test_follow_ups_disabled_no_block(monkeypatch, base_state, fake_llm):
    """Default (FOLLOW_UP_ENABLED=False): no follow-ups are produced."""
    monkeypatch.setattr(settings, "FOLLOW_UP_ENABLED", False)
    monkeypatch.setattr(
        graph_mod.research_agent,
        "_retrieve_context",
        AsyncMock(return_value=(_chunks(6), dict(STRONG_SIGNALS))),
    )
    monkeypatch.setattr(graph_mod.verifier, "run", AsyncMock())

    out = await graph_mod.research_graph.ainvoke(base_state)
    assert out["follow_ups"] == []
