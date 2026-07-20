"""Phase 1: GET /documents/{id} returns content_md for an owned doc, 404 foreign.

The in-app viewer reads the body via this endpoint; it must be client_id-scoped
exactly like the download route (both call ``db.documents.get_for_client``).
"""
from unittest.mock import MagicMock

from taxflow.main import app
from taxflow.middleware.auth import get_current_client
from taxflow.middleware.trial_gate import check_trial_gate
from taxflow.db import get_db


def _override(fake_client, mock_db):
    app.dependency_overrides[get_current_client] = lambda: fake_client
    app.dependency_overrides[check_trial_gate] = lambda: fake_client
    app.dependency_overrides[get_db] = lambda: mock_db


CLIENT = {"id": "client-1", "email": "a@b.com.au", "business_name": "Meridian"}


def test_get_document_returns_content_for_owned_doc(client):
    mock_db = MagicMock()
    mock_db.documents.get_for_client.return_value = {
        "id": "doc-1",
        "title": "Div 7A memo",
        "content_md": "# Summary\n\nBody text.",
        "document_type": "advice_memo",
    }
    _override(CLIENT, mock_db)
    try:
        resp = client.get("/documents/doc-1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["content_md"] == "# Summary\n\nBody text."
        assert data["title"] == "Div 7A memo"
        mock_db.documents.get_for_client.assert_called_once_with("client-1", "doc-1")
    finally:
        app.dependency_overrides.clear()


def test_get_document_404_for_foreign_doc(client):
    mock_db = MagicMock()
    mock_db.documents.get_for_client.return_value = None
    _override(CLIENT, mock_db)
    try:
        resp = client.get("/documents/doc-9")
        assert resp.status_code == 404
    finally:
        app.dependency_overrides.clear()
