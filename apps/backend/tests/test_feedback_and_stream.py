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
