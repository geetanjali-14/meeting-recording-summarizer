import json
import logging

from fastapi import APIRouter, HTTPException, status
from fastapi.testclient import TestClient

from app.core.logging import JSONFormatter
from app.main import create_app

test_router = APIRouter(prefix="/test-security-checks")


@test_router.get("/trigger-unhandled")
async def trigger_unhandled() -> dict:
    # Simulates an unhandled exception leaking raw connection info
    raise RuntimeError(
        "Connection refused: postgresql+psycopg://postgres:secret123@db.prod.internal:5432"
    )


@test_router.get("/trigger-http-error")
async def trigger_http_error() -> dict:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found")


def test_security_headers_present_on_all_responses() -> None:
    app = create_app()
    client = TestClient(app)

    response = client.get("/api/v1/health")
    assert response.status_code == 200

    # Required security headers from SECURITY.md §8
    assert (
        response.headers.get("Strict-Transport-Security")
        == "max-age=63072000; includeSubDomains; preload"
    )
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("X-Frame-Options") == "DENY"
    assert "default-src 'self'" in response.headers.get("Content-Security-Policy", "")
    assert response.headers.get("X-XSS-Protection") == "1; mode=block"
    assert response.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"


def test_unhandled_exception_sanitized_in_http_response() -> None:
    """Verifies unhandled 500 exceptions never leak stack traces
    or credentials in response bodies.
    """
    app = create_app()
    app.include_router(test_router)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.get("/test-security-checks/trigger-unhandled")
    assert response.status_code == 500

    body = response.json()
    assert "error" in body
    assert body["error"]["code"] == "INTERNAL_ERROR"
    # Never leak internal database passwords or URLs!
    assert "secret123" not in response.text
    assert "Traceback" not in response.text
    assert "postgresql+psycopg" not in response.text


def test_log_sanitization_masks_sensitive_keys() -> None:
    """Verifies that JSONFormatter redacts sensitive tokens and credentials."""
    formatter = JSONFormatter()

    record = logging.LogRecord(
        name="test_logger",
        level=logging.INFO,
        pathname="test.py",
        lineno=10,
        msg="Authenticated user request",
        args=(),
        exc_info=None,
    )
    # Custom attributes attached to record
    record.token = "eyJhbGciOi..."
    record.password = "supersecret"
    record.request_id = "req-12345"

    output = formatter.format(record)
    log_data = json.loads(output)

    assert log_data["request_id"] == "req-12345"
    assert "password" not in log_data
    assert "token" not in log_data
    assert "supersecret" not in output
