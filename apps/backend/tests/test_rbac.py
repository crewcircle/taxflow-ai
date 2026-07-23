"""Phase 1: RBAC permission matrix + require_permission + /staff endpoints.

Follows the ``test_engagements_api.py`` style: FastAPI ``TestClient`` +
``app.dependency_overrides`` with a ``MagicMock`` db.
"""
from unittest.mock import MagicMock, patch

import pytest

from taxflow.db import get_db
from taxflow.main import app
from taxflow.middleware.auth import get_current_client
from taxflow.ports.auth import Identity
from taxflow.rbac import Role, has_permission

OWNER = {"id": "client-1", "email": "owner@firm.com.au", "role": "owner", "user_id": "user-owner"}
REVIEWER = {"id": "client-1", "email": "rev@firm.com.au", "role": "reviewer", "user_id": "user-rev"}
STAFF = {"id": "client-1", "email": "staff@firm.com.au", "role": "staff", "user_id": "user-staff"}


def _override(fake_client, mock_db):
    app.dependency_overrides[get_current_client] = lambda: fake_client
    app.dependency_overrides[get_db] = lambda: mock_db


def _clear():
    app.dependency_overrides.clear()


# --- pure permission matrix ---------------------------------------------------


@pytest.mark.parametrize(
    "permission,allowed_roles",
    [
        ("billing.manage", {Role.OWNER}),
        ("staff.manage", {Role.OWNER}),
        ("documents.approve", {Role.OWNER, Role.REVIEWER}),
        ("ato_response.approve", {Role.OWNER, Role.REVIEWER}),
        ("verification.resolve", {Role.OWNER, Role.REVIEWER}),
        ("work.delete_any", {Role.OWNER}),
        ("query.ask", {Role.OWNER, Role.REVIEWER, Role.STAFF}),
        ("documents.draft", {Role.OWNER, Role.REVIEWER, Role.STAFF}),
    ],
)
def test_permission_matrix(permission, allowed_roles):
    for role in Role:
        assert has_permission(role.value, permission) == (role in allowed_roles)


def test_has_permission_fails_closed_on_unknown_role():
    assert has_permission("superadmin", "query.ask") is False


def test_has_permission_fails_closed_on_unknown_permission():
    assert has_permission("owner", "not_a_real_permission") is False


# --- require_permission dependency (via a real gated route) ------------------


@patch("taxflow.routers.auth.providers.get_billing_port")
def test_require_permission_403s_staff_on_owner_only_action(mock_get_billing, client, monkeypatch):
    monkeypatch.setenv("STRIPE_PROFESSIONAL_PRICE_ID", "price_pro_123")
    _override(STAFF, MagicMock())
    try:
        resp = client.post("/auth/checkout-session", json={"tier": "professional"})
        assert resp.status_code == 403
    finally:
        _clear()


@patch("taxflow.routers.auth.providers.get_billing_port")
def test_require_permission_allows_owner(mock_get_billing, client, monkeypatch):
    from taxflow.ports.billing import CheckoutSession

    monkeypatch.setenv("STRIPE_PROFESSIONAL_PRICE_ID", "price_pro_123")
    billing = MagicMock()
    mock_get_billing.return_value = billing
    billing.create_checkout_session.return_value = CheckoutSession(
        url="https://checkout.stripe.com/pay/cs_test", id="cs_test_123"
    )
    _override(OWNER, MagicMock())
    try:
        resp = client.post("/auth/checkout-session", json={"tier": "professional"})
        assert resp.status_code == 200
    finally:
        _clear()


def test_require_permission_defaults_missing_role_to_owner(client, monkeypatch):
    """A client dict with no role key at all (pre-043 in-flight request, or a
    test fixture that predates RBAC) defaults to Owner rather than 403ing."""
    monkeypatch.setenv("STRIPE_PROFESSIONAL_PRICE_ID", "price_pro_123")
    with patch("taxflow.routers.auth.providers.get_billing_port") as mock_get_billing:
        from taxflow.ports.billing import CheckoutSession

        billing = MagicMock()
        mock_get_billing.return_value = billing
        billing.create_checkout_session.return_value = CheckoutSession(
            url="https://checkout.stripe.com/pay/cs_test", id="cs_test_123"
        )
        _override({"id": "client-1", "email": "x@y.com.au"}, MagicMock())
        try:
            resp = client.post("/auth/checkout-session", json={"tier": "professional"})
            assert resp.status_code == 200
        finally:
            _clear()


# --- GET /staff ----------------------------------------------------------------


def test_list_staff_visible_to_every_role(client):
    mock_db = MagicMock()
    mock_db.users.list_for_client.return_value = [
        {"id": "user-owner", "role": "owner", "status": "active"}
    ]
    _override(STAFF, mock_db)
    try:
        resp = client.get("/staff")
        assert resp.status_code == 200
        mock_db.users.list_for_client.assert_called_once_with("client-1")
    finally:
        _clear()


