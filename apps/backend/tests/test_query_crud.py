"""Phase 3: route tests for query (soft-delete + edit), session delete,
notification delete, and firm-knowledge edit (re-embed).

Style mirrors ``test_feedback_and_stream.py`` — override auth + db with a fake
client and a ``MagicMock`` db. The firm-knowledge edit re-embeds, so ``embed``
is patched to avoid a real OpenAI call.
"""
from unittest.mock import AsyncMock, MagicMock, patch


def _override(fake_client, mock_db):
    from taxflow.main import app
    from taxflow.middleware.auth import get_current_client
    from taxflow.db import get_db

    app.dependency_overrides[get_current_client] = lambda: fake_client
    app.dependency_overrides[get_db] = lambda: mock_db


FAKE_CLIENT = {"id": "client-1", "email": "a@b.com.au", "business_name": "Firm"}


# --- DELETE /query/{id} (soft-delete + cache invalidation) --------------------


def test_delete_query_foreign_returns_404(client):
    from taxflow.main import app

    mock_db = MagicMock()
    mock_db.queries.get_for_client.return_value = None
    _override(FAKE_CLIENT, mock_db)
    try:
        resp = client.delete("/query/other-clients-query")
        assert resp.status_code == 404
        mock_db.queries.delete.assert_not_called()
    finally:
        app.dependency_overrides.clear()


def test_delete_own_query_soft_deletes_and_invalidates_cache(client):
    from taxflow.main import app

    mock_db = MagicMock()
    mock_db.queries.get_for_client.return_value = {"id": "q1", "question": "How do I?"}
    _override(FAKE_CLIENT, mock_db)
    try:
        resp = client.delete("/query/q1")
        assert resp.status_code == 200
        mock_db.queries.delete.assert_called_once_with("client-1", "q1")
        # Exact re-ask protection: the answer cache is invalidated for the
        # normalised question.
        mock_db.query_cache.invalidate.assert_called_once_with("client-1", "how do i")
    finally:
        app.dependency_overrides.clear()


# --- PATCH /query/{id} (edit answer, stale verification, cache invalidate) ----


def test_patch_query_foreign_returns_404(client):
    from taxflow.main import app

    mock_db = MagicMock()
    mock_db.queries.get_for_client.return_value = None
    _override(FAKE_CLIENT, mock_db)
    try:
        resp = client.patch("/query/other-q", json={"final_answer": "edited"})
        assert resp.status_code == 404
        mock_db.queries.update.assert_not_called()
    finally:
        app.dependency_overrides.clear()


def test_patch_query_empty_answer_returns_400(client):
    from taxflow.main import app

    mock_db = MagicMock()
    _override(FAKE_CLIENT, mock_db)
    try:
        resp = client.patch("/query/q1", json={"final_answer": "   "})
        assert resp.status_code == 400
        mock_db.queries.update.assert_not_called()
    finally:
        app.dependency_overrides.clear()


def test_patch_own_query_edits_answer_and_stales_verification(client):
    from taxflow.main import app

    mock_db = MagicMock()
    mock_db.queries.get_for_client.return_value = {
        "id": "q1",
        "question": "How do I?",
        "trace": {"verification": {"ran": True, "verdict": "supported"}, "retrieval": {}},
    }
    _override(FAKE_CLIENT, mock_db)
    try:
        resp = client.patch("/query/q1", json={"final_answer": "my edited answer"})
        assert resp.status_code == 200
        mock_db.queries.update.assert_called_once()
        args = mock_db.queries.update.call_args.args
        assert args[0] == "client-1"
        assert args[1] == "q1"
        fields = args[2]
        assert fields["final_answer"] == "my edited answer"
        assert fields["edited_at"] == "now()"
        # ALL verification/citation signals are staled — they described the
        # previous answer, not this hand-edited one.
        assert fields["verification_result"] is None
        assert fields["citation_valid"] is None
        assert fields["invalid_citations"] is None
        # The persisted trace's verification block is rewritten to "did not run"
        # (the "why this answer?" UI reads it independently), while other trace
        # sections are preserved.
        assert fields["trace"]["verification"] == {"ran": False}
        assert fields["trace"]["retrieval"] == {}
        mock_db.query_cache.invalidate.assert_called_once_with("client-1", "how do i")
    finally:
        app.dependency_overrides.clear()


# --- DELETE /query/sessions/{id} (soft-delete all queries in session) ---------


def test_delete_session_soft_deletes_all_and_invalidates_each(client):
    from taxflow.main import app

    mock_db = MagicMock()
    mock_db.queries.delete_session.return_value = True
    mock_db.queries.list_session_history.return_value = [
        {"question": "First question"},
        {"question": "Second question"},
    ]
    _override(FAKE_CLIENT, mock_db)
    try:
        resp = client.delete("/query/sessions/sess-1")
        assert resp.status_code == 200
        mock_db.queries.delete_session.assert_called_once_with("client-1", "sess-1")
        # Each affected question's cache entry is invalidated.
        called = {c.args for c in mock_db.query_cache.invalidate.call_args_list}
        assert ("client-1", "first question") in called
        assert ("client-1", "second question") in called
    finally:
        app.dependency_overrides.clear()


