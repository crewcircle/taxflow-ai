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
    # Ownership check returns no rows -> the query belongs to another client.
    ownership = mock_db.table.return_value.select.return_value.eq.return_value.eq.return_value.execute
    ownership.return_value.data = []

    _override(fake_client, mock_db)
    try:
        resp = client.post("/query/other-clients-query/feedback", json={"rating": "up"})
        assert resp.status_code == 404
        # No feedback row must be inserted for a foreign query.
        mock_db.table.return_value.insert.assert_not_called()
    finally:
        app.dependency_overrides.clear()


def test_feedback_accepts_own_query(client):
    from taxflow.main import app

    fake_client = {"id": "client-1", "email": "a@b.com.au"}
    mock_db = MagicMock()
    mock_db.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = [
        {"id": "q1"}
    ]
    mock_db.table.return_value.insert.return_value.execute.return_value.data = [{"id": "fb1"}]

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


# --- Task C5: the stream path persists model/confidence/tokens/cache tokens ---


@pytest.mark.asyncio
async def test_stream_persists_metrics():
    import taxflow.routers.query as q

    fake_client = {"id": "client-1", "email": "a@b.com.au"}

    captured_update = {}
    mock_db = MagicMock()
    mock_db.table.return_value.insert.return_value.execute.return_value.data = [{"id": "query-1"}]

    def capture_update(payload):
        captured_update.update(payload)
        return mock_db.table.return_value

    mock_db.table.return_value.update.side_effect = capture_update

    async def fake_stream(question, client_id, embedding=None, client=None, session_id=None):
        yield {"type": "token", "text": "hello "}
        yield {
            "type": "final",
            "citations": [{"citation": "x"}],
            "answer": "hello world [1]",
            "confidence": 0.9,
            "model_used": "sonnet",
            "chunks_retrieved": 5,
            "input_tokens": 100,
            "output_tokens": 50,
            "cache_read_input_tokens": 40,
            "cache_creation_input_tokens": 10,
        }

    with patch.object(q, "get_supabase_client", return_value=mock_db), patch.object(
        q, "embed", new=AsyncMock(return_value=[0.0] * 1536)
    ), patch.object(q, "increment_usage", new=AsyncMock()), patch.object(
        q.agent, "run_stream", side_effect=fake_stream
    ), patch.object(
        q.verify_mod, "should_verify", return_value=False
    ), patch.object(
        q.answer_cache, "store_answer", new=AsyncMock()
    ), patch.object(
        q.answer_cache, "get_cached_answer", new=AsyncMock(return_value=None)
    ), patch.object(
        q.answer_cache, "count_prior_asks", new=AsyncMock(return_value=0)
    ):
        response = await q.stream_query(question="q", client=fake_client, _trial=fake_client)
        # Drain the SSE generator.
        chunks = [c async for c in response.body_iterator]

    assert captured_update["model_used"] == "sonnet"
    assert captured_update["confidence_score"] == 0.9
    assert captured_update["input_tokens"] == 100
    assert captured_update["output_tokens"] == 50
    assert captured_update["cache_read_input_tokens"] == 40
    assert captured_update["cache_creation_input_tokens"] == 10
    assert captured_update["wall_time_ms"] is not None
    assert any("verification" in c for c in chunks)


