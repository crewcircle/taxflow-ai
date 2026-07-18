from unittest.mock import MagicMock, patch

from taxflow.ports.auth import DemoSession


def test_signup_requires_valid_fields(client):
    response = client.post("/auth/signup", json={"business_name": "Test Firm"})
    assert response.status_code == 422  # missing required fields


@patch("taxflow.routers.auth.providers.get_relational_data")
def test_signup_creates_client_and_trial(mock_get_rel, client):
    repos = MagicMock()
    mock_get_rel.return_value = repos
    # No existing client with this email.
    repos.clients.email_exists.return_value = False
    repos.clients.create.return_value = {"id": "client-123"}

    response = client.post(
        "/auth/signup",
        json={
            "business_name": "Smith Dental Practice",
            "email": "admin@smithdental.com.au",
            "business_type": "dental",
            "suburb": "Sydney CBD",
            "state": "NSW",
        },
    )
    assert response.status_code == 200
    assert response.json()["client_id"] == "client-123"
    repos.trials.create.assert_called_once_with("client-123")


@patch("taxflow.routers.auth.providers.get_relational_data")
def test_signup_duplicate_email_conflicts(mock_get_rel, client):
    repos = MagicMock()
    mock_get_rel.return_value = repos
    repos.clients.email_exists.return_value = True

    response = client.post(
        "/auth/signup",
        json={
            "business_name": "Smith Dental Practice",
            "email": "admin@smithdental.com.au",
            "business_type": "dental",
            "suburb": "Sydney CBD",
            "state": "NSW",
        },
    )
    assert response.status_code == 409
    repos.clients.create.assert_not_called()


@patch("taxflow.routers.auth.providers.get_auth_port")
@patch("taxflow.routers.auth.providers.get_relational_data")
def test_demo_login_returns_session_tokens(mock_get_rel, mock_get_auth, client):
    repos = MagicMock()
    mock_get_rel.return_value = repos
    repos.clients.find_demo_emails.return_value = ["demo@example.com.au"]

    auth_port = MagicMock()
    mock_get_auth.return_value = auth_port
    auth_port.issue_demo_session.return_value = DemoSession(
        access_token="access-abc", refresh_token="refresh-xyz"
    )

    response = client.post("/auth/demo-login")
    assert response.status_code == 200
    body = response.json()
    assert body["access_token"] == "access-abc"
    assert body["refresh_token"] == "refresh-xyz"


@patch("taxflow.routers.auth.providers.get_relational_data")
def test_demo_login_no_demo_account_configured(mock_get_rel, client):
    repos = MagicMock()
    mock_get_rel.return_value = repos
    repos.clients.find_demo_emails.return_value = []

    response = client.post("/auth/demo-login")
    assert response.status_code == 503
