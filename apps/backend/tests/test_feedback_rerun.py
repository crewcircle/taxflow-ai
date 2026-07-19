"""Task C2: feedback-triggered async re-research enqueue (submit_feedback)."""
from unittest.mock import MagicMock


def _override(fake_client, mock_db):
    from taxflow.main import app
    from taxflow.middleware.auth import get_current_client
    from taxflow.db import get_db

    app.dependency_overrides[get_current_client] = lambda: fake_client
    app.dependency_overrides[get_db] = lambda: mock_db


def _base_db():
    mock_db = MagicMock()
    mock_db.queries.get_for_client.return_value = {"id": "q1", "final_answer": "orig answer"}
    mock_db.query_feedback.insert.return_value = {"id": "fb1"}
    return mock_db


def test_down_with_note_enqueues_and_sets_pending(client):
    from taxflow.main import app

    fake_client = {"id": "client-1", "email": "a@b.com.au"}
    mock_db = _base_db()
    # Not a duplicate -> enqueue returns a row.
    mock_db.re_research_jobs.enqueue.return_value = {"id": "job-1"}

    _override(fake_client, mock_db)
    try:
        resp = client.post(
            "/query/q1/feedback", json={"rating": "down", "note": "wrong section 8-1"}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["re_research_enqueued"] is True

        # Enqueued with the snapshotted feedback_note + original_answer.
        mock_db.re_research_jobs.enqueue.assert_called_once()
        enq = mock_db.re_research_jobs.enqueue.call_args.args[0]
        assert enq["client_id"] == "client-1"
        assert enq["query_id"] == "q1"
        assert enq["feedback_id"] == "fb1"
        assert enq["feedback_note"] == "wrong section 8-1"
        assert enq["original_answer"] == "orig answer"

        # Query flagged pending so the sidebar badge can render.
        mock_db.queries.set_re_research_status.assert_called_once_with(
            "client-1", "q1", "pending"
        )
    finally:
        app.dependency_overrides.clear()


def test_down_without_note_not_enqueued(client):
    from taxflow.main import app

    fake_client = {"id": "client-1", "email": "a@b.com.au"}
    mock_db = _base_db()

    _override(fake_client, mock_db)
    try:
        resp = client.post("/query/q1/feedback", json={"rating": "down"})
        assert resp.status_code == 200
        assert resp.json()["re_research_enqueued"] is False
        mock_db.re_research_jobs.enqueue.assert_not_called()
        mock_db.queries.set_re_research_status.assert_not_called()
    finally:
        app.dependency_overrides.clear()


def test_down_with_blank_note_not_enqueued(client):
    from taxflow.main import app

    fake_client = {"id": "client-1", "email": "a@b.com.au"}
    mock_db = _base_db()

    _override(fake_client, mock_db)
    try:
        resp = client.post("/query/q1/feedback", json={"rating": "down", "note": "   "})
        assert resp.status_code == 200
        assert resp.json()["re_research_enqueued"] is False
        mock_db.re_research_jobs.enqueue.assert_not_called()
    finally:
        app.dependency_overrides.clear()


def test_up_not_enqueued(client):
    from taxflow.main import app

    fake_client = {"id": "client-1", "email": "a@b.com.au"}
    mock_db = _base_db()

    _override(fake_client, mock_db)
    try:
        resp = client.post("/query/q1/feedback", json={"rating": "up", "note": "great"})
        assert resp.status_code == 200
        assert resp.json()["re_research_enqueued"] is False
        mock_db.re_research_jobs.enqueue.assert_not_called()
        mock_db.queries.set_re_research_status.assert_not_called()
    finally:
        app.dependency_overrides.clear()


def test_duplicate_feedback_not_re_enqueued(client):
    from taxflow.main import app

    fake_client = {"id": "client-1", "email": "a@b.com.au"}
    mock_db = _base_db()
    # Duplicate feedback -> ON CONFLICT DO NOTHING -> enqueue returns None.
    mock_db.re_research_jobs.enqueue.return_value = None

    _override(fake_client, mock_db)
    try:
        resp = client.post(
            "/query/q1/feedback", json={"rating": "down", "note": "same issue"}
        )
        assert resp.status_code == 200
        assert resp.json()["re_research_enqueued"] is False
        # enqueue was attempted, but the dup returned None so no status flip.
        mock_db.re_research_jobs.enqueue.assert_called_once()
        mock_db.queries.set_re_research_status.assert_not_called()
    finally:
        app.dependency_overrides.clear()
