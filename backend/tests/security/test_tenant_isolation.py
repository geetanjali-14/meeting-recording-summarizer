import datetime
import uuid
from collections.abc import Sequence

import pytest
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.testclient import TestClient
from jose import jwt
from pydantic import BaseModel

from app.api.deps import get_current_user
from app.core.config import Settings, get_settings
from app.core.security import UserContext
from app.main import create_app
from app.models.meeting import Meeting, MeetingStatus


# Test DTOs for testing tenant isolation & IDOR
class MeetingCreatePayload(BaseModel):
    title: str
    description: str | None = None
    user_id: uuid.UUID | None = None  # Attacker attempt to override identity


class MeetingResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    title: str
    description: str | None = None
    status: str


class InMemoryMeetingRepository:
    """In-memory repository implementing the exact tenant scoping interface."""

    def __init__(self) -> None:
        self.storage: dict[uuid.UUID, Meeting] = {}

    async def create(
        self, user_id: uuid.UUID, title: str, description: str | None = None
    ) -> Meeting:
        m_id = uuid.uuid4()
        meeting = Meeting(
            id=m_id,
            user_id=user_id,
            title=title,
            description=description,
            status=MeetingStatus.CREATED,
        )
        self.storage[m_id] = meeting
        return meeting

    async def get_by_id(self, meeting_id: uuid.UUID, user_id: uuid.UUID) -> Meeting | None:
        meeting = self.storage.get(meeting_id)
        if meeting is None or meeting.user_id != user_id:
            return None
        return meeting

    async def delete(self, meeting_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        meeting = await self.get_by_id(meeting_id=meeting_id, user_id=user_id)
        if meeting is None:
            return False
        del self.storage[meeting_id]
        return True

    async def list_by_user(
        self, user_id: uuid.UUID, limit: int = 50, offset: int = 0
    ) -> Sequence[Meeting]:
        return [m for m in self.storage.values() if m.user_id == user_id]


# Shared repo instance dependency for test routes
shared_repo = InMemoryMeetingRepository()


def get_repo() -> InMemoryMeetingRepository:
    return shared_repo


# Create an isolated test router mimicking authenticated CRUD resources
secure_router = APIRouter(prefix="/test-meetings", tags=["SecureTestMeetings"])


@secure_router.post("", response_model=MeetingResponse)
async def create_meeting_endpoint(
    payload: MeetingCreatePayload,
    current_user: UserContext = Depends(get_current_user),
    repo: InMemoryMeetingRepository = Depends(get_repo),
) -> MeetingResponse:
    # Always scopes strictly to authenticated user_id; ignores payload.user_id
    meeting = await repo.create(
        user_id=current_user.user_id,
        title=payload.title,
        description=payload.description,
    )
    return MeetingResponse(
        id=meeting.id,
        user_id=meeting.user_id,
        title=meeting.title,
        description=meeting.description,
        status=meeting.status.value,
    )


@secure_router.get("/{meeting_id}", response_model=MeetingResponse)
async def get_meeting_endpoint(
    meeting_id: uuid.UUID,
    current_user: UserContext = Depends(get_current_user),
    repo: InMemoryMeetingRepository = Depends(get_repo),
) -> MeetingResponse:
    meeting = await repo.get_by_id(meeting_id=meeting_id, user_id=current_user.user_id)
    if meeting is None:
        # Anti-enumeration IDOR defense: return 404 for unowned or missing resources
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Meeting not found",
        )
    return MeetingResponse(
        id=meeting.id,
        user_id=meeting.user_id,
        title=meeting.title,
        description=meeting.description,
        status=meeting.status.value,
    )


@secure_router.delete("/{meeting_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_meeting_endpoint(
    meeting_id: uuid.UUID,
    current_user: UserContext = Depends(get_current_user),
    repo: InMemoryMeetingRepository = Depends(get_repo),
) -> None:
    deleted = await repo.delete(meeting_id=meeting_id, user_id=current_user.user_id)
    if not deleted:
        # Anti-enumeration IDOR defense: return 404 for unowned or missing resources
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Meeting not found",
        )