# --- POST /staff/invite ---------------------------------------------------------


def test_invite_staff_requires_staff_manage(client):
    mock_db = MagicMock()
    _override(STAFF, mock_db)
    try:
        resp = client.post("/staff/invite", json={"email": "new@firm.com.au"})
        assert resp.status_code == 403
        mock_db.users.create.assert_not_called()
    finally:
        _clear()


@patch("taxflow.routers.staff.providers.get_auth_port")
def test_invite_staff_creates_invited_user(mock_get_auth, client):
    auth_port = MagicMock()
    mock_get_auth.return_value = auth_port
    auth_port.invite_user.return_value = Identity(email="new@firm.com.au", sub="auth-new")

    mock_db = MagicMock()
    mock_db.users.get_by_client_and_email.return_value = None
    mock_db.users.create.return_value = {"id": "auth-new", "role": "staff", "status": "invited"}
    _override(OWNER, mock_db)
    try:
        resp = client.post(
            "/staff/invite",
            json={"email": "new@firm.com.au", "role": "staff", "display_name": "Jamie"},
        )
        assert resp.status_code == 201
        mock_db.users.create.assert_called_once_with(
            "auth-new", "client-1", "new@firm.com.au", "staff", "Jamie", "user-owner", "invited"
        )
    finally:
        _clear()


def test_invite_staff_rejects_duplicate_email(client):
    mock_db = MagicMock()
    mock_db.users.get_by_client_and_email.return_value = {"id": "existing-user"}
    _override(OWNER, mock_db)
    try:
        resp = client.post("/staff/invite", json={"email": "existing@firm.com.au"})
        assert resp.status_code == 409
    finally:
        _clear()


# --- PATCH /staff/{user_id} ----------------------------------------------------


def test_update_staff_role_requires_staff_manage(client):
    mock_db = MagicMock()
    _override(REVIEWER, mock_db)
    try:
        resp = client.patch("/staff/user-x", json={"role": "reviewer"})
        assert resp.status_code == 403
    finally:
        _clear()


def test_update_staff_role_404s_for_foreign_client(client):
    mock_db = MagicMock()
    mock_db.users.get_by_id.return_value = {"id": "user-x", "client_id": "some-other-client", "role": "staff"}
    _override(OWNER, mock_db)
    try:
        resp = client.patch("/staff/user-x", json={"role": "reviewer"})
        assert resp.status_code == 404
    finally:
        _clear()


def test_update_staff_role_refuses_to_demote_last_owner(client):
    mock_db = MagicMock()
    mock_db.users.get_by_id.return_value = {"id": "user-owner", "client_id": "client-1", "role": "owner"}
    mock_db.users.count_active_owners.return_value = 1
    _override(OWNER, mock_db)
    try:
        resp = client.patch("/staff/user-owner", json={"role": "staff"})
        assert resp.status_code == 409
        mock_db.users.update_role.assert_not_called()
    finally:
        _clear()


def test_update_staff_role_allows_demoting_owner_when_others_remain(client):
    mock_db = MagicMock()
    mock_db.users.get_by_id.return_value = {"id": "user-owner-2", "client_id": "client-1", "role": "owner"}
    mock_db.users.count_active_owners.return_value = 2
    mock_db.users.update_role.return_value = {"id": "user-owner-2", "role": "reviewer"}
    _override(OWNER, mock_db)
    try:
        resp = client.patch("/staff/user-owner-2", json={"role": "reviewer"})
        assert resp.status_code == 200
        mock_db.users.update_role.assert_called_once_with("client-1", "user-owner-2", "reviewer")
    finally:
        _clear()


# --- DELETE /staff/{user_id} ---------------------------------------------------


def test_remove_staff_refuses_to_remove_last_owner(client):
    mock_db = MagicMock()
    mock_db.users.get_by_id.return_value = {"id": "user-owner", "client_id": "client-1", "role": "owner"}
    mock_db.users.count_active_owners.return_value = 1
    _override(OWNER, mock_db)
    try:
        resp = client.delete("/staff/user-owner")
        assert resp.status_code == 409
        mock_db.users.set_status.assert_not_called()
    finally:
        _clear()


def test_remove_staff_soft_deletes_non_owner(client):
    mock_db = MagicMock()
    mock_db.users.get_by_id.return_value = {"id": "user-staff", "client_id": "client-1", "role": "staff"}
    mock_db.users.set_status.return_value = {"id": "user-staff", "status": "removed"}
    _override(OWNER, mock_db)
    try:
        resp = client.delete("/staff/user-staff")
        assert resp.status_code == 200
        mock_db.users.set_status.assert_called_once_with("client-1", "user-staff", "removed")
    finally:
        _clear()
