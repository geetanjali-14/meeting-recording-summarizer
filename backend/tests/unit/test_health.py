from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_check_endpoint() -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["app_name"] == "Meeting Intelligence Summarizer"
    assert "environment" in data
