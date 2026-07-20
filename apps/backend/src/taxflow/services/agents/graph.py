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
    _compute_knowledge_as_of,
    _system_blocks,
    build_firm_items,
    build_session_fragment,
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
    client_ref: str | None
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
    re_reason: str | None
    re_detail: str | None
    streaming: bool
    # Optional trace-assembly inputs (workstreams B/C thread real values in
    # later; A1 wires them through null-safe). ``firm``/``session`` are the
    # already-merged trace fragments; ``knowledge_as_of`` the freshness stamp;
    # ``first_pass`` the first-pass generation-meta snapshot captured before any
    # corrective pass overwrites confidence/model (see C3/H3).
    firm: dict | None
    session: dict | None
    knowledge_as_of: str | None
    first_pass: dict | None
    prior_turns_used: int
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
    steering, source_type_hint, prior_turns_used = await research_agent._build_steering(
        state["question"],
        state["client_id"],
        state.get("client"),
        state.get("session_id"),
    )
    out: dict = {
        "steering": steering,
        "source_type_hint": source_type_hint,
        # Task C6: the prior-session-turn count is threaded onto the state so the
        # generate node can populate trace.session.prior_turns_used (previously
        # computed in _build_steering then discarded).
        "prior_turns_used": prior_turns_used,
    }
    # Task C6: the C-owned trace.firm fragment (profile_applied / voice_applied /
    # profile_summary / usage_trend). Set on the state ONLY when non-empty so a
    # caller-supplied firm fragment survives when there is nothing firm-specific
    # to report; the generate node MERGES B's firm_items fragment into it before
    # _build_trace (co-ownership — disjoint keys, neither side overwrites).
    firm_fragment = await research_agent._build_firm_fragment(
        state.get("client"), state["client_id"]
    )
    if firm_fragment:
        out["firm"] = firm_fragment
    return out


async def retrieve(state: AgentState) -> dict:
    chunks, signals = await research_agent._retrieve_context(
        state["question"],
        state["client_id"],
        embedding=state.get("embedding"),
        source_type_hint=state.get("source_type_hint"),
        client_ref=state.get("client_ref"),
    )
    return {"chunks": chunks, "signals": signals}


