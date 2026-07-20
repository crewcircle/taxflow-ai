"""Phase 1: annotations API ownership + validation tests.

Mirrors ``test_feedback_and_stream.py`` ownership pattern: a target owned by
another client must 404 with NO row written/returned, ``client_id`` is forced
from the auth context (a malicious body value is ignored), invalid enums 422,
and reply ``parent_id`` may not couple across clients or targets.
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


CLIENT = {"id": "client-1", "email": "a@b.com.au"}


def _valid_body(**overrides):
    body = {
        "target_type": "document",
        "target_id": "doc-1",
        "target_version": "abc123",
        "block_index": 0,
        "start_offset": 3,
        "end_offset": 9,
        "quoted_text": "$120,000",
        "author_kind": "reviewer",
        "body": "Confirm this ties to the ledger.",
    }
    body.update(overrides)
    return body


# --- ownership: foreign target -> 404, no repo write -------------------------


def test_get_rejects_foreign_document(client):
    mock_db = MagicMock()
    mock_db.documents.get_for_client.return_value = None
    _override(CLIENT, mock_db)
    try:
        resp = client.get("/annotations", params={"target_type": "document", "target_id": "d9"})
        assert resp.status_code == 404
        mock_db.annotations.list_for_target.assert_not_called()
    finally:
        app.dependency_overrides.clear()


def test_post_rejects_foreign_document(client):
    mock_db = MagicMock()
    mock_db.documents.get_for_client.return_value = None
    _override(CLIENT, mock_db)
    try:
        resp = client.post("/annotations", json=_valid_body(target_id="d9"))
        assert resp.status_code == 404
        mock_db.annotations.insert.assert_not_called()
    finally:
        app.dependency_overrides.clear()


def test_post_rejects_foreign_query_answer(client):
    mock_db = MagicMock()
    mock_db.queries.get_for_client.return_value = None
    _override(CLIENT, mock_db)
    try:
        resp = client.post(
            "/annotations", json=_valid_body(target_type="query_answer", target_id="q9")
        )
        assert resp.status_code == 404
        mock_db.annotations.insert.assert_not_called()
    finally:
        app.dependency_overrides.clear()


def test_patch_rejects_foreign_annotation(client):
    mock_db = MagicMock()
    mock_db.annotations.get_for_client.return_value = None
    _override(CLIENT, mock_db)
    try:
        resp = client.patch("/annotations/a9", json={"body": "x"})
        assert resp.status_code == 404
        mock_db.annotations.update.assert_not_called()
    finally:
        app.dependency_overrides.clear()


def test_delete_rejects_foreign_annotation(client):
    mock_db = MagicMock()
    mock_db.annotations.get_for_client.return_value = None
    _override(CLIENT, mock_db)
    try:
        resp = client.delete("/annotations/a9")
        assert resp.status_code == 404
        mock_db.annotations.delete.assert_not_called()
    finally:
        app.dependency_overrides.clear()


# --- happy path --------------------------------------------------------------


def test_get_returns_annotations_and_source_hash(client):
    mock_db = MagicMock()
    mock_db.documents.get_for_client.return_value = {"id": "doc-1", "content_md": "# Hi"}
    mock_db.annotations.list_for_target.return_value = [{"id": "a1"}]
    _override(CLIENT, mock_db)
    try:
        resp = client.get("/annotations", params={"target_type": "document", "target_id": "doc-1"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["annotations"] == [{"id": "a1"}]
        assert isinstance(data["source_hash"], str) and data["source_hash"]
        mock_db.annotations.list_for_target.assert_called_once_with("client-1", "document", "doc-1")
    finally:
        app.dependency_overrides.clear()


def test_post_creates_with_auth_client_id(client):
    mock_db = MagicMock()
    mock_db.documents.get_for_client.return_value = {"id": "doc-1", "content_md": "x"}
    mock_db.annotations.insert.return_value = {"id": "a1"}
    _override(CLIENT, mock_db)
    try:
        resp = client.post("/annotations", json=_valid_body())
        assert resp.status_code == 201
        inserted = mock_db.annotations.insert.call_args[0][0]
        assert inserted["client_id"] == "client-1"
    finally:
        app.dependency_overrides.clear()


def test_patch_sets_resolved_at(client):
    mock_db = MagicMock()
    mock_db.annotations.get_for_client.return_value = {"id": "a1", "client_id": "client-1"}
    mock_db.annotations.update.return_value = {"id": "a1", "resolved_at": "2026-07-20"}
    _override(CLIENT, mock_db)
    try:
        resp = client.patch("/annotations/a1", json={"resolved": True})
        assert resp.status_code == 200
        fields = mock_db.annotations.update.call_args[0][2]
        assert fields["resolved_at"] == "now()"
    finally:
        app.dependency_overrides.clear()


def test_delete_owned_annotation(client):
    mock_db = MagicMock()
    mock_db.annotations.get_for_client.return_value = {"id": "a1", "client_id": "client-1"}
    _override(CLIENT, mock_db)
    try:
        resp = client.delete("/annotations/a1")
        assert resp.status_code == 204
        mock_db.annotations.delete.assert_called_once_with("client-1", "a1")
    finally:
        app.dependency_overrides.clear()


# --- validation --------------------------------------------------------------


def test_post_rejects_invalid_target_type(client):
    mock_db = MagicMock()
    _override(CLIENT, mock_db)
    try:
        resp = client.post("/annotations", json=_valid_body(target_type="engagement_letter"))
        assert resp.status_code == 422
        mock_db.annotations.insert.assert_not_called()
    finally:
        app.dependency_overrides.clear()


def test_post_rejects_invalid_author_kind(client):
    mock_db = MagicMock()
    mock_db.documents.get_for_client.return_value = {"id": "doc-1", "content_md": "x"}
    _override(CLIENT, mock_db)
    try:
        resp = client.post("/annotations", json=_valid_body(author_kind="partner"))
        assert resp.status_code == 422
        mock_db.annotations.insert.assert_not_called()
    finally:
        app.dependency_overrides.clear()


def test_get_rejects_invalid_target_type(client):
    mock_db = MagicMock()
    _override(CLIENT, mock_db)
    try:
        resp = client.get("/annotations", params={"target_type": "nope", "target_id": "x"})
        assert resp.status_code == 422
    finally:
        app.dependency_overrides.clear()


# --- malicious client_id in body is ignored ----------------------------------


def test_post_ignores_client_id_in_body(client):
    mock_db = MagicMock()
    mock_db.documents.get_for_client.return_value = {"id": "doc-1", "content_md": "x"}
    mock_db.annotations.insert.return_value = {"id": "a1"}
    _override(CLIENT, mock_db)
    try:
        payload = _valid_body()
        payload["client_id"] = "client-999"  # attacker-supplied
        resp = client.post("/annotations", json=payload)
        assert resp.status_code == 201
        inserted = mock_db.annotations.insert.call_args[0][0]
        assert inserted["client_id"] == "client-1"
    finally:
        app.dependency_overrides.clear()


# --- reply validation: cross-client + cross-target parent_id -----------------


def test_post_reply_rejects_foreign_parent(client):
    mock_db = MagicMock()
    mock_db.documents.get_for_client.return_value = {"id": "doc-1", "content_md": "x"}
    # get_for_client is client-scoped, so a parent owned by another client
    # returns None -> the reply is rejected as if the parent does not exist.
    mock_db.annotations.get_for_client.return_value = None
    _override(CLIENT, mock_db)
    try:
        resp = client.post("/annotations", json=_valid_body(parent_id="foreign-parent"))
        assert resp.status_code == 404
        mock_db.annotations.insert.assert_not_called()
    finally:
        app.dependency_overrides.clear()


def test_post_reply_rejects_cross_target_parent(client):
    mock_db = MagicMock()
    mock_db.documents.get_for_client.return_value = {"id": "doc-1", "content_md": "x"}
    # Parent belongs to the same client but a DIFFERENT target.
    mock_db.annotations.get_for_client.return_value = {
        "id": "p1",
        "client_id": "client-1",
        "target_type": "document",
        "target_id": "doc-OTHER",
    }
    _override(CLIENT, mock_db)
    try:
        resp = client.post(
            "/annotations", json=_valid_body(target_id="doc-1", parent_id="p1")
        )
        assert resp.status_code == 404
        mock_db.annotations.insert.assert_not_called()
    finally:
        app.dependency_overrides.clear()


def test_post_reply_accepts_same_target_parent(client):
    mock_db = MagicMock()
    mock_db.documents.get_for_client.return_value = {"id": "doc-1", "content_md": "x"}
    mock_db.annotations.get_for_client.return_value = {
        "id": "p1",
        "client_id": "client-1",
        "target_type": "document",
        "target_id": "doc-1",
    }
    mock_db.annotations.insert.return_value = {"id": "a2", "parent_id": "p1"}
    _override(CLIENT, mock_db)
    try:
        resp = client.post(
            "/annotations", json=_valid_body(target_id="doc-1", parent_id="p1")
        )
        assert resp.status_code == 201
        inserted = mock_db.annotations.insert.call_args[0][0]
        assert inserted["parent_id"] == "p1"
    finally:
        app.dependency_overrides.clear()
