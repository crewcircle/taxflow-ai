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
        AsyncMock(return_value=("", None)),
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
        }
    )
    monkeypatch.setattr(graph_mod.research_agent, "regenerate_with_feedback", regen)

    out = await graph_mod.research_graph.ainvoke(base_state)

    # Corrective pass runs EXACTLY once, and verify runs exactly once (no
    # re-verification of the corrected answer — no edge back to verify).
    regen.assert_awaited_once()
    assert verify_run.await_count == 1
    assert out["corrective_count"] == 1
    assert out["answer"] == "Corrected [1]"
    assert out["caveat"] is not None
    assert out["corrected_meta"]["model_used"] == "sonnet"


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
