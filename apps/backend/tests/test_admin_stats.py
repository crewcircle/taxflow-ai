"""Task 2b: /admin/stats endpoint + admin-token guard + window parsing.

The admin endpoints are operator-global (NOT client-scoped): gated by the shared
``X-Admin-Token`` secret rather than ``get_current_client``. We override
``get_db`` with a MagicMock so no real DB is touched, and patch
``settings.ADMIN_API_TOKEN`` to toggle the feature on/off.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from taxflow.routers.admin import parse_window


# --- admin-token guard (Decision #2484) --------------------------------------


def _override_db(mock_db):
    from taxflow.main import app
    from taxflow.db import get_db

    app.dependency_overrides[get_db] = lambda: mock_db


def _clear_overrides():
    from taxflow.main import app

    app.dependency_overrides.clear()


def test_stats_404_when_token_unset(client):
    mock_db = MagicMock()
    _override_db(mock_db)
    try:
        with patch("taxflow.middleware.admin.settings.ADMIN_API_TOKEN", ""):
            resp = client.get("/admin/stats")
        assert resp.status_code == 404
        mock_db.queries.stats.assert_not_called()
    finally:
        _clear_overrides()


def test_stats_401_when_token_missing(client):
    mock_db = MagicMock()
    _override_db(mock_db)
    try:
        with patch("taxflow.middleware.admin.settings.ADMIN_API_TOKEN", "s3cret"):
            resp = client.get("/admin/stats")  # no X-Admin-Token header
        assert resp.status_code == 401
        mock_db.queries.stats.assert_not_called()
    finally:
        _clear_overrides()


def test_stats_401_when_token_mismatch(client):
    mock_db = MagicMock()
    _override_db(mock_db)
    try:
        with patch("taxflow.middleware.admin.settings.ADMIN_API_TOKEN", "s3cret"):
            resp = client.get("/admin/stats", headers={"X-Admin-Token": "wrong"})
        assert resp.status_code == 401
        mock_db.queries.stats.assert_not_called()
    finally:
        _clear_overrides()


def test_stats_200_with_valid_token(client):
    mock_db = MagicMock()
    mock_db.queries.stats.return_value = {"query_volume": 5}
    _override_db(mock_db)
    try:
        with patch("taxflow.middleware.admin.settings.ADMIN_API_TOKEN", "s3cret"):
            resp = client.get("/admin/stats", headers={"X-Admin-Token": "s3cret"})
        assert resp.status_code == 200
        assert resp.json() == {"query_volume": 5}
        mock_db.queries.stats.assert_called_once()
    finally:
        _clear_overrides()


# --- window parsing ----------------------------------------------------------


def test_stats_default_window_is_7d(client):
    mock_db = MagicMock()
    mock_db.queries.stats.return_value = {}
    _override_db(mock_db)
    try:
        before = datetime.now(timezone.utc)
        with patch("taxflow.middleware.admin.settings.ADMIN_API_TOKEN", "s3cret"):
            client.get("/admin/stats", headers={"X-Admin-Token": "s3cret"})
        after = datetime.now(timezone.utc)
        # stats called positionally with the computed start (now - 7d).
        args, kwargs = mock_db.queries.stats.call_args
        start = args[0] if args else kwargs["start"]
        assert before - timedelta(days=7) - timedelta(seconds=2) <= start
        assert start <= after - timedelta(days=7) + timedelta(seconds=2)
    finally:
        _clear_overrides()


def test_stats_explicit_window(client):
    mock_db = MagicMock()
    mock_db.queries.stats.return_value = {}
    _override_db(mock_db)
    try:
        before = datetime.now(timezone.utc)
        with patch("taxflow.middleware.admin.settings.ADMIN_API_TOKEN", "s3cret"):
            client.get("/admin/stats?window=30d", headers={"X-Admin-Token": "s3cret"})
        args, kwargs = mock_db.queries.stats.call_args
        start = args[0] if args else kwargs["start"]
        expected = before - timedelta(days=30)
        assert abs((start - expected).total_seconds()) < 2
    finally:
        _clear_overrides()


def test_stats_bad_window_returns_400(client):
    mock_db = MagicMock()
    _override_db(mock_db)
    try:
        with patch("taxflow.middleware.admin.settings.ADMIN_API_TOKEN", "s3cret"):
            resp = client.get("/admin/stats?window=banana", headers={"X-Admin-Token": "s3cret"})
        assert resp.status_code == 400
        mock_db.queries.stats.assert_not_called()
    finally:
        _clear_overrides()


# --- parse_window unit coverage ----------------------------------------------


def test_parse_window_days_and_months():
    assert parse_window("7d") == timedelta(days=7)
    assert parse_window("30d") == timedelta(days=30)
    assert parse_window("90d") == timedelta(days=90)
    # 12m -> 12 * 30 = 360 days (under the >=365d cap).
    assert parse_window("12m") == timedelta(days=360)


def test_parse_window_caps_at_least_365_days():
    # A huge window is capped, and the cap covers 12m (>= 365 days).
    capped = parse_window("999d")
    assert capped >= timedelta(days=365)
    assert capped == parse_window("9999d")


def test_parse_window_rejects_bad_format():
    for bad in ("", "d", "7", "7w", "abc", "-1d", "0d"):
        with pytest.raises(Exception):
            parse_window(bad)
