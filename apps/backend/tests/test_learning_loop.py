"""Task C5: approval-gated learning loop.

Covers:
  - a thumbs-UP creates a PENDING knowledge_suggestion (deduped per query — a
    second thumbs-up on the same query does NOT create another);
  - approve embeds into firm_knowledge + records firm_knowledge_id + status;
  - reject sets status only (nothing written to firm_knowledge);
  - cross-client access to a suggestion -> 404;
  - route ordering: GET /firm-knowledge/suggestions?status=pending resolves to
    the suggestions handler, NOT get_firm_knowledge with knowledge_id="suggestions".
"""
from unittest.mock import AsyncMock, MagicMock, patch


def _override(fake_client, mock_db):
    from taxflow.main import app
    from taxflow.db import get_db
    from taxflow.middleware.auth import get_current_client

    app.dependency_overrides[get_current_client] = lambda: fake_client
    app.dependency_overrides[get_db] = lambda: mock_db


# --- thumbs-up creates a pending suggestion (deduped per query) --------------


def test_thumbs_up_creates_pending_suggestion(client):
    from taxflow.main import app

    fake_client = {"id": "client-1", "email": "a@b.com.au"}
    mock_db = MagicMock()
    mock_db.queries.get_for_client.return_value = {
        "id": "q1",
        "question": "How does Division 7A apply?",
        "final_answer": "It applies to loans [1].",
    }
    mock_db.query_feedback.insert.return_value = {"id": "fb1"}
    mock_db.knowledge_suggestions.exists_for_query.return_value = False

    _override(fake_client, mock_db)
    try:
        resp = client.post("/query/q1/feedback", json={"rating": "up"})
        assert resp.status_code == 200

        mock_db.knowledge_suggestions.exists_for_query.assert_called_once_with(
            "client-1", "q1"
        )
        mock_db.knowledge_suggestions.insert.assert_called_once()
        row = mock_db.knowledge_suggestions.insert.call_args.args[0]
        assert row["client_id"] == "client-1"
        assert row["source_query_id"] == "q1"
        assert row["title"] == "How does Division 7A apply?"
        assert row["content"] == "It applies to loans [1]."
        assert row["reason"] == "thumbs_up"
    finally:
        app.dependency_overrides.clear()


def test_second_thumbs_up_does_not_create_duplicate(client):
    from taxflow.main import app

    fake_client = {"id": "client-1", "email": "a@b.com.au"}
    mock_db = MagicMock()
    mock_db.queries.get_for_client.return_value = {
        "id": "q1",
        "question": "Q?",
        "final_answer": "A [1].",
    }
    mock_db.query_feedback.insert.return_value = {"id": "fb2"}
    # A pending suggestion already exists for this query.
    mock_db.knowledge_suggestions.exists_for_query.return_value = True

    _override(fake_client, mock_db)
    try:
        resp = client.post("/query/q1/feedback", json={"rating": "up"})
        assert resp.status_code == 200
        mock_db.knowledge_suggestions.exists_for_query.assert_called_once_with(
            "client-1", "q1"
        )
        mock_db.knowledge_suggestions.insert.assert_not_called()
    finally:
        app.dependency_overrides.clear()


def test_thumbs_down_does_not_create_suggestion(client):
    from taxflow.main import app

    fake_client = {"id": "client-1", "email": "a@b.com.au"}
    mock_db = MagicMock()
    mock_db.queries.get_for_client.return_value = {
        "id": "q1", "question": "Q?", "final_answer": "A."
    }
    mock_db.query_feedback.insert.return_value = {"id": "fb3"}

    _override(fake_client, mock_db)
    try:
        resp = client.post("/query/q1/feedback", json={"rating": "down"})
        assert resp.status_code == 200
        mock_db.knowledge_suggestions.insert.assert_not_called()
    finally:
        app.dependency_overrides.clear()


# --- approve: embed into firm_knowledge + record decision --------------------


