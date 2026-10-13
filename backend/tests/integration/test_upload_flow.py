import datetime
import uuid
from collections.abc import AsyncGenerator, Sequence
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from jose import jwt
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    get_current_user,
    get_db_session,
    get_job_repository,
    get_meeting_repository,
    get_recording_repository,
    get_storage_provider,
)
from app.core.config import Settings, get_settings
from app.core.security import UserContext
from app.main import create_app
from app.models.meeting import Meeting, MeetingStatus
from app.models.processing_job import JobStage, JobStatus, ProcessingJob
from app.models.recording import Recording, RecordingStatus
from app.providers.storage.base import StorageProvider
from app.repositories.job_repository import JobRepository
from app.repositories.meeting_repository import MeetingRepository
from app.repositories.recording_repository import RecordingRepository


class MockStorageProvider(StorageProvider):
    """Mock storage provider simulating R2 / S3 operations."""

    def __init__(self) -> None:
        self.objects: set[str] = set()
        self.presigned_urls_generated: list[dict[str, Any]] = []

    def generate_presigned_upload_url(
        self,
        storage_key: str,
        content_type: str,
        expires_in_seconds: int = 900,
    ) -> str:
        self.presigned_urls_generated.append(
            {
                "type": "upload",
                "key": storage_key,
                "content_type": content_type,
                "expires": expires_in_seconds,
            }
        )
        return f"https://mock-r2.cloudflarestorage.com/{storage_key}?signature=mock_sig"

    def generate_presigned_download_url(
        self,
        storage_key: str,
        expires_in_seconds: int = 3600,
    ) -> str:
        self.presigned_urls_generated.append(
            {"type": "download", "key": storage_key, "expires": expires_in_seconds}
        )
        return f"https://mock-r2.cloudflarestorage.com/{storage_key}?signature=mock_get_sig"

    def delete_object(self, storage_key: str) -> None:
        if storage_key in self.objects:
            self.objects.remove(storage_key)

    def object_exists(self, storage_key: str) -> bool:
        return storage_key in self.objects


