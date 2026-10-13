import time
import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.core.rate_limiter import (
    SlidingWindowRateLimiter,
    confirm_upload_limiter,
    create_meeting_limiter,
    general_read_limiter,
    status_polling_limiter,
)
from app.main import create_app
from tests.security.test_tenant_isolation import create_token


@pytest.fixture(autouse=True)
def reset_limiters() -> None:
    create_meeting_limiter.reset()
    confirm_upload_limiter.reset()
    status_polling_limiter.reset()
    general_read_limiter.reset()


def test_sliding_window_rate_limiter_unit_logic() -> None:
    limiter = SlidingWindowRateLimiter(max_requests=3, window_seconds=2)
    user_id = uuid.uuid4()
    other_user = uuid.uuid4()

    # First 3 requests permitted
    assert limiter.is_allowed(user_id)[0] is True
    assert limiter.is_allowed(user_id)[0] is True
    assert limiter.is_allowed(user_id)[0] is True

    # 4th request within 2 seconds blocked with 429
    allowed, retry_after = limiter.is_allowed(user_id)
    assert allowed is False
    assert retry_after >= 1

    # Independent user is unaffected (tenant-isolated rate limits)
    assert limiter.is_allowed(other_user)[0] is True


def test_post_meetings_rate_limit_enforced() -> None:
    app = create_app()
    test_settings = Settings(
        JWT_ISSUER="https://auth.example.com",
        JWT_AUDIENCE="authenticated",
        JWT_ALGORITHMS=["HS256"],
        JWT_SIGNING_KEY_OR_JWKS="test-secret",
    )
    app.dependency_overrides[get_settings] = lambda: test_settings
    client = TestClient(app)

    user_id = uuid.uuid4()
    token = create_token(user_id)
    headers = {"Authorization": f"Bearer {token}"}

    # Custom limiter configured to max 2 requests to simulate boundary quickly
    create_meeting_limiter.max_requests = 2

    # Request 1 & 2 succeed (or fail validation, but pass rate limiter dependency)
    res1 = client.post("/api/v1/meetings", json={}, headers=headers)
    assert res1.status_code != 429

    res2 = client.post("/api/v1/meetings", json={}, headers=headers)
    assert res2.status_code != 429

    # Request 3 is blocked by rate limiting
    res3 = client.post("/api/v1/meetings", json={}, headers=headers)
    assert res3.status_code == 429
    assert res3.json()["error"]["code"] == "RATE_LIMITED"
    assert "Retry-After" in res3.headers


def test_get_meetings_read_rate_limit_enforced() -> None:
    app = create_app()
    test_settings = Settings(
        JWT_ISSUER="https://auth.example.com",
        JWT_AUDIENCE="authenticated",
        JWT_ALGORITHMS=["HS256"],
        JWT_SIGNING_KEY_OR_JWKS="test-secret",
    )
    app.dependency_overrides[get_settings] = lambda: test_settings
    client = TestClient(app)

    user_id = uuid.uuid4()
    token = create_token(user_id)
    headers = {"Authorization": f"Bearer {token}"}

    # Temporarily set max_requests to 2
    general_read_limiter.max_requests = 2

    res1 = client.get(f"/api/v1/meetings/{uuid.uuid4()}", headers=headers)
    assert res1.status_code != 429

    res2 = client.get(f"/api/v1/meetings/{uuid.uuid4()}", headers=headers)
    assert res2.status_code != 429

    res3 = client.get(f"/api/v1/meetings/{uuid.uuid4()}", headers=headers)
    assert res3.status_code == 429
    assert res3.json()["error"]["code"] == "RATE_LIMITED"