def test_approve_embeds_into_firm_knowledge(client):
    from taxflow.main import app
    from taxflow.routers import firm_knowledge as fk_router

    fake_client = {"id": "client-1", "email": "a@b.com.au", "business_name": "Acme"}
    mock_db = MagicMock()
    mock_db.knowledge_suggestions.get_for_client.return_value = {
        "id": "s1",
        "title": "Div 7A note",
        "content": "Some approved content.",
        "status": "pending",
    }
    # The atomic approve claims the suggestion + inserts firm_knowledge in one txn.
    mock_db.knowledge_suggestions.approve.return_value = {
        "id": "s1", "status": "approved", "firm_knowledge_id": "fk-9"
    }

    _override(fake_client, mock_db)
    embedding = [0.1] * 1536
    try:
        with patch.object(fk_router, "embed", new=AsyncMock(return_value=embedding)) as mock_embed:
            resp = client.post("/firm-knowledge/suggestions/s1/approve")
        assert resp.status_code == 200
        assert resp.json()["firm_knowledge_id"] == "fk-9"

        mock_embed.assert_awaited_once_with("Some approved content.")
        # Approval goes through the single atomic repo method (claim + insert +
        # stamp), NOT a bare firm_knowledge.insert + set_decision.
        mock_db.knowledge_suggestions.approve.assert_called_once()
        args = mock_db.knowledge_suggestions.approve.call_args.args
        assert args[0] == "client-1"
        assert args[1] == "s1"
        fk_row = args[2]
        assert fk_row["client_id"] == "client-1"
        assert fk_row["file_name"] == "Div 7A note"
        assert fk_row["file_type"] == "note"
        assert fk_row["content"] == "Some approved content."
        assert fk_row["embedding"] == embedding
        assert args[3] == "Acme"  # decided_by
    finally:
        app.dependency_overrides.clear()


def test_approve_cross_client_404(client):
    from taxflow.main import app
    from taxflow.routers import firm_knowledge as fk_router

    fake_client = {"id": "client-1", "email": "a@b.com.au"}
    mock_db = MagicMock()
    # Another client's suggestion -> repo scoped by client_id returns None.
    mock_db.knowledge_suggestions.get_for_client.return_value = None

    _override(fake_client, mock_db)
    try:
        with patch.object(fk_router, "embed", new=AsyncMock(return_value=[0.1] * 1536)):
            resp = client.post("/firm-knowledge/suggestions/other/approve")
        assert resp.status_code == 404
        mock_db.knowledge_suggestions.approve.assert_not_called()
    finally:
        app.dependency_overrides.clear()


def test_approve_already_decided_returns_409_no_insert(client):
    """Approving an already-approved/rejected suggestion is a 409 and never
    embeds or writes a second firm_knowledge row."""
    from taxflow.main import app
    from taxflow.routers import firm_knowledge as fk_router

    fake_client = {"id": "client-1", "email": "a@b.com.au", "business_name": "Acme"}
    for decided_status in ("approved", "rejected"):
        mock_db = MagicMock()
        mock_db.knowledge_suggestions.get_for_client.return_value = {
            "id": "s1", "title": "t", "content": "c", "status": decided_status
        }
        _override(fake_client, mock_db)
        try:
            with patch.object(fk_router, "embed", new=AsyncMock(return_value=[0.1] * 1536)) as mock_embed:
                resp = client.post("/firm-knowledge/suggestions/s1/approve")
            assert resp.status_code == 409
            mock_embed.assert_not_awaited()
            mock_db.knowledge_suggestions.approve.assert_not_called()
        finally:
            app.dependency_overrides.clear()


