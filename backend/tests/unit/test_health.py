from unittest.mock import patch

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


def test_readiness_check_endpoint_ready() -> None:
    with (
        patch("app.api.v1.health.check_database", return_value=True),
        patch("app.api.v1.health.check_redis", return_value=True),
    ):
        response = client.get("/api/v1/health/ready")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ready"
        assert data["dependencies"]["database"] == "ready"
        assert data["dependencies"]["redis"] == "ready"
        assert "timestamp" in data


def test_readiness_check_endpoint_db_failure() -> None:
    with (
        patch("app.api.v1.health.check_database", return_value=False),
        patch("app.api.v1.health.check_redis", return_value=True),
    ):
        response = client.get("/api/v1/health/ready")
        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "unready"
        assert data["dependencies"]["database"] == "unreachable"
        assert data["dependencies"]["redis"] == "ready"


def test_readiness_check_endpoint_redis_failure() -> None:
    with (
        patch("app.api.v1.health.check_database", return_value=True),
        patch("app.api.v1.health.check_redis", return_value=False),
    ):
        response = client.get("/api/v1/health/ready")
        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "unready"
        assert data["dependencies"]["database"] == "ready"
        assert data["dependencies"]["redis"] == "unreachable"