def test_delete_session_foreign_or_missing_returns_404(client):
    from taxflow.main import app

    mock_db = MagicMock()
    # No live rows for this client under this session -> delete_session reports
    # False, and the route must 404 rather than a false success.
    mock_db.queries.delete_session.return_value = False
    mock_db.queries.list_session_history.return_value = []
    _override(FAKE_CLIENT, mock_db)
    try:
        resp = client.delete("/query/sessions/foreign-session")
        assert resp.status_code == 404
        # Cache is not invalidated for a session that archived nothing.
        mock_db.query_cache.invalidate.assert_not_called()
    finally:
        app.dependency_overrides.clear()


# --- DELETE /notifications/{id} -----------------------------------------------


def test_delete_notification_scoped_by_client(client):
    from taxflow.main import app

    mock_db = MagicMock()
    mock_db.notifications.delete.return_value = True
    _override(FAKE_CLIENT, mock_db)
    try:
        resp = client.delete("/notifications/n1")
        assert resp.status_code == 200
        mock_db.notifications.delete.assert_called_once_with("client-1", "n1")
    finally:
        app.dependency_overrides.clear()


def test_delete_notification_foreign_or_missing_returns_404(client):
    from taxflow.main import app

    mock_db = MagicMock()
    mock_db.notifications.delete.return_value = False
    _override(FAKE_CLIENT, mock_db)
    try:
        resp = client.delete("/notifications/foreign")
        assert resp.status_code == 404
    finally:
        app.dependency_overrides.clear()


# --- PATCH /firm-knowledge/{id} (edit + re-embed) -----------------------------


def test_patch_firm_knowledge_foreign_returns_404(client):
    from taxflow.main import app

    mock_db = MagicMock()
    mock_db.firm_knowledge.get_for_client.return_value = None
    _override(FAKE_CLIENT, mock_db)
    try:
        with patch(
            "taxflow.routers.firm_knowledge.embed", new=AsyncMock(return_value=[0.1])
        ) as embed_mock:
            resp = client.patch("/firm-knowledge/other-note", json={"content": "x"})
        assert resp.status_code == 404
        mock_db.firm_knowledge.update.assert_not_called()
        # Foreign note: never spend an embedding call.
        embed_mock.assert_not_called()
    finally:
        app.dependency_overrides.clear()


def test_patch_firm_knowledge_empty_returns_400(client):
    from taxflow.main import app

    mock_db = MagicMock()
    _override(FAKE_CLIENT, mock_db)
    try:
        with patch(
            "taxflow.routers.firm_knowledge.embed", new=AsyncMock(return_value=[0.1])
        ):
            resp = client.patch("/firm-knowledge/fk1", json={"content": "  "})
        assert resp.status_code == 400
        mock_db.firm_knowledge.update.assert_not_called()
    finally:
        app.dependency_overrides.clear()


def test_patch_own_firm_knowledge_reembeds_and_updates(client):
    from taxflow.main import app

    mock_db = MagicMock()
    mock_db.firm_knowledge.get_for_client.return_value = {"id": "fk1"}
    mock_db.firm_knowledge.update.return_value = {"id": "fk1", "content": "edited"}
    _override(FAKE_CLIENT, mock_db)
    try:
        with patch(
            "taxflow.routers.firm_knowledge.embed",
            new=AsyncMock(return_value=[0.1, 0.2]),
        ) as embed_mock:
            resp = client.patch("/firm-knowledge/fk1", json={"content": "edited"})
        assert resp.status_code == 200
        # Re-embed ran on the edited content, then the repo update was called
        # with the fresh embedding.
        embed_mock.assert_awaited_once_with("edited")
        mock_db.firm_knowledge.update.assert_called_once_with(
            "client-1", "fk1", "edited", [0.1, 0.2]
        )
    finally:
        app.dependency_overrides.clear()


# --- DELETE /firm-knowledge/{id} ----------------------------------------------


def test_delete_firm_knowledge_scoped_by_client(client):
    from taxflow.main import app

    mock_db = MagicMock()
    mock_db.firm_knowledge.delete.return_value = True
    _override(FAKE_CLIENT, mock_db)
    try:
        resp = client.delete("/firm-knowledge/fk1")
        assert resp.status_code == 200
        mock_db.firm_knowledge.delete.assert_called_once_with("client-1", "fk1")
    finally:
        app.dependency_overrides.clear()


def test_delete_firm_knowledge_foreign_or_missing_returns_404(client):
    from taxflow.main import app

    mock_db = MagicMock()
    # Nothing owned was deleted (missing / foreign-owned) -> 404, not a false
    # success.
    mock_db.firm_knowledge.delete.return_value = False
    _override(FAKE_CLIENT, mock_db)
    try:
        resp = client.delete("/firm-knowledge/foreign-note")
        assert resp.status_code == 404
    finally:
        app.dependency_overrides.clear()
