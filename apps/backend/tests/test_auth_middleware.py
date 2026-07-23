"""Hot-path tests for the get_current_client dependency (Task B5).

Exercises a protected route (``GET /settings/me``) through the real
``get_current_client`` dependency, patching the AuthPort and clients repo at the
``providers`` module accessors, to assert the 401/404/200 semantics.
"""

from unittest.mock import MagicMock, patch

from taxflow.ports.auth import AuthError, Identity


def test_missing_bearer_returns_401(client):
    response = client.get("/settings/me")
    assert response.status_code == 401


@patch("taxflow.middleware.auth.providers.get_auth_port")
def test_invalid_token_returns_401(mock_get_auth, client):
    auth_port = MagicMock()
    mock_get_auth.return_value = auth_port
    auth_port.validate_token.side_effect = AuthError("bad token")

    response = client.get(
        "/settings/me", headers={"Authorization": "Bearer bad-token"}
    )
    assert response.status_code == 401


@patch("taxflow.middleware.auth.providers.get_relational_data")
@patch("taxflow.middleware.auth.providers.get_auth_port")
def test_valid_token_no_client_row_auto_provisions(mock_get_auth, mock_get_rel, client):
    """A valid token with no matching users/clients row means the user
    authenticated via OAuth and never signed up, so get_current_client
    auto-provisions a minimal trial account + Owner user (mirroring POST
    /api/signup) instead of 404ing."""
    auth_port = MagicMock()
    mock_get_auth.return_value = auth_port
    auth_port.validate_token.return_value = Identity(
        email="missing@example.com.au", sub="auth-user-new", metadata={"full_name": "New User"}
    )

    repos = MagicMock()
    mock_get_rel.return_value = repos
    repos.users.get_by_id.return_value = None
    repos.clients.get_by_email.return_value = None
    provisioned = {"id": "client-new", "email": "missing@example.com.au"}
    repos.clients.create.return_value = provisioned
    repos.users.create.return_value = {"id": "auth-user-new", "role": "owner"}
    repos.trials.latest_for_client.return_value = {"id": "trial-1"}

    from taxflow.main import app
    from taxflow.db import get_db

    app.dependency_overrides[get_db] = lambda: repos
    try:
        response = client.get(
            "/settings/me", headers={"Authorization": "Bearer good-token"}
        )
        assert response.status_code == 200
        # A client row + trial + Owner user were created for the OAuth user.
        create_arg = repos.clients.create.call_args.args[0]
        assert create_arg["email"] == "missing@example.com.au"
        assert create_arg["business_name"] == "New User"
        repos.trials.create.assert_called_once_with("client-new")
        repos.users.create.assert_called_once_with(
            "auth-user-new", "client-new", "missing@example.com.au", role="owner"
        )
    finally:
        app.dependency_overrides.clear()


@patch("taxflow.middleware.auth.providers.get_relational_data")
@patch("taxflow.middleware.auth.providers.get_auth_port")
def test_valid_token_and_client_row_returns_200(
    mock_get_auth, mock_get_rel, client, trial_client_row
):
    auth_port = MagicMock()
    mock_get_auth.return_value = auth_port
    auth_port.validate_token.return_value = Identity(
        email=trial_client_row["email"], sub="auth-user-1"
    )

    repos = MagicMock()
    mock_get_rel.return_value = repos
    repos.users.get_by_id.return_value = {
        "id": "auth-user-1",
        "client_id": trial_client_row["id"],
        "role": "owner",
        "status": "active",
    }
    repos.clients.get_by_id.return_value = trial_client_row
    repos.trials.latest_for_client.return_value = {"id": "trial-1"}

    from taxflow.main import app
    from taxflow.db import get_db

    # Override get_db so the route body (settings/me) doesn't touch a real DB.
    app.dependency_overrides[get_db] = lambda: repos
    try:
        response = client.get(
            "/settings/me", headers={"Authorization": "Bearer good-token"}
        )
        assert response.status_code == 200
        assert response.json()["client"] == {
            **trial_client_row,
            "role": "owner",
            "user_id": "auth-user-1",
        }
    finally:
        app.dependency_overrides.clear()
