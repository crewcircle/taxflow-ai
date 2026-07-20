"""Phase 3: route tests for document + ATO CRUD (delete/edit).

Style mirrors ``test_feedback_and_stream.py``: override the auth + db
dependencies with a fake client and a ``MagicMock`` db so no real DB/LLM is
touched. Covers ownership-404 (get_for_client -> None), happy-path, empty-edit
400, and the FK 409 on delete.
"""
from unittest.mock import MagicMock

import psycopg2


def _override(fake_client, mock_db):
    from taxflow.main import app
    from taxflow.middleware.auth import get_current_client
    from taxflow.db import get_db

    app.dependency_overrides[get_current_client] = lambda: fake_client
    app.dependency_overrides[get_db] = lambda: mock_db


FAKE_CLIENT = {"id": "client-1", "email": "a@b.com.au", "business_name": "Firm"}


# --- DELETE /documents/{id} ---------------------------------------------------


def test_delete_document_foreign_returns_404(client):
    from taxflow.main import app

    mock_db = MagicMock()
    mock_db.documents.get_for_client.return_value = None
    _override(FAKE_CLIENT, mock_db)
    try:
        resp = client.delete("/documents/other-clients-doc")
        assert resp.status_code == 404
        mock_db.documents.delete.assert_not_called()
    finally:
        app.dependency_overrides.clear()


def test_delete_own_document_returns_200(client):
    from taxflow.main import app

    mock_db = MagicMock()
    mock_db.documents.get_for_client.return_value = {"id": "d1", "client_id": "client-1"}
    _override(FAKE_CLIENT, mock_db)
    try:
        resp = client.delete("/documents/d1")
        assert resp.status_code == 200
        mock_db.documents.delete.assert_called_once_with("client-1", "d1")
    finally:
        app.dependency_overrides.clear()


def test_delete_document_fk_referenced_returns_409(client):
    from taxflow.main import app

    mock_db = MagicMock()
    mock_db.documents.get_for_client.return_value = {"id": "d1"}
    mock_db.documents.delete.side_effect = psycopg2.IntegrityError("FK violation")
    _override(FAKE_CLIENT, mock_db)
    try:
        resp = client.delete("/documents/d1")
        assert resp.status_code == 409
    finally:
        app.dependency_overrides.clear()


# --- PATCH /documents/{id} ----------------------------------------------------


def test_patch_document_foreign_returns_404(client):
    from taxflow.main import app

    mock_db = MagicMock()
    mock_db.documents.get_for_client.return_value = None
    _override(FAKE_CLIENT, mock_db)
    try:
        resp = client.patch("/documents/other-doc", json={"content_md": "new"})
        assert resp.status_code == 404
        mock_db.documents.update.assert_not_called()
    finally:
        app.dependency_overrides.clear()


def test_patch_document_empty_body_returns_400(client):
    from taxflow.main import app

    mock_db = MagicMock()
    mock_db.documents.get_for_client.return_value = {"id": "d1"}
    _override(FAKE_CLIENT, mock_db)
    try:
        resp = client.patch("/documents/d1", json={})
        assert resp.status_code == 400
        mock_db.documents.update.assert_not_called()
    finally:
        app.dependency_overrides.clear()


def test_patch_own_document_updates_content(client):
    from taxflow.main import app

    mock_db = MagicMock()
    mock_db.documents.get_for_client.return_value = {"id": "d1"}
    mock_db.documents.update.return_value = {
        "id": "d1",
        "content_md": "new",
        "edited_at": "2026-07-20T00:00:00Z",
    }
    _override(FAKE_CLIENT, mock_db)
    try:
        resp = client.patch("/documents/d1", json={"content_md": "new", "title": "T"})
        assert resp.status_code == 200
        mock_db.documents.update.assert_called_once()
        args = mock_db.documents.update.call_args.args
        assert args[0] == "client-1"
        assert args[1] == "d1"
        assert args[2] == {"content_md": "new", "title": "T"}
        assert resp.json()["edited_at"] == "2026-07-20T00:00:00Z"
    finally:
        app.dependency_overrides.clear()


# --- ATO response (documents table, document_type='ato_response') -------------


def test_delete_ato_wrong_type_returns_404(client):
    from taxflow.main import app

    mock_db = MagicMock()
    # A real document, but NOT an ato_response -> ATO route must 404.
    mock_db.documents.get_for_client.return_value = {
        "id": "d1",
        "document_type": "advice_memo",
    }
    _override(FAKE_CLIENT, mock_db)
    try:
        resp = client.delete("/ato-response/d1")
        assert resp.status_code == 404
        mock_db.documents.delete.assert_not_called()
    finally:
        app.dependency_overrides.clear()


def test_delete_own_ato_returns_200(client):
    from taxflow.main import app

    mock_db = MagicMock()
    mock_db.documents.get_for_client.return_value = {
        "id": "d1",
        "document_type": "ato_response",
    }
    _override(FAKE_CLIENT, mock_db)
    try:
        resp = client.delete("/ato-response/d1")
        assert resp.status_code == 200
        mock_db.documents.delete.assert_called_once_with("client-1", "d1")
    finally:
        app.dependency_overrides.clear()


def test_patch_ato_empty_body_returns_400(client):
    from taxflow.main import app

    mock_db = MagicMock()
    mock_db.documents.get_for_client.return_value = {
        "id": "d1",
        "document_type": "ato_response",
    }
    _override(FAKE_CLIENT, mock_db)
    try:
        resp = client.patch("/ato-response/d1", json={})
        assert resp.status_code == 400
        mock_db.documents.update.assert_not_called()
    finally:
        app.dependency_overrides.clear()
