"""Tests for the feedback endpoint (Task C5) and stream-path metric persistence."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _override(fake_client, mock_db):
    from taxflow.main import app
    from taxflow.middleware.auth import get_current_client
    from taxflow.middleware.trial_gate import check_trial_gate
    from taxflow.db import get_db

    app.dependency_overrides[get_current_client] = lambda: fake_client
    app.dependency_overrides[check_trial_gate] = lambda: fake_client
    app.dependency_overrides[get_db] = lambda: mock_db


# --- Task C5: feedback endpoint enforces client ownership ---------------------


def test_feedback_rejects_query_from_another_client(client):
    from taxflow.main import app

    fake_client = {"id": "client-1", "email": "a@b.com.au"}
    mock_db = MagicMock()
    # Ownership check returns None -> the query belongs to another client.
    mock_db.queries.get_for_client.return_value = None

    _override(fake_client, mock_db)
    try:
        resp = client.post("/query/other-clients-query/feedback", json={"rating": "up"})
        assert resp.status_code == 404
        # No feedback row must be inserted for a foreign query.
        mock_db.query_feedback.insert.assert_not_called()
    finally:
        app.dependency_overrides.clear()


def test_feedback_accepts_own_query(client):
    from taxflow.main import app

    fake_client = {"id": "client-1", "email": "a@b.com.au"}
    mock_db = MagicMock()
    mock_db.queries.get_for_client.return_value = {"id": "q1"}
    mock_db.query_feedback.insert.return_value = {"id": "fb1"}

    _override(fake_client, mock_db)
    try:
        resp = client.post("/query/q1/feedback", json={"rating": "down", "note": "wrong section"})
        assert resp.status_code == 200
        assert resp.json()["rating"] == "down"
    finally:
        app.dependency_overrides.clear()


def test_feedback_rejects_bad_rating(client):
    from taxflow.main import app

    fake_client = {"id": "client-1", "email": "a@b.com.au"}
    mock_db = MagicMock()
    _override(fake_client, mock_db)
    try:
        resp = client.post("/query/q1/feedback", json={"rating": "meh"})
        assert resp.status_code == 422
    finally:
        app.dependency_overrides.clear()


# --- Task A6: the SSE stream drives the compiled graph via astream ------------
#
# LangGraph (>=1.2,<2) with stream_mode=["custom","values"] yields (mode, chunk)
# TUPLES: "custom" carries the generate node's {"token": ...} writer events, and
# "values" carries a full state snapshot on every update. The stream helpers
# below mimic that exact tuple shape.


def _values(**overrides):
    """A full-state `values` snapshot with sensible defaults for a stream run."""
    state = {
        "answer": "",
        "citations": [],
        "confidence": 0.0,
        "routed_tier": "haiku",
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
    }
    state.update(overrides)
    return state


@pytest.mark.asyncio
async def test_stream_persists_metrics():
    import taxflow.routers.query as q

    fake_client = {"id": "client-1", "email": "a@b.com.au"}

    captured_update = {}
    mock_db = MagicMock()
    mock_db.queries.insert.return_value = {"id": "query-1"}
    mock_db.queries.update.side_effect = lambda cid, qid, payload: captured_update.update(payload)

    async def fake_astream(initial_state, stream_mode=None):
        assert stream_mode == ["custom", "values"]
        yield ("custom", {"token": "hello "})
        yield ("custom", {"token": "world [1]"})
        # Final snapshot: verify skipped -> no verification/caveat/corrected_meta.
        yield (
            "values",
            _values(
                answer="hello world [1]",
                citations=[{"citation": "x"}],
                confidence=0.9,
                routed_tier="sonnet",
                input_tokens=100,
                output_tokens=50,
                cache_read_input_tokens=40,
                cache_creation_input_tokens=10,
            ),
        )

    with patch.object(
        q, "embed", new=AsyncMock(return_value=[0.0] * 1536)
    ), patch.object(q, "increment_usage", new=AsyncMock()), patch.object(
        q.research_graph, "astream", new=fake_astream
    ), patch.object(
        q.answer_cache, "store_answer", new=AsyncMock()
    ), patch.object(
        q.answer_cache, "get_cached_answer", new=AsyncMock(return_value=None)
    ), patch.object(
        q.answer_cache, "count_prior_asks", new=AsyncMock(return_value=0)
    ):
        response = await q.stream_query(question="q", client=fake_client, _trial=fake_client, db=mock_db)
        chunks = [c async for c in response.body_iterator]

    assert captured_update["model_used"] == "sonnet"
    assert captured_update["confidence_score"] == 0.9
    assert captured_update["input_tokens"] == 100
    assert captured_update["output_tokens"] == 50
    assert captured_update["cache_read_input_tokens"] == 40
    assert captured_update["cache_creation_input_tokens"] == 10
    assert captured_update["wall_time_ms"] is not None

    # Task 1b/1c: observability columns are persisted on a normal generation.
    assert "citation_valid" in captured_update
    assert "invalid_citations" in captured_update
    assert captured_update["cost_usd"] is not None
    assert "model_id" in captured_update

    # Contract order (no correction): token* -> final(once) -> verification ->
    # trace -> repeat_count -> [DONE].
    types = [_event_type(c) for c in chunks]
    assert types.count("final") == 1
    assert types == ["token", "token", "final", "verification", "trace", "repeat_count", None]
    assert chunks[-1] == "data: [DONE]\n\n"


@pytest.mark.asyncio
async def test_stream_observability_failure_is_best_effort():
    """Task 1b: if the observability add-on (check_citation_validity / run_cost)
    raises, the ALREADY-PAID-FOR generation must still succeed and persist — the
    observability columns are stored NULL rather than failing the request."""
    import taxflow.routers.query as q

    fake_client = {"id": "client-1", "email": "a@b.com.au"}

    captured_update = {}
    mock_db = MagicMock()
    mock_db.queries.insert.return_value = {"id": "query-1"}
    mock_db.queries.update.side_effect = lambda cid, qid, payload: captured_update.update(payload)

    async def fake_astream(initial_state, stream_mode=None):
        yield ("custom", {"token": "hello "})
        yield ("custom", {"token": "world [1]"})
        yield (
            "values",
            _values(
                answer="hello world [1]",
                citations=[{"citation": "x"}],
                confidence=0.9,
                routed_tier="sonnet",
                model_id="anthropic/sonnet-concrete",
                input_tokens=100,
                output_tokens=50,
            ),
        )

    with patch.object(
        q, "embed", new=AsyncMock(return_value=[0.0] * 1536)
    ), patch.object(q, "increment_usage", new=AsyncMock()), patch.object(
        q.research_graph, "astream", new=fake_astream
    ), patch.object(
        q.answer_cache, "store_answer", new=AsyncMock()
    ), patch.object(
        q.answer_cache, "get_cached_answer", new=AsyncMock(return_value=None)
    ), patch.object(
        q.answer_cache, "count_prior_asks", new=AsyncMock(return_value=0)
    ), patch.object(
        q, "run_cost", side_effect=RuntimeError("boom")
    ):
        response = await q.stream_query(question="q", client=fake_client, _trial=fake_client, db=mock_db)
        chunks = [c async for c in response.body_iterator]

    # The query still completed and persisted the generation metadata.
    assert captured_update["status"] == "completed"
    assert captured_update["model_used"] == "sonnet"
    assert captured_update["final_answer"] == "hello world [1]"
    # Observability fields fell back to NULL rather than 500ing the request.
    assert captured_update["citation_valid"] is None
    assert captured_update["invalid_citations"] is None
    assert captured_update["cost_usd"] is None
    # model_id comes from state, not the failing helper, so it's still persisted.
    assert captured_update["model_id"] == "anthropic/sonnet-concrete"
    # Stream still terminated normally.
    assert chunks[-1] == "data: [DONE]\n\n"


@pytest.mark.asyncio
async def test_stream_correction_swaps_metadata_and_emits_event():
    """Stream path: BOTH verify and a corrective pass run — the graph's final
    state carries the corrected answer + caveat + corrected_meta. The router
    emits `final`(once) then `correction`, and persists the corrective (Sonnet)
    metadata — not the streamed first-pass values (Task A6)."""
    import json

    import taxflow.routers.query as q

    fake_client = {"id": "client-1", "email": "a@b.com.au"}

    captured_update = {}
    store_calls = []
    mock_db = MagicMock()
    mock_db.queries.insert.return_value = {"id": "query-1"}
    mock_db.queries.update.side_effect = lambda cid, qid, payload: captured_update.update(payload)

    verification = {"overall_status": "needs_correction", "issues": [{"severity": "critical"}]}

    async def fake_astream(initial_state, stream_mode=None):
        assert stream_mode == ["custom", "values"]
        yield ("custom", {"token": "first "})
        yield ("custom", {"token": "pass answer [1]"})
        # First-pass snapshot right after generate (before verify/corrective).
        yield (
            "values",
            _values(
                answer="first pass answer [1]",
                citations=[{"citation": "x"}],
                confidence=0.3,
                routed_tier="haiku",
                input_tokens=100,
                output_tokens=50,
                cache_read_input_tokens=40,
                cache_creation_input_tokens=10,
            ),
        )
        # Final snapshot after verify + one corrective pass. The graph OVERWRITES
        # answer/citations/confidence in state with the corrected pass, so this
        # snapshot carries the corrected values — the `final` event must NOT use
        # them (it must use the first-pass snapshot captured above).
        yield (
            "values",
            _values(
                answer="Corrected answer [1]",
                citations=[{"citation": "y"}],
                confidence=0.85,
                routed_tier="haiku",
                verification=verification,
                caveat="Caveat: review claim 1.",
                corrected_meta={
                    "answer": "Corrected answer [1]",
                    "citations": [{"citation": "y"}],
                    "confidence": 0.85,
                    "model_used": "sonnet",
                    "input_tokens": 300,
                    "output_tokens": 120,
                    "cache_read_input_tokens": 200,
                    "cache_creation_input_tokens": 0,
                },
                input_tokens=100,
                output_tokens=50,
                cache_read_input_tokens=40,
                cache_creation_input_tokens=10,
            ),
        )

    async def store_answer(*args, **kwargs):
        store_calls.append(args)

    with patch.object(
        q, "embed", new=AsyncMock(return_value=[0.0] * 1536)
    ), patch.object(q, "increment_usage", new=AsyncMock()), patch.object(
        q.research_graph, "astream", new=fake_astream
    ), patch.object(
        q.answer_cache, "store_answer", new=AsyncMock(side_effect=store_answer)
    ), patch.object(
        q.answer_cache, "get_cached_answer", new=AsyncMock(return_value=None)
    ), patch.object(
        q.answer_cache, "count_prior_asks", new=AsyncMock(return_value=0)
    ):
        response = await q.stream_query(question="q", client=fake_client, _trial=fake_client, db=mock_db)
        chunks = [c async for c in response.body_iterator]

    # Persisted metadata reflects the corrective (Sonnet) pass, not the first pass.
    assert captured_update["model_used"] == "sonnet"
    assert captured_update["confidence_score"] == 0.85
    assert captured_update["input_tokens"] == 300
    assert captured_update["output_tokens"] == 120
    assert captured_update["cache_read_input_tokens"] == 200
    assert "Corrected answer [1]" in captured_update["final_answer"]
    assert captured_update["verification_result"] == verification

    # Contract order with both verify + correction:
    # token* -> final(once) -> correction -> verification -> trace ->
    # repeat_count -> [DONE].
    types = [_event_type(c) for c in chunks]
    assert types.count("final") == 1
    assert types == [
        "token",
        "token",
        "final",
        "correction",
        "verification",
        "trace",
        "repeat_count",
        None,
    ]

    # The `final` event must carry the FIRST-pass values — model (haiku),
    # citations and confidence from the snapshot right after generate — NOT the
    # corrected values the graph later wrote into state (BLOCKING fix).
    final_chunk = next(c for c in chunks if _event_type(c) == "final")
    final_payload = json.loads(final_chunk.removeprefix("data: ").strip())
    assert final_payload["model_used"] == "haiku"
    assert final_payload["confidence"] == 0.3
    assert final_payload["citations"] == [{"citation": "x"}]

    # A `correction` event carries the authoritative corrected answer + citations
    # + caveat.
    correction_chunk = next(c for c in chunks if _event_type(c) == "correction")
    payload = json.loads(correction_chunk.removeprefix("data: ").strip())
    assert "Corrected answer [1]" in payload["answer"]
    assert payload["citations"] == [{"citation": "y"}]
    assert payload["caveat"] == "Caveat: review claim 1."
    assert payload["model_used"] == "sonnet"

    # A needs_correction answer must NEVER be cached (B3 _safe_to_cache gate).
    assert store_calls == []


@pytest.mark.asyncio
async def test_stream_cache_hit_skips_embed_and_generation():
    """Stream path: a cache hit must serve the stored answer WITHOUT calling the
    paid OpenAI embed or the research graph, and emit cached: true (Task B3)."""
    import json

    import taxflow.routers.query as q

    fake_client = {"id": "client-1", "email": "a@b.com.au"}
    mock_db = MagicMock()
    mock_db.queries.insert.return_value = {"id": "cached-query-1"}

    cached = {
        "answer": "Cached answer [1]",
        "citations": [{"citation": "x"}],
        "confidence": 0.9,
        "model_used": "haiku",
    }

    embed_mock = AsyncMock(return_value=[0.0] * 1536)
    astream_mock = MagicMock()

    with patch.object(
        q, "embed", new=embed_mock
    ), patch.object(q, "increment_usage", new=AsyncMock()), patch.object(
        q.research_graph, "astream", new=astream_mock
    ), patch.object(
        q.answer_cache, "get_cached_answer", new=AsyncMock(return_value=cached)
    ), patch.object(
        q.answer_cache, "count_prior_asks", new=AsyncMock(return_value=0)
    ):
        response = await q.stream_query(question="q", client=fake_client, _trial=fake_client, db=mock_db)
        chunks = [c async for c in response.body_iterator]

    # No paid work on a cache hit.
    embed_mock.assert_not_awaited()
    astream_mock.assert_not_called()

    # The cached answer is streamed and the final event marks it cached.
    joined = "".join(chunks)
    assert "Cached answer [1]" in joined
    final_chunk = next(c for c in chunks if '"type": "final"' in c)
    payload = json.loads(final_chunk.removeprefix("data: ").strip())
    assert payload["cached"] is True
    assert payload["model_used"] == "cache"
    assert chunks[-1] == "data: [DONE]\n\n"


@pytest.mark.asyncio
async def test_stream_session_id_bypasses_cache():
    """A session_id must bypass the answer-cache read/write on the stream path."""
    import taxflow.routers.query as q

    fake_client = {"id": "client-1", "email": "a@b.com.au"}
    mock_db = MagicMock()
    mock_db.queries.insert.return_value = {"id": "query-1"}

    async def fake_astream(initial_state, stream_mode=None):
        assert initial_state["session_id"] == "sess-1"
        yield ("custom", {"token": "hi [1]"})
        yield (
            "values",
            _values(answer="hi [1]", citations=[{"citation": "x"}], confidence=0.9),
        )

    get_cache_mock = AsyncMock(return_value=None)
    store_mock = AsyncMock()

    with patch.object(
        q, "embed", new=AsyncMock(return_value=[0.0] * 1536)
    ), patch.object(q, "increment_usage", new=AsyncMock()), patch.object(
        q.research_graph, "astream", new=fake_astream
    ), patch.object(
        q.answer_cache, "get_cached_answer", new=get_cache_mock
    ), patch.object(
        q.answer_cache, "store_answer", new=store_mock
    ), patch.object(
        q.answer_cache, "count_prior_asks", new=AsyncMock(return_value=0)
    ):
        response = await q.stream_query(
            question="q", client=fake_client, _trial=fake_client, db=mock_db, session_id="sess-1"
        )
        _ = [c async for c in response.body_iterator]

    # Session-scoped: cache neither read nor written.
    get_cache_mock.assert_not_awaited()
    store_mock.assert_not_awaited()


# --- Task A6: real compiled graph yields (mode, chunk) tuples -----------------


@pytest.mark.asyncio
async def test_compiled_graph_astream_yields_mode_chunk_tuples():
    """Pin the LangGraph (>=1.2,<2) multi-mode contract the router depends on:
    astream(stream_mode=["custom","values"]) yields (mode, chunk) 2-tuples, with
    the generate node emitting {"token": ...} custom events and the first values
    snapshot carrying the first-pass answer (before verification appears)."""
    from types import SimpleNamespace

    import taxflow.services.agents.graph as g

    class _Usage:
        input_tokens = 1
        output_tokens = 1
        cache_read_input_tokens = 0
        cache_creation_input_tokens = 0

    class _Chunk:
        def __init__(self, text="", done=False, usage=None):
            self.text = text
            self.done = done
            self.usage = usage

    async def fake_llm_stream(**kwargs):
        yield _Chunk("hi ", False)
        yield _Chunk("there [1]", False)
        yield _Chunk("", True, _Usage())

    with patch.object(
        g.research_agent, "_build_steering", new=AsyncMock(return_value=("", None, 0))
    ), patch.object(
        g.research_agent,
        "_retrieve_context",
        new=AsyncMock(return_value=([{"id": 1, "citation": "x", "source_type": "ruling", "score": 1.0}], {"num_chunks": 1, "top_score": 1.0})),
    ), patch.object(
        g.research_agent, "_build_context_string", return_value=("ctx", [{"citation": "x", "source_url": None, "parent_key": None, "chunks": [{"id": 1, "citation": "x", "content": "c", "source_url": None}]}])
    ), patch.object(
        g.research_agent, "_user_content", return_value="uc"
    ), patch.object(
        g.research_agent, "_parse_citations", return_value=[{"citation": "x"}]
    ), patch.object(
        g.research_agent, "_estimate_confidence", return_value=0.9
    ), patch.object(
        g, "_system_blocks", return_value=[]
    ), patch.object(
        g, "route_model", return_value="haiku"
    ), patch.object(
        g, "should_verify", return_value=False
    ), patch.object(
        g.providers, "resolve_model", return_value="m"
    ), patch.object(
        g.research_agent, "_llm", SimpleNamespace(stream=fake_llm_stream)
    ):
        initial = {
            "question": "q",
            "client": None,
            "client_id": "c",
            "session_id": None,
            "embedding": None,
            "streaming": True,
            "corrective_count": 0,
            "re_retrieved": False,
        }
        items = [
            item
            async for item in g.research_graph.astream(
                initial, stream_mode=["custom", "values"]
            )
        ]

    # Every yielded item is a (mode, chunk) 2-tuple.
    assert all(isinstance(item, tuple) and len(item) == 2 for item in items)
    modes = {item[0] for item in items}
    assert modes <= {"custom", "values"}

    custom = [item[1] for item in items if item[0] == "custom"]
    assert custom == [{"token": "hi "}, {"token": "there [1]"}]

    # The last values snapshot is the final state with the assembled answer.
    values = [item[1] for item in items if item[0] == "values"]
    assert values[-1]["answer"] == "hi there [1]"
    # verify was skipped -> no verification key in the final state.
    assert values[-1].get("verification") is None


def _event_type(chunk: str):
    """Return the SSE event `type` for a data chunk, or None for [DONE]."""
    import json

    payload = chunk.removeprefix("data: ").strip()
    if payload == "[DONE]":
        return None
    return json.loads(payload).get("type")


# --- Phase 4: clarify + follow_ups SSE event ordering ------------------------


@pytest.mark.asyncio
async def test_stream_clarify_terminal_event():
    """An ambiguous first turn yields a single `clarify` event then [DONE],
    skipping token/final/verification/trace/repeat_count. A clarify row with
    trace.clarify.asked=true is persisted."""
    import taxflow.routers.query as q

    fake_client = {"id": "client-1", "email": "a@b.com.au"}
    captured_update = {}
    mock_db = MagicMock()
    mock_db.queries.insert.return_value = {"id": "query-1"}
    mock_db.queries.update.side_effect = lambda cid, qid, payload: captured_update.update(payload)

    async def fake_astream(initial_state, stream_mode=None):
        # The clarify short-circuit yields no tokens, only a final values snapshot
        # carrying the needs_clarification verdict.
        yield (
            "values",
            _values(
                clarify_decision={
                    "needs_clarification": True,
                    "confidence": 0.9,
                    "questions": [
                        {"prompt": "Which entity?", "options": [], "allow_free_text": True}
                    ],
                }
            ),
        )

    with patch.object(
        q, "embed", new=AsyncMock(return_value=[0.0] * 1536)
    ), patch.object(q, "increment_usage", new=AsyncMock()), patch.object(
        q.research_graph, "astream", new=fake_astream
    ), patch.object(
        q.answer_cache, "get_cached_answer", new=AsyncMock(return_value=None)
    ), patch.object(
        q.answer_cache, "count_prior_asks", new=AsyncMock(return_value=0)
    ):
        response = await q.stream_query(question="q?", client=fake_client, _trial=fake_client, db=mock_db)
        chunks = [c async for c in response.body_iterator]

    types = [_event_type(c) for c in chunks]
    assert types == ["clarify", None]
    assert chunks[-1] == "data: [DONE]\n\n"
    # Persisted clarify row gates the session cap.
    assert captured_update["model_used"] == "clarify"
    assert captured_update["trace"]["clarify"]["asked"] is True


@pytest.mark.asyncio
async def test_stream_follow_ups_event_after_final():
    """With follow-ups produced, the `follow_ups` event is emitted right after
    `final` and before verification/trace; trace persists trace.follow_ups."""
    import taxflow.routers.query as q

    fake_client = {"id": "client-1", "email": "a@b.com.au"}
    captured_update = {}
    mock_db = MagicMock()
    mock_db.queries.insert.return_value = {"id": "query-1"}
    mock_db.queries.update.side_effect = lambda cid, qid, payload: captured_update.update(payload)

    async def fake_astream(initial_state, stream_mode=None):
        yield ("custom", {"token": "answer [1]"})
        yield (
            "values",
            _values(
                answer="answer [1]",
                citations=[{"citation": "x"}],
                confidence=0.9,
                trace={"retrieval": {}, "generation": {"model": "haiku"}},
                follow_ups=["What about GST?", "How is CGT applied?"],
            ),
        )

    with patch.object(
        q, "embed", new=AsyncMock(return_value=[0.0] * 1536)
    ), patch.object(q, "increment_usage", new=AsyncMock()), patch.object(
        q.research_graph, "astream", new=fake_astream
    ), patch.object(
        q.answer_cache, "store_answer", new=AsyncMock()
    ), patch.object(
        q.answer_cache, "get_cached_answer", new=AsyncMock(return_value=None)
    ), patch.object(
        q.answer_cache, "count_prior_asks", new=AsyncMock(return_value=0)
    ):
        response = await q.stream_query(question="q", client=fake_client, _trial=fake_client, db=mock_db)
        chunks = [c async for c in response.body_iterator]

    types = [_event_type(c) for c in chunks]
    assert types == [
        "token",
        "final",
        "follow_ups",
        "verification",
        "trace",
        "repeat_count",
        None,
    ]
    # trace.follow_ups persisted additively.
    assert captured_update["trace"]["follow_ups"] == [
        "What about GST?",
        "How is CGT applied?",
    ]
    follow_chunk = next(c for c in chunks if _event_type(c) == "follow_ups")
    import json as _json

    assert _json.loads(follow_chunk.removeprefix("data: ").strip())["questions"] == [
        "What about GST?",
        "How is CGT applied?",
    ]
