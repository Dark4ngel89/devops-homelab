from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_health_returns_ok():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_root_returns_version():
    response = client.get("/")
    assert response.status_code == 200
    assert "version" in response.json()


def test_metrics_counts_requests():
    client.get("/health")
    response = client.get("/metrics")
    assert response.status_code == 200
    assert 'http_requests_total{method="GET",path="/health",status="200"}' in response.text


def test_unknown_path_is_grouped_as_unmatched():
    client.get("/does-not-exist-123")
    response = client.get("/metrics")
    assert 'path="unmatched",status="404"' in response.text
    assert "does-not-exist-123" not in response.text
