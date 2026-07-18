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
    """A valid token with no matching client row means the user authenticated
    via OAuth and never signed up, so get_current_client auto-provisions a
    minimal trial account (mirroring POST /api/signup) instead of 404ing."""
    auth_port = MagicMock()
    mock_get_auth.return_value = auth_port
    auth_port.validate_token.return_value = Identity(
        email="missing@example.com.au", metadata={"full_name": "New User"}
    )

    repos = MagicMock()
    mock_get_rel.return_value = repos
    repos.clients.get_by_email.return_value = None
    provisioned = {"id": "client-new", "email": "missing@example.com.au"}
    repos.clients.create.return_value = provisioned
    repos.trials.latest_for_client.return_value = {"id": "trial-1"}

    from taxflow.main import app
    from taxflow.db import get_db

    app.dependency_overrides[get_db] = lambda: repos
    try:
        response = client.get(
            "/settings/me", headers={"Authorization": "Bearer good-token"}
        )
        assert response.status_code == 200
        # A client row + trial were created for the OAuth user.
        create_arg = repos.clients.create.call_args.args[0]
        assert create_arg["email"] == "missing@example.com.au"
        assert create_arg["business_name"] == "New User"
        repos.trials.create.assert_called_once_with("client-new")
    finally:
        app.dependency_overrides.clear()


@patch("taxflow.middleware.auth.providers.get_relational_data")
@patch("taxflow.middleware.auth.providers.get_auth_port")
def test_valid_token_and_client_row_returns_200(
    mock_get_auth, mock_get_rel, client, trial_client_row
):
    auth_port = MagicMock()
    mock_get_auth.return_value = auth_port
    auth_port.validate_token.return_value = Identity(email=trial_client_row["email"])

    repos = MagicMock()
    mock_get_rel.return_value = repos
    repos.clients.get_by_email.return_value = trial_client_row
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
        assert response.json()["client"] == trial_client_row
    finally:
        app.dependency_overrides.clear()