def create_token(user_id: uuid.UUID, secret: str = "test-secret") -> str:
    now = datetime.datetime.now(datetime.UTC)
    payload = {
        "sub": str(user_id),
        "email": "test@example.com",
        "aud": "authenticated",
        "iss": "https://auth.example.com",
        "exp": int((now + datetime.timedelta(hours=1)).timestamp()),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


@pytest.fixture(autouse=True)
def clean_storage() -> None:
    shared_repo.storage.clear()


@pytest.fixture
def client() -> TestClient:
    app = create_app()
    app.include_router(secure_router)
    test_settings = Settings(
        JWT_ISSUER="https://auth.example.com",
        JWT_AUDIENCE="authenticated",
        JWT_ALGORITHMS=["HS256"],
        JWT_SIGNING_KEY_OR_JWKS="test-secret",
    )
    app.dependency_overrides[get_settings] = lambda: test_settings
    return TestClient(app)


def test_public_health_endpoint_remains_unauthenticated(client: TestClient) -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_unauthenticated_request_rejected(client: TestClient) -> None:
    response = client.get(f"/test-meetings/{uuid.uuid4()}")
    assert response.status_code == 401
    assert "WWW-Authenticate" in response.headers
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_malformed_auth_header_rejected(client: TestClient) -> None:
    response = client.get(
        f"/test-meetings/{uuid.uuid4()}",
        headers={"Authorization": "Bearer not.a.valid.jwt"},
    )
    assert response.status_code == 401


def test_identity_override_attempt_prevented(client: TestClient) -> None:
    legitimate_user_id = uuid.uuid4()
    victim_user_id = uuid.uuid4()
    token = create_token(legitimate_user_id)

    # Attacker tries to pass victim_user_id in request body
    response = client.post(
        "/test-meetings",
        json={
            "title": "Malicious Creation",
            "description": "Attempt to create meeting on behalf of victim",
            "user_id": str(victim_user_id),
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    data = response.json()
    # Meeting must be owned by legitimate user from token, not victim!
    assert data["user_id"] == str(legitimate_user_id)
    assert data["user_id"] != str(victim_user_id)


@pytest.mark.asyncio
async def test_cross_user_read_returns_404_anti_enumeration(client: TestClient) -> None:
    user_a = uuid.uuid4()
    user_b = uuid.uuid4()

    # User A creates a meeting
    meeting_a = await shared_repo.create(user_id=user_a, title="User A Confidential Meeting")

    # User A can read their own meeting
    token_a = create_token(user_a)
    res_a = client.get(
        f"/test-meetings/{meeting_a.id}",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert res_a.status_code == 200
    assert res_a.json()["id"] == str(meeting_a.id)

    # User B attempts to read User A's meeting -> must return 404 NOT FOUND (anti-enumeration)
    token_b = create_token(user_b)
    res_b = client.get(
        f"/test-meetings/{meeting_a.id}",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert res_b.status_code == 404
    assert res_b.json()["detail"] == "Meeting not found"


@pytest.mark.asyncio
async def test_cross_user_delete_returns_404_anti_enumeration(client: TestClient) -> None:
    user_a = uuid.uuid4()
    user_b = uuid.uuid4()

    # User A creates a meeting
    meeting_a = await shared_repo.create(user_id=user_a, title="User A Protected Meeting")

    # User B attempts to delete User A's meeting -> must return 404 NOT FOUND
    token_b = create_token(user_b)
    res_b = client.delete(
        f"/test-meetings/{meeting_a.id}",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert res_b.status_code == 404
    assert res_b.json()["detail"] == "Meeting not found"

    # Verify meeting was NOT deleted
    assert meeting_a.id in shared_repo.storage

    # User A can delete their own meeting -> 204
    token_a = create_token(user_a)
    res_a = client.delete(
        f"/test-meetings/{meeting_a.id}",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert res_a.status_code == 204
    assert meeting_a.id not in shared_repo.storage
