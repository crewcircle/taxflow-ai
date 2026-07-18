"""LangGraph agent-loop for research queries (Task A5).

The graph is a THIN orchestration layer over the existing
:class:`ResearchAgent` / :class:`VerifyAgent` logic — nodes are wrappers that
reuse those methods rather than re-implementing retrieval, routing, generation
or verification. The bounded control flow (retrieve → optional single
re-retrieve → route → generate → gated verify → at-most-once corrective pass)
mirrors what ``routers/query.py`` orchestrates today, so accuracy behaviour is
unchanged; only the wiring moves into an explicit graph.

The compiled graph is a module-level singleton (like today's
``agent = ResearchAgent()``) built once at import via
:func:`build_research_graph`. Wiring it into the HTTP layer is Task A6.
"""

from __future__ import annotations

from typing import Any, TypedDict

from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph

from taxflow import providers
from taxflow.config import settings
from taxflow.services.agents.research import (
    ResearchAgent,
    _system_blocks,
    route_model,
)
from taxflow.services.agents.verify import (
    VerifyAgent,
    build_caveat,
    needs_correction,
    should_verify,
    verify_model_for,
)

# Module-level singletons, reused by every node. The LLMPort is injected into
# the agents (defaulting to providers.get_llm()) so the whole graph is testable
# with fake ports by swapping these out.
research_agent = ResearchAgent()
verifier = VerifyAgent()


class AgentState(TypedDict, total=False):
    """State threaded through the research graph.

    ``corrective_count`` starts at 0 and is incremented by ``corrective_generate``
    so the at-most-once corrective pass can be gated. ``re_retrieved`` starts
    False and is set True by ``re_retrieve`` so the single widening pass never
    repeats. ``streaming`` selects the generate-node mode: POST sets it False
    (buffered ``llm.generate``), SSE sets it True (token streaming via the
    LangGraph stream writer).
    """

    question: str
    client: dict | None
    client_id: str
    session_id: str | None
    embedding: list[float] | None
    steering: str
    source_type_hint: list[str] | None
    chunks: list[dict]
    signals: dict
    routed_tier: str
    answer: str
    citations: list[dict]
    confidence: float
    verification: dict | None
    caveat: str | None
    corrected_meta: dict | None
    corrective_count: int
    re_retrieved: bool
    streaming: bool
    input_tokens: int
    output_tokens: int
    cache_read_input_tokens: int
    cache_creation_input_tokens: int
    trace: dict


def _weak_signal(signals: dict) -> bool:
    """True when retrieval looks weak enough to justify a single re-retrieval.

    Weak = nothing retrieved, or the top RRF score sits below the configured
    re-retrieval floor (RE_RETRIEVE_MIN_TOP_SCORE).
    """
    if signals.get("insufficient") or signals.get("num_chunks", 0) == 0:
        return True
    top_score = signals.get("top_score", 0.0) or 0.0
    return top_score < settings.RE_RETRIEVE_MIN_TOP_SCORE


# --- nodes (thin wrappers over ResearchAgent / VerifyAgent) ------------------


async def build_steering(state: AgentState) -> dict:
    steering, source_type_hint = await research_agent._build_steering(
        state["question"],
        state["client_id"],
        state.get("client"),
        state.get("session_id"),
    )
    return {"steering": steering, "source_type_hint": source_type_hint}


async def retrieve(state: AgentState) -> dict:
    chunks, signals = await research_agent._retrieve_context(
        state["question"],
        state["client_id"],
        embedding=state.get("embedding"),
        source_type_hint=state.get("source_type_hint"),
    )
    return {"chunks": chunks, "signals": signals}


async def re_retrieve(state: AgentState) -> dict:
    """Widen the candidate pool ONCE and re-run retrieval (guarded by
    RE_RETRIEVE_ENABLED). Reuses ``_retrieve_context`` with a temporarily
    doubled candidate pool so weak first-pass retrieval gets a second, broader
    look before generation. Sets ``re_retrieved`` so this can never repeat.
    """
    original_pool = settings.RERANK_CANDIDATE_POOL
    original_global = settings.RETRIEVAL_GLOBAL_POOL
    try:
        settings.RERANK_CANDIDATE_POOL = original_pool * 2
        settings.RETRIEVAL_GLOBAL_POOL = original_global * 2
        chunks, signals = await research_agent._retrieve_context(
            state["question"],
            state["client_id"],
            embedding=state.get("embedding"),
            source_type_hint=state.get("source_type_hint"),
        )
    finally:
        settings.RERANK_CANDIDATE_POOL = original_pool
        settings.RETRIEVAL_GLOBAL_POOL = original_global
    return {"chunks": chunks, "signals": signals, "re_retrieved": True}


def route_model_node(state: AgentState) -> dict:
    # route_model() keeps returning a TIER name ("haiku"/"sonnet"); the concrete
    # model id is resolved at the generate call boundary via resolve_model().
    return {"routed_tier": route_model(state["signals"])}