def test_concurrent_double_approve_inserts_once(client):
    """A concurrent double-approve (both pass the read-time pending check, but the
    atomic claim only succeeds for one) results in exactly ONE firm_knowledge
    insert — the loser gets a 409 because repo.approve returns None."""
    from taxflow.main import app
    from taxflow.routers import firm_knowledge as fk_router

    fake_client = {"id": "client-1", "email": "a@b.com.au", "business_name": "Acme"}
    mock_db = MagicMock()
    mock_db.knowledge_suggestions.get_for_client.return_value = {
        "id": "s1", "title": "t", "content": "c", "status": "pending"
    }
    # First atomic approve claims + inserts; the second matches 0 pending rows
    # (already claimed) so it returns None and inserts nothing.
    mock_db.knowledge_suggestions.approve.side_effect = [
        {"id": "s1", "status": "approved", "firm_knowledge_id": "fk-9"},
        None,
    ]

    _override(fake_client, mock_db)
    try:
        with patch.object(fk_router, "embed", new=AsyncMock(return_value=[0.1] * 1536)):
            first = client.post("/firm-knowledge/suggestions/s1/approve")
            second = client.post("/firm-knowledge/suggestions/s1/approve")
        assert first.status_code == 200
        assert second.status_code == 409
        # The atomic repo method (which does the single firm_knowledge insert)
        # ran twice, but only claimed once — the second returned None.
        assert mock_db.knowledge_suggestions.approve.call_count == 2
    finally:
        app.dependency_overrides.clear()


# --- reject: status only -----------------------------------------------------


def test_reject_sets_status_only(client):
    from taxflow.main import app

    fake_client = {"id": "client-1", "email": "a@b.com.au"}
    mock_db = MagicMock()
    mock_db.knowledge_suggestions.get_for_client.return_value = {
        "id": "s1", "title": "t", "content": "c", "status": "pending"
    }
    mock_db.knowledge_suggestions.set_decision.return_value = {
        "id": "s1", "status": "rejected"
    }

    _override(fake_client, mock_db)
    try:
        resp = client.post("/firm-knowledge/suggestions/s1/reject")
        assert resp.status_code == 200
        # Nothing written to the authoritative store.
        mock_db.firm_knowledge.insert.assert_not_called()
        args = mock_db.knowledge_suggestions.set_decision.call_args.args
        assert args[2] == "rejected"
    finally:
        app.dependency_overrides.clear()


def test_reject_cross_client_404(client):
    from taxflow.main import app

    fake_client = {"id": "client-1", "email": "a@b.com.au"}
    mock_db = MagicMock()
    mock_db.knowledge_suggestions.get_for_client.return_value = None

    _override(fake_client, mock_db)
    try:
        resp = client.post("/firm-knowledge/suggestions/other/reject")
        assert resp.status_code == 404
        mock_db.knowledge_suggestions.set_decision.assert_not_called()
    finally:
        app.dependency_overrides.clear()


def test_reject_already_decided_returns_409(client):
    from taxflow.main import app

    fake_client = {"id": "client-1", "email": "a@b.com.au"}
    mock_db = MagicMock()
    mock_db.knowledge_suggestions.get_for_client.return_value = {
        "id": "s1", "title": "t", "content": "c", "status": "approved"
    }

    _override(fake_client, mock_db)
    try:
        resp = client.post("/firm-knowledge/suggestions/s1/reject")
        assert resp.status_code == 409
        mock_db.knowledge_suggestions.set_decision.assert_not_called()
    finally:
        app.dependency_overrides.clear()


# --- POST /suggestions: create (promote button) ------------------------------


def test_create_suggestion_creates_pending(client):
    from taxflow.main import app

    fake_client = {"id": "client-1", "email": "a@b.com.au"}
    mock_db = MagicMock()
    mock_db.queries.get_for_client.return_value = {"id": "q1"}
    mock_db.knowledge_suggestions.exists_for_query.return_value = False
    mock_db.knowledge_suggestions.insert.return_value = {"id": "s1", "status": "pending"}

    _override(fake_client, mock_db)
    try:
        resp = client.post(
            "/firm-knowledge/suggestions",
            json={"title": "Promoted", "content": "answer body", "source_query_id": "q1"},
        )
        assert resp.status_code == 200
        assert resp.json()["id"] == "s1"
        row = mock_db.knowledge_suggestions.insert.call_args.args[0]
        assert row["client_id"] == "client-1"
        assert row["title"] == "Promoted"
        assert row["content"] == "answer body"
        assert row["source_query_id"] == "q1"
        assert row["reason"] == "manual_promote"
    finally:
        app.dependency_overrides.clear()