@pytest.mark.asyncio
async def test_stream_correction_swaps_metadata_and_emits_event():
    """Stream path: a corrective pass replaces the answer, emits a `correction`
    SSE event, and persists the corrective (Sonnet) metadata — not the streamed
    first-pass values (should-fix #1 + #2)."""
    import json

    import taxflow.routers.query as q

    fake_client = {"id": "client-1", "email": "a@b.com.au"}

    captured_update = {}
    store_calls = []
    mock_db = MagicMock()
    mock_db.table.return_value.insert.return_value.execute.return_value.data = [{"id": "query-1"}]

    def capture_update(payload):
        captured_update.update(payload)
        return mock_db.table.return_value

    mock_db.table.return_value.update.side_effect = capture_update

    async def fake_stream(question, client_id, embedding=None, client=None, session_id=None):
        yield {"type": "token", "text": "first pass "}
        yield {
            "type": "final",
            "citations": [{"citation": "x"}],
            "answer": "first pass answer [1]",
            "confidence": 0.3,
            "model_used": "haiku",
            "input_tokens": 100,
            "output_tokens": 50,
            "cache_read_input_tokens": 40,
            "cache_creation_input_tokens": 10,
        }

    corrected = {
        "answer": "Corrected answer [1]",
        "citations": [{"citation": "y"}],
        "confidence": 0.85,
        "model_used": "sonnet",
        "input_tokens": 300,
        "output_tokens": 120,
        "cache_read_input_tokens": 200,
        "cache_creation_input_tokens": 0,
    }
    verification = {"overall_status": "needs_correction", "issues": [{"severity": "critical"}]}

    async def store_answer(*args, **kwargs):
        store_calls.append(args)

    with patch.object(q, "get_supabase_client", return_value=mock_db), patch.object(
        q, "embed", new=AsyncMock(return_value=[0.0] * 1536)
    ), patch.object(q, "increment_usage", new=AsyncMock()), patch.object(
        q.agent, "run_stream", side_effect=fake_stream
    ), patch.object(
        q.verify_mod, "should_verify", return_value=True
    ), patch.object(
        q.verify_mod, "verify_model_for", return_value="haiku"
    ), patch.object(
        q.verify_mod, "needs_correction", return_value=True
    ), patch.object(
        q.verify_mod, "build_caveat", return_value="Caveat: review claim 1."
    ), patch.object(
        q.verifier, "run", new=AsyncMock(return_value=verification)
    ), patch.object(
        q.agent, "regenerate_with_feedback", new=AsyncMock(return_value=corrected)
    ), patch.object(
        q.answer_cache, "store_answer", new=AsyncMock(side_effect=store_answer)
    ), patch.object(
        q.answer_cache, "get_cached_answer", new=AsyncMock(return_value=None)
    ), patch.object(
        q.answer_cache, "count_prior_asks", new=AsyncMock(return_value=0)
    ):
        response = await q.stream_query(question="q", client=fake_client, _trial=fake_client)
        chunks = [c async for c in response.body_iterator]

    # Persisted metadata reflects the corrective (Sonnet) pass, not the first pass.
    assert captured_update["model_used"] == "sonnet"
    assert captured_update["confidence_score"] == 0.85
    assert captured_update["input_tokens"] == 300
    assert captured_update["output_tokens"] == 120
    assert captured_update["cache_read_input_tokens"] == 200
    assert "Corrected answer [1]" in captured_update["final_answer"]

    # A `correction` event carries the authoritative corrected answer + caveat.
    correction_chunks = [c for c in chunks if '"type": "correction"' in c]
    assert len(correction_chunks) == 1
    payload = json.loads(correction_chunks[0].removeprefix("data: ").strip())
    assert "Corrected answer [1]" in payload["answer"]
    assert payload["caveat"] == "Caveat: review claim 1."

    # A needs_correction answer must NEVER be cached (B3 _safe_to_cache gate).
    assert store_calls == []


@pytest.mark.asyncio
async def test_stream_cache_hit_skips_embed_and_generation():
    """Stream path: a cache hit must serve the stored answer WITHOUT calling the
    paid OpenAI embed or Anthropic generation, and emit cached: true (review #2)."""
    import json

    import taxflow.routers.query as q

    fake_client = {"id": "client-1", "email": "a@b.com.au"}
    mock_db = MagicMock()
    mock_db.table.return_value.insert.return_value.execute.return_value.data = [{"id": "cached-query-1"}]

    cached = {
        "answer": "Cached answer [1]",
        "citations": [{"citation": "x"}],
        "confidence": 0.9,
        "model_used": "haiku",
    }

    embed_mock = AsyncMock(return_value=[0.0] * 1536)
    run_stream_mock = MagicMock()

    with patch.object(q, "get_supabase_client", return_value=mock_db), patch.object(
        q, "embed", new=embed_mock
    ), patch.object(q, "increment_usage", new=AsyncMock()), patch.object(
        q.agent, "run_stream", new=run_stream_mock
    ), patch.object(
        q.answer_cache, "get_cached_answer", new=AsyncMock(return_value=cached)
    ):
        response = await q.stream_query(question="q", client=fake_client, _trial=fake_client)
        chunks = [c async for c in response.body_iterator]

    # No paid work on a cache hit.
    embed_mock.assert_not_awaited()
    run_stream_mock.assert_not_called()

    # The cached answer is streamed and the final event marks it cached.
    joined = "".join(chunks)
    assert "Cached answer [1]" in joined
    final_chunk = next(c for c in chunks if '"type": "final"' in c)
    payload = json.loads(final_chunk.removeprefix("data: ").strip())
    assert payload["cached"] is True
    assert payload["model_used"] == "cache"
    assert chunks[-1] == "data: [DONE]\n\n"
