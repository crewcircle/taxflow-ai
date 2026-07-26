"""Regulatory alerts: global feed + server-side per-user 'seen' cursor.

Business audit P2 (Persona 3): the regulatory feed's "seen" marker used to
live in per-browser localStorage while every other notification kind already
had server-side read state - these cover the two new /seen endpoints that
move it onto users.regulatory_alerts_seen_at.
"""
from unittest.mock import MagicMock


def _override(fake_client, mock_db):
    from taxflow.main import app
    from taxflow.db import get_db
    from taxflow.middleware.auth import get_current_client

    app.dependency_overrides[get_current_client] = lambda: fake_client
    app.dependency_overrides[get_db] = lambda: mock_db


def test_get_seen_returns_current_cursor(client):
    from taxflow.main import app

    fake_client = {"id": "client-1", "user_id": "user-1", "regulatory_alerts_seen_at": "2026-01-01T00:00:00Z"}
    mock_db = MagicMock()
    _override(fake_client, mock_db)
    try:
        resp = client.get("/regulatory-alerts/seen")
        assert resp.status_code == 200
        assert resp.json() == {"seen_at": "2026-01-01T00:00:00Z"}
    finally:
        app.dependency_overrides.clear()


def test_get_seen_null_when_never_seen(client):
    from taxflow.main import app

    fake_client = {"id": "client-1", "user_id": "user-1"}
    mock_db = MagicMock()
    _override(fake_client, mock_db)
    try:
        resp = client.get("/regulatory-alerts/seen")
        assert resp.status_code == 200
        assert resp.json() == {"seen_at": None}
    finally:
        app.dependency_overrides.clear()


def test_post_seen_marks_current_user(client):
    from taxflow.main import app

    fake_client = {"id": "client-1", "user_id": "user-1"}
    mock_db = MagicMock()
    _override(fake_client, mock_db)
    try:
        resp = client.post("/regulatory-alerts/seen")
        assert resp.status_code == 200
        mock_db.users.mark_regulatory_alerts_seen.assert_called_once_with("user-1")
    finally:
        app.dependency_overrides.clear()