async def re_retrieve(state: AgentState) -> dict:
    """Widen the candidate pool ONCE and re-run retrieval (guarded by
    RE_RETRIEVE_ENABLED). Reuses ``_retrieve_context`` with a widened candidate
    pool (``pool_scale=2``) so weak first-pass retrieval gets a second, broader
    look before generation. The widening is threaded as a PARAMETER (Task C3) so
    the global pool ``settings`` are never mutated — concurrent requests can
    never inherit a widened pool. Sets ``re_retrieved`` so this can never repeat.
    """
    chunks, signals = await research_agent._retrieve_context(
        state["question"],
        state["client_id"],
        embedding=state.get("embedding"),
        source_type_hint=state.get("source_type_hint"),
        pool_scale=2,
        client_ref=state.get("client_ref"),
    )
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

    context, citation_map = research_agent._build_context_string(chunks)
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

    citations = research_agent._parse_citations(answer, citation_map)
    confidence = research_agent._estimate_confidence(answer, chunks, citations)
    stats = {
        "input_tokens": usage.input_tokens if usage else 0,
        "output_tokens": usage.output_tokens if usage else 0,
        "cache_read_input_tokens": usage.cache_read_input_tokens if usage else 0,
        "cache_creation_input_tokens": usage.cache_creation_input_tokens if usage else 0,
    }
    # Task C5: bump usage_count for the CITED firm chunks (best-effort) and
    # surface the cited firm citations on trace.retrieval.firm_knowledge_used.
    firm_used = research_agent._cited_firm_citations(citations)
    await research_agent._increment_firm_usage(
        state["client_id"], research_agent._cited_firm_ids(citations, chunks)
    )
    # Task B3: freshness stamp + firm-items trace fragment. MERGE the B firm
    # fragment (firm_items/firm_items_used) with C's fragment (profile/voice/
    # usage_trend, threaded via state["firm"] from the build_steering node) so
    # neither side overwrites the other's keys (co-ownership of trace.firm).
    # Merging into a copy of state["firm"] keeps it null-safe when C has nothing
    # to report. The B fragment is only merged when firm items are actually
    # present so the trace.firm block stays absent when neither side has content.
    knowledge_as_of = state.get("knowledge_as_of") or _compute_knowledge_as_of(
        chunks, citations
    )
    firm_fragment = dict(state.get("firm") or {})
    firm_items = build_firm_items(chunks, citations)
    if firm_items["firm_items"]:
        firm_fragment.update(firm_items)
    # Task C6: the C-owned trace.session fragment (prior_turns_used from the
    # build_steering node, engagement_memos_used counted from the retrieved
    # pool, client_ref from state). None for a plain single-shot query, so a
    # caller-supplied session fragment is preferred when present.
    session_fragment = state.get("session") or build_session_fragment(
        state.get("prior_turns_used", 0),
        research_agent._engagement_memos_used(chunks),
        state.get("client_ref"),
    )
    trace = research_agent._build_trace(
        chunks,
        citations,
        state.get("source_type_hint"),
        state["routed_tier"],
        stats,
        confidence,
        firm=firm_fragment or None,
        session=session_fragment,
        knowledge_as_of=knowledge_as_of,
        firm_knowledge_used=firm_used or None,
        citation_map=citation_map,
    )
    return {
        "answer": answer,
        "citations": citations,
        "confidence": confidence,
        # Task 1c: the concrete resolved model id (a runtime resolve_model value,
        # never a literal) so the router can persist queries.model_id alongside
        # the abstract routed_tier stored in model_used.
        "model_id": model,
        **stats,
        # Answer-flow trace (migration 022 / "why this answer?" UI): capture what
        # retrieval returned and what generation did on the first pass. Optional
        # firm/session/knowledge_as_of inputs are read via state.get(...) so the
        # manual-stats streaming path and research.run assemble identical traces
        # (no usage.as_dict() dependency — guards the streaming _Usage bug).
        "trace": trace,
        # First-pass generation-meta snapshot (Task C3/H3): captured HERE, before
        # any corrective pass overwrites confidence/model in state, so both the
        # POST and SSE paths have a real first-pass record for trace.passes. Read
        # via state.get in _build_final_trace, so it survives the corrective pass
        # overwriting state["confidence"].
        "first_pass": trace["generation"],
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

    Task C3: the corrective pass passes ``widen=True`` so retrieval re-runs with
    a widened pool (``pool_scale=2``, threaded as a parameter — never a global
    settings mutation). Because the STORED answer is the corrected one, the
    corrected answer's trace REPLACES the top-level ``state["trace"]`` (so the
    top-level ``retrieval``/``generation`` describe the corrected answer); the
    ``generate`` node's ``first_pass`` snapshot is left untouched so
    ``trace.passes.first_pass`` still carries the original meta. The returned
    ``re_retrieval`` (reason ``"reviewer_flag"``) is threaded into state so A1's
    ``_build_final_trace`` records ``re_retrieval.fired``.
    """
    verification = state.get("verification") or {}
    result = await research_agent.regenerate_with_feedback(
        state["question"],
        state["client_id"],
        issues=verification.get("issues", []),
        embedding=state.get("embedding"),
        client=state.get("client"),
        session_id=state.get("session_id"),
        client_ref=state.get("client_ref"),
        widen=True,
    )
    out: dict = {
        "answer": result["answer"],
        "citations": result["citations"],
        "confidence": result["confidence"],
        "caveat": build_caveat(verification),
        "corrected_meta": result,
        "corrective_count": state.get("corrective_count", 0) + 1,
    }
    # The stored answer is the corrected one, so the top-level trace must
    # describe it. Replace state["trace"] with the corrected pass's trace; the
    # generate node's `first_pass` snapshot is NOT touched, so
    # trace.passes.first_pass keeps the original meta.
    if result.get("trace") is not None:
        out["trace"] = result["trace"]
    # Thread the reviewer-driven widen result so _build_final_trace emits
    # re_retrieval.fired. Only set when the widen actually fired, so a prior
    # weak-signal re_retrieve flag is never clobbered.
    re_retrieval = result.get("re_retrieval") or {}
    if result.get("re_retrieved"):
        out["re_retrieved"] = True
        out["re_reason"] = re_retrieval.get("reason")
    return out


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