async def generate(state: AgentState) -> dict:
    """Single generation pass with an EXPLICIT streaming/non-streaming switch.

    - ``streaming is False`` → buffered ``llm.generate`` (no writer touched).
    - ``streaming is True``  → obtain the LangGraph stream writer INSIDE the
      node (correct for langgraph>=1.2,<2), iterate ``llm.stream`` and emit one
      ``{"token": ...}`` custom event per text chunk, accumulating the full text
      and the terminal usage into the final state.
    """
    chunks = state["chunks"]
    steering = state.get("steering", "")
    question = state["question"]
    model = providers.resolve_model(state["routed_tier"])

    context = research_agent._build_context_string(chunks)
    messages = [
        {"role": "user", "content": research_agent._user_content(question, context, steering)}
    ]
    llm = research_agent._llm

    if state["streaming"] is False:
        result = await llm.generate(
            messages=messages,
            system=_system_blocks(),
            model=model,
            max_tokens=1500,
            temperature=0,
        )
        answer = result.text
        usage = result.usage
    else:
        writer = get_stream_writer()
        parts: list[str] = []
        usage = None
        async for chunk in llm.stream(
            messages=messages,
            system=_system_blocks(),
            model=model,
            max_tokens=1500,
            temperature=0,
        ):
            if chunk.text:
                parts.append(chunk.text)
                writer({"token": chunk.text})
            if chunk.done:
                usage = chunk.usage
        answer = "".join(parts)

    citations = research_agent._parse_citations(answer, chunks)
    confidence = research_agent._estimate_confidence(answer, chunks, citations)
    stats = {
        "input_tokens": usage.input_tokens if usage else 0,
        "output_tokens": usage.output_tokens if usage else 0,
        "cache_read_input_tokens": usage.cache_read_input_tokens if usage else 0,
        "cache_creation_input_tokens": usage.cache_creation_input_tokens if usage else 0,
    }
    return {
        "answer": answer,
        "citations": citations,
        "confidence": confidence,
        **stats,
        # Answer-flow trace (migration 022 / "why this answer?" UI): capture what
        # retrieval returned and what generation did on the first pass.
        "trace": research_agent._build_trace(
            chunks, citations, state.get("source_type_hint"), state["routed_tier"], stats, confidence
        ),
    }


async def verify(state: AgentState) -> dict:
    verification = await verifier.run(
        draft=state["answer"],
        citations=state["citations"],
        question=state["question"],
        model=verify_model_for(state["confidence"], state["citations"], state["answer"]),
    )
    return {"verification": verification}


async def corrective_generate(state: AgentState) -> dict:
    """ONE bounded corrective regeneration (Task C3), reusing
    ``regenerate_with_feedback``. Increments ``corrective_count`` and attaches a
    caveat. There is no edge back to verify — the corrective pass is
    at-most-once and is NOT re-verified.
    """
    verification = state.get("verification") or {}
    result = await research_agent.regenerate_with_feedback(
        state["question"],
        state["client_id"],
        issues=verification.get("issues", []),
        embedding=state.get("embedding"),
        client=state.get("client"),
        session_id=state.get("session_id"),
    )
    return {
        "answer": result["answer"],
        "citations": result["citations"],
        "confidence": result["confidence"],
        "caveat": build_caveat(verification),
        "corrected_meta": result,
        "corrective_count": state.get("corrective_count", 0) + 1,
    }


# --- conditional edges -------------------------------------------------------


def route_after_retrieve(state: AgentState) -> str:
    if (
        settings.RE_RETRIEVE_ENABLED
        and not state.get("re_retrieved", False)
        and _weak_signal(state["signals"])
    ):
        return "re_retrieve"
    return "route_model"


def route_after_generate(state: AgentState) -> str:
    if should_verify(state["confidence"], state["citations"], state["answer"]):
        return "verify"
    return END


def route_after_verify(state: AgentState) -> str:
    if (
        settings.CORRECTIVE_PASS_ENABLED
        and state.get("corrective_count", 0) == 0
        and needs_correction(state.get("verification") or {})
    ):
        return "corrective_generate"
    return END


def build_research_graph() -> Any:
    """Compile the bounded research graph. Called once at module import."""
    g = StateGraph(AgentState)
    g.add_node("build_steering", build_steering)
    g.add_node("retrieve", retrieve)
    g.add_node("re_retrieve", re_retrieve)
    g.add_node("route_model", route_model_node)
    g.add_node("generate", generate)
    g.add_node("verify", verify)
    g.add_node("corrective_generate", corrective_generate)

    g.add_edge(START, "build_steering")
    g.add_edge("build_steering", "retrieve")
    g.add_conditional_edges(
        "retrieve",
        route_after_retrieve,
        {"re_retrieve": "re_retrieve", "route_model": "route_model"},
    )
    g.add_edge("re_retrieve", "route_model")
    g.add_edge("route_model", "generate")
    g.add_conditional_edges(
        "generate", route_after_generate, {"verify": "verify", END: END}
    )
    g.add_conditional_edges(
        "verify",
        route_after_verify,
        {"corrective_generate": "corrective_generate", END: END},
    )
    g.add_edge("corrective_generate", END)
    return g.compile()


# Module-level singleton compiled graph (Task A6 wires this into query.py).
research_graph = build_research_graph()
