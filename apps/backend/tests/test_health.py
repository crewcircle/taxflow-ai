def test_health_endpoint_returns_expected_schema(client):
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "version" in body
    assert "environment" in body
    assert "database" in body
    assert "scheduler" in body
    assert "timestamp" in body