class InMemoryMeetingRepository(MeetingRepository):
    def __init__(self) -> None:
        self.storage: dict[uuid.UUID, Meeting] = {}

    async def create(
        self,
        user_id: uuid.UUID,
        title: str,
        description: str | None = None,
        meeting_date: datetime.date | None = None,
    ) -> Meeting:
        m_id = uuid.uuid4()
        meeting = Meeting(
            id=m_id,
            user_id=user_id,
            title=title,
            description=description,
            status=MeetingStatus.CREATED,
        )
        if meeting_date is not None:
            meeting.meeting_date = meeting_date
        self.storage[m_id] = meeting
        return meeting

    async def get_by_id(
        self,
        meeting_id: uuid.UUID,
        user_id: uuid.UUID,
        include_relations: bool = False,
    ) -> Meeting | None:
        meeting = self.storage.get(meeting_id)
        if meeting is None or meeting.user_id != user_id:
            return None
        return meeting

    async def list_by_user(
        self,
        user_id: uuid.UUID,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[Meeting]:
        meetings = [
            m for m in self.storage.values()
            if m.user_id == user_id and m.status != MeetingStatus.PURGED
        ]
        return meetings[offset : offset + limit]

    async def count_by_user(self, user_id: uuid.UUID) -> int:
        return len([
            m for m in self.storage.values()
            if m.user_id == user_id and m.status != MeetingStatus.PURGED
        ])

    async def mark_active(self, meeting: Meeting) -> Meeting:
        meeting.status = MeetingStatus.ACTIVE
        return meeting

    async def mark_deleting(self, meeting_id: uuid.UUID, user_id: uuid.UUID) -> Meeting | None:
        meeting = await self.get_by_id(meeting_id, user_id)
        if meeting is None or meeting.status in (MeetingStatus.DELETING, MeetingStatus.PURGED):
            return None
        meeting.status = MeetingStatus.DELETING
        return meeting

    async def delete(self, meeting_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        meeting = await self.get_by_id(meeting_id, user_id)
        if meeting is None:
            return False
        del self.storage[meeting_id]
        return True


class InMemoryRecordingRepository(RecordingRepository):
    def __init__(self) -> None:
        self.storage: dict[uuid.UUID, Recording] = {}

    async def create(
        self,
        meeting_id: uuid.UUID,
        user_id: uuid.UUID,
        storage_key: str,
        original_filename: str,
        content_type: str,
        file_size_bytes: int,
        status: RecordingStatus = RecordingStatus.PRESIGNED,
        recording_id: uuid.UUID | None = None,
    ) -> Recording:
        r_id = recording_id or uuid.uuid4()
        recording = Recording(
            id=r_id,
            meeting_id=meeting_id,
            user_id=user_id,
            storage_key=storage_key,
            original_filename=original_filename,
            content_type=content_type,
            file_size_bytes=file_size_bytes,
            status=status,
        )
        self.storage[r_id] = recording
        return recording

    async def get_by_id(self, recording_id: uuid.UUID, user_id: uuid.UUID) -> Recording | None:
        recording = self.storage.get(recording_id)
        if recording is None or recording.user_id != user_id:
            return None
        return recording

    async def get_by_meeting_id(
        self, meeting_id: uuid.UUID, user_id: uuid.UUID
    ) -> Recording | None:
        for r in self.storage.values():
            if r.meeting_id == meeting_id and r.user_id == user_id:
                return r
        return None

    async def mark_uploaded(self, recording: Recording) -> Recording:
        recording.status = RecordingStatus.UPLOADED
        recording.uploaded_at = datetime.datetime.now(datetime.UTC)
        return recording

    async def mark_deleted(self, recording: Recording) -> Recording:
        recording.status = RecordingStatus.DELETED
        return recording


class InMemoryJobRepository(JobRepository):
    def __init__(self) -> None:
        self.storage: dict[uuid.UUID, ProcessingJob] = {}

    async def create(self, meeting_id: uuid.UUID, user_id: uuid.UUID) -> ProcessingJob:
        j_id = uuid.uuid4()
        job = ProcessingJob(
            id=j_id,
            meeting_id=meeting_id,
            user_id=user_id,
            status=JobStatus.PENDING,
            stage=JobStage.CREATED,
            attempt=0,
        )
        self.storage[j_id] = job
        return job

    async def get_by_meeting_id(
        self, meeting_id: uuid.UUID, user_id: uuid.UUID
    ) -> ProcessingJob | None:
        for j in self.storage.values():
            if j.meeting_id == meeting_id and j.user_id == user_id:
                return j
        return None

    async def get_by_id(self, job_id: uuid.UUID, user_id: uuid.UUID) -> ProcessingJob | None:
        job = self.storage.get(job_id)
        if job is None or job.user_id != user_id:
            return None
        return job

    async def set_celery_task_id(
        self, job: ProcessingJob, celery_task_id: str
    ) -> ProcessingJob:
        job.celery_task_id = celery_task_id
        return job


TEST_JWT_SECRET = "test-secret-key-32-chars-minimum-length"


def make_token(user_id: uuid.UUID) -> str:
    now = datetime.datetime.now(datetime.UTC)
    payload = {
        "sub": str(user_id),
        "email": "tester@example.com",
        "aud": "authenticated",
        "iss": "https://auth.example.com",
        "exp": int((now + datetime.timedelta(hours=1)).timestamp()),
    }
    return jwt.encode(payload, TEST_JWT_SECRET, algorithm="HS256")


@pytest.fixture
def mock_storage() -> MockStorageProvider:
    return MockStorageProvider()


@pytest.fixture
def mock_meeting_repo() -> InMemoryMeetingRepository:
    return InMemoryMeetingRepository()


@pytest.fixture
def mock_recording_repo(mock_meeting_repo: InMemoryMeetingRepository) -> InMemoryRecordingRepository:
    repo = InMemoryRecordingRepository()
    orig_create = repo.create

    async def create_with_linking(*args: Any, **kwargs: Any) -> Recording:
        rec = await orig_create(*args, **kwargs)
        if rec.meeting_id in mock_meeting_repo.storage:
            mock_meeting_repo.storage[rec.meeting_id].recording = rec
        return rec

    repo.create = create_with_linking  # type: ignore[assignment]
    return repo


@pytest.fixture
def mock_job_repo(mock_meeting_repo: InMemoryMeetingRepository) -> InMemoryJobRepository:
    repo = InMemoryJobRepository()
    orig_create = repo.create

    async def create_with_linking(*args: Any, **kwargs: Any) -> ProcessingJob:
        job = await orig_create(*args, **kwargs)
        if job.meeting_id in mock_meeting_repo.storage:
            mock_meeting_repo.storage[job.meeting_id].job = job
        return job

    repo.create = create_with_linking  # type: ignore[assignment]
    return repo


@pytest.fixture
def test_app(
    mock_storage: MockStorageProvider,
    mock_meeting_repo: InMemoryMeetingRepository,
    mock_recording_repo: InMemoryRecordingRepository,
    mock_job_repo: InMemoryJobRepository,
) -> Any:
    app = create_app()
    test_settings = Settings(
        JWT_ISSUER="https://auth.example.com",
        JWT_AUDIENCE="authenticated",
        JWT_ALGORITHMS=["HS256"],
        JWT_SIGNING_KEY_OR_JWKS=TEST_JWT_SECRET,
        STORAGE_PRESIGNED_UPLOAD_EXPIRY_SECONDS=900,
    )
    app.dependency_overrides[get_settings] = lambda: test_settings
    app.dependency_overrides[get_storage_provider] = lambda: mock_storage
    app.dependency_overrides[get_meeting_repository] = lambda: mock_meeting_repo
    app.dependency_overrides[get_recording_repository] = lambda: mock_recording_repo
    app.dependency_overrides[get_job_repository] = lambda: mock_job_repo
    return app


@pytest.fixture
def client(test_app: Any) -> TestClient:
    return TestClient(test_app)


def test_complete_upload_and_confirmation_flow(
    client: TestClient,
    mock_storage: MockStorageProvider,
) -> None:
    user_id = uuid.uuid4()
    token = make_token(user_id)
    auth_headers = {"Authorization": f"Bearer {token}", "X-Request-ID": "req-123"}

    # 1. Step 1: POST /api/v1/meetings
    create_payload = {
        "title": "Weekly Sprint Planning",
        "description": "Discussion on Q4 backend refactoring",
        "meeting_date": "2026-10-09",
        "filename": "sprint_planning.mp4",
        "content_type": "video/mp4",
        "file_size_bytes": 145000000,
    }
    create_res = client.post("/api/v1/meetings", json=create_payload, headers=auth_headers)
    assert create_res.status_code == 201
    res_json = create_res.json()
    assert "data" in res_json
    data = res_json["data"]
    meeting_id = data["meeting_id"]
    recording_id = data["recording_id"]
    upload_url = data["upload_url"]
    upload_token = data["upload_token"]
    assert data["status"] == "CREATED"
    assert "mock-r2.cloudflarestorage.com" in upload_url
    assert data["expires_in_seconds"] == 900
    assert res_json["meta"]["request_id"] == "req-123"

    # Verify storage key structure in generated presigned URL
    expected_storage_key = f"users/{user_id}/recordings/{recording_id}/sprint_planning.mp4"
    assert expected_storage_key in upload_url

    # 2. Simulate client uploading binary directly to R2 (not through FastAPI)
    mock_storage.objects.add(expected_storage_key)

    # 3. Step 2: POST /api/v1/meetings/{id}/confirm-upload
    with patch("app.services.upload_service.celery_app.send_task") as mock_celery:
        mock_task = MagicMock()
        mock_task.id = "mock-celery-task-id-123"
        mock_celery.return_value = mock_task

        confirm_payload = {
            "recording_id": recording_id,
            "upload_token": upload_token,
        }
        confirm_res = client.post(
            f"/api/v1/meetings/{meeting_id}/confirm-upload",
            json=confirm_payload,
            headers=auth_headers,
        )
        assert confirm_res.status_code == 202
        confirm_json = confirm_res.json()
        confirm_data = confirm_json["data"]
        assert confirm_data["meeting_id"] == meeting_id
        assert confirm_data["status"] == "ACTIVE"
        assert confirm_data["job_status"] == "PENDING"
        assert "job_id" in confirm_data

        # Celery task dispatched with late acks task name
        mock_celery.assert_called_once_with(
            "process_meeting_recording",
            args=[confirm_data["job_id"], meeting_id],
        )

    # 4. Step 3: GET /api/v1/meetings/{id} detail
    get_res = client.get(f"/api/v1/meetings/{meeting_id}", headers=auth_headers)
    assert get_res.status_code == 200
    get_json = get_res.json()
    meeting_detail = get_json["data"]
    assert meeting_detail["meeting_id"] == meeting_id
    assert meeting_detail["status"] == "ACTIVE"
    assert meeting_detail["recording"]["recording_id"] == recording_id
    assert meeting_detail["recording"]["status"] == "UPLOADED"
    assert meeting_detail["job"]["status"] == "PENDING"


def test_upload_confirmation_fails_if_binary_not_in_storage(
    client: TestClient,
    mock_storage: MockStorageProvider,
) -> None:
    user_id = uuid.uuid4()
    token = make_token(user_id)
    auth_headers = {"Authorization": f"Bearer {token}"}

    create_payload = {
        "title": "Meeting with missing binary",
        "filename": "missing.mp3",
        "content_type": "audio/mpeg",
        "file_size_bytes": 1000000,
    }
    create_res = client.post("/api/v1/meetings", json=create_payload, headers=auth_headers)
    assert create_res.status_code == 201
    data = create_res.json()["data"]

    # Do NOT add object to storage -> confirmation must fail with 409 CONFLICT
    confirm_res = client.post(
        f"/api/v1/meetings/{data['meeting_id']}/confirm-upload",
        json={"recording_id": data["recording_id"], "upload_token": data["upload_token"]},
        headers=auth_headers,
    )
    assert confirm_res.status_code == 409
    error_json = confirm_res.json()
    assert error_json["error"]["code"] == "CONFLICT"


def test_invalid_content_type_rejected(client: TestClient) -> None:
    user_id = uuid.uuid4()
    token = make_token(user_id)
    auth_headers = {"Authorization": f"Bearer {token}"}

    create_payload = {
        "title": "Executable Upload",
        "filename": "malicious.exe",
        "content_type": "application/x-dosexec",
        "file_size_bytes": 1000,
    }
    res = client.post("/api/v1/meetings", json=create_payload, headers=auth_headers)
    assert res.status_code == 422
    err = res.json()["error"]
    assert err["code"] == "VALIDATION_ERROR"


def test_oversized_file_rejected(client: TestClient) -> None:
    user_id = uuid.uuid4()
    token = make_token(user_id)
    auth_headers = {"Authorization": f"Bearer {token}"}

    create_payload = {
        "title": "Huge Video",
        "filename": "huge.mp4",
        "content_type": "video/mp4",
        "file_size_bytes": 524_288_001,  # Exceeds 500 MB limit
    }
    res = client.post("/api/v1/meetings", json=create_payload, headers=auth_headers)
    assert res.status_code == 422
    err = res.json()["error"]
    assert err["code"] == "VALIDATION_ERROR"


def test_unauthenticated_requests_rejected(client: TestClient) -> None:
    res = client.post(
        "/api/v1/meetings",
        json={
            "title": "No Auth",
            "filename": "test.mp3",
            "content_type": "audio/mpeg",
            "file_size_bytes": 1000,
        },
    )
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "UNAUTHORIZED"


def test_cross_user_isolation_anti_enumeration(
    client: TestClient,
    mock_storage: MockStorageProvider,
) -> None:
    user_a = uuid.uuid4()
    user_b = uuid.uuid4()
    token_a = make_token(user_a)
    token_b = make_token(user_b)

    # User A creates a meeting
    create_res = client.post(
        "/api/v1/meetings",
        json={
            "title": "User A Private Meeting",
            "filename": "secret.wav",
            "content_type": "audio/wav",
            "file_size_bytes": 2000,
        },
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert create_res.status_code == 201
    meeting_id = create_res.json()["data"]["meeting_id"]

    # User B queries User A's meeting -> 404 NOT FOUND (anti-enumeration)
    get_res = client.get(
        f"/api/v1/meetings/{meeting_id}",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert get_res.status_code == 404
    assert get_res.json()["error"]["code"] == "NOT_FOUND"

    # User B attempts to delete User A's meeting -> 404 NOT FOUND
    del_res = client.delete(
        f"/api/v1/meetings/{meeting_id}",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert del_res.status_code == 404


def test_meeting_deletion_cascades_cleanly_to_storage(
    client: TestClient,
    mock_storage: MockStorageProvider,
) -> None:
    user_id = uuid.uuid4()
    token = make_token(user_id)
    auth_headers = {"Authorization": f"Bearer {token}"}

    create_res = client.post(
        "/api/v1/meetings",
        json={
            "title": "Meeting To Delete",
            "filename": "delete_me.mp4",
            "content_type": "video/mp4",
            "file_size_bytes": 5000,
        },
        headers=auth_headers,
    )
    meeting_id = create_res.json()["data"]["meeting_id"]
    recording_id = create_res.json()["data"]["recording_id"]
    storage_key = f"users/{user_id}/recordings/{recording_id}/delete_me.mp4"

    # Add object in storage
    mock_storage.objects.add(storage_key)
    assert mock_storage.object_exists(storage_key) is True

    # DELETE /api/v1/meetings/{id}
    del_res = client.delete(f"/api/v1/meetings/{meeting_id}", headers=auth_headers)
    assert del_res.status_code == 204

    # Storage object must be purged
    assert mock_storage.object_exists(storage_key) is False

    # Meeting must return 404 now
    get_res = client.get(f"/api/v1/meetings/{meeting_id}", headers=auth_headers)
    assert get_res.status_code == 404


def test_storage_failure_during_upload_returns_502(
    client: TestClient,
    mock_storage: MockStorageProvider,
) -> None:
    user_id = uuid.uuid4()
    token = make_token(user_id)
    auth_headers = {"Authorization": f"Bearer {token}"}

    with patch.object(
        mock_storage,
        "generate_presigned_upload_url",
        side_effect=Exception("R2 timeout"),
    ):
        res = client.post(
            "/api/v1/meetings",
            json={
                "title": "Failing Meeting",
                "filename": "fail.mp3",
                "content_type": "audio/mpeg",
                "file_size_bytes": 1000,
            },
            headers=auth_headers,
        )
        assert res.status_code == 502
        assert res.json()["error"]["code"] == "STORAGE_ERROR"


def test_celery_dispatch_failure_returns_500(
    client: TestClient,
    mock_storage: MockStorageProvider,
) -> None:
    user_id = uuid.uuid4()
    token = make_token(user_id)
    auth_headers = {"Authorization": f"Bearer {token}"}

    create_res = client.post(
        "/api/v1/meetings",
        json={
            "title": "Celery Broker Down",
            "filename": "broker_down.mp3",
            "content_type": "audio/mpeg",
            "file_size_bytes": 1000,
        },
        headers=auth_headers,
    )
    data = create_res.json()["data"]
    storage_key = f"users/{user_id}/recordings/{data['recording_id']}/broker_down.mp3"
    mock_storage.objects.add(storage_key)

    with patch(
        "app.services.upload_service.celery_app.send_task",
        side_effect=Exception("Redis connection refused"),
    ):
        confirm_res = client.post(
            f"/api/v1/meetings/{data['meeting_id']}/confirm-upload",
            json={"recording_id": data["recording_id"], "upload_token": data["upload_token"]},
            headers=auth_headers,
        )
        assert confirm_res.status_code == 500
        assert confirm_res.json()["error"]["code"] == "INTERNAL_ERROR"
