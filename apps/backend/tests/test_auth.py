from unittest.mock import MagicMock, patch


def test_signup_requires_valid_fields(client):
    response = client.post("/auth/signup", json={"business_name": "Test Firm"})
    assert response.status_code == 422  # missing required fields


@patch("taxflow.routers.auth.get_supabase_client")
def test_signup_creates_client_and_trial(mock_get_client, client):
    mock_sb = MagicMock()
    mock_get_client.return_value = mock_sb
    mock_sb.table.return_value.insert.return_value.execute.return_value.data = [
        {"id": "client-123"}
    ]

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