def test_create_suggestion_without_query_id(client):
    from taxflow.main import app

    fake_client = {"id": "client-1", "email": "a@b.com.au"}
    mock_db = MagicMock()
    mock_db.knowledge_suggestions.insert.return_value = {"id": "s2", "status": "pending"}

    _override(fake_client, mock_db)
    try:
        resp = client.post(
            "/firm-knowledge/suggestions",
            json={"title": "Note", "content": "free text"},
        )
        assert resp.status_code == 200
        # No source_query_id → no ownership check, no dedupe query.
        mock_db.queries.get_for_client.assert_not_called()
        mock_db.knowledge_suggestions.exists_for_query.assert_not_called()
        row = mock_db.knowledge_suggestions.insert.call_args.args[0]
        assert row["source_query_id"] is None
    finally:
        app.dependency_overrides.clear()


def test_create_suggestion_dedupes_existing_pending(client):
    from taxflow.main import app

    fake_client = {"id": "client-1", "email": "a@b.com.au"}
    mock_db = MagicMock()
    mock_db.queries.get_for_client.return_value = {"id": "q1"}
    mock_db.knowledge_suggestions.exists_for_query.return_value = True
    mock_db.knowledge_suggestions.list_for_client.return_value = [
        {"id": "existing", "status": "pending", "source_query_id": "q1"},
    ]

    _override(fake_client, mock_db)
    try:
        resp = client.post(
            "/firm-knowledge/suggestions",
            json={"title": "Promoted", "content": "body", "source_query_id": "q1"},
        )
        assert resp.status_code == 200
        # Returns the existing pending suggestion; no second insert.
        assert resp.json()["id"] == "existing"
        mock_db.knowledge_suggestions.insert.assert_not_called()
    finally:
        app.dependency_overrides.clear()


def test_create_suggestion_cross_client_query_404(client):
    from taxflow.main import app

    fake_client = {"id": "client-1", "email": "a@b.com.au"}
    mock_db = MagicMock()
    # source_query_id belongs to another client → scoped get returns None.
    mock_db.queries.get_for_client.return_value = None

    _override(fake_client, mock_db)
    try:
        resp = client.post(
            "/firm-knowledge/suggestions",
            json={"title": "t", "content": "c", "source_query_id": "other-q"},
        )
        assert resp.status_code == 404
        mock_db.knowledge_suggestions.insert.assert_not_called()
    finally:
        app.dependency_overrides.clear()


def test_create_suggestion_route_resolves_to_create_handler(client):
    """POST /firm-knowledge/suggestions MUST hit create_suggestion, NOT be
    captured by a wildcard path."""
    from taxflow.main import app

    fake_client = {"id": "client-1", "email": "a@b.com.au"}
    mock_db = MagicMock()
    mock_db.knowledge_suggestions.insert.return_value = {"id": "s9", "status": "pending"}

    _override(fake_client, mock_db)
    try:
        resp = client.post(
            "/firm-knowledge/suggestions", json={"title": "t", "content": "c"}
        )
        assert resp.status_code == 200
        mock_db.knowledge_suggestions.insert.assert_called_once()
    finally:
        app.dependency_overrides.clear()


# --- route ordering: /suggestions resolves to the suggestions handler --------


def test_suggestions_route_resolves_to_suggestions_handler(client):
    """GET /firm-knowledge/suggestions?status=pending MUST hit list_suggestions,
    NOT get_firm_knowledge with knowledge_id="suggestions"."""
    from taxflow.main import app

    fake_client = {"id": "client-1", "email": "a@b.com.au"}
    mock_db = MagicMock()
    mock_db.knowledge_suggestions.list_for_client.return_value = [
        {"id": "s1", "status": "pending"}
    ]

    _override(fake_client, mock_db)
    try:
        resp = client.get("/firm-knowledge/suggestions?status=pending")
        assert resp.status_code == 200
        # The suggestions handler ran, scoped by client + status filter...
        mock_db.knowledge_suggestions.list_for_client.assert_called_once_with(
            "client-1", "pending"
        )
        # ...and the wildcard /{knowledge_id} handler did NOT.
        mock_db.firm_knowledge.get_for_client.assert_not_called()
        assert resp.json() == [{"id": "s1", "status": "pending"}]
    finally:
        app.dependency_overrides.clear()
