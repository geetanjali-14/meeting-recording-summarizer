import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user, get_meeting_service
from app.core.security import UserContext
from app.main import create_app
from app.models.meeting import Meeting, MeetingStatus
from app.models.processing_job import JobStage, JobStatus, ProcessingJob
from app.models.recording import Recording, RecordingStatus
from app.services.meeting_service import MeetingNotFoundError, MeetingService, StorageError


@pytest.fixture
def owner_user_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def non_owner_user_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def owner_user_context(owner_user_id: uuid.UUID) -> UserContext:
    return UserContext(
        user_id=owner_user_id,
        email="owner@example.com",
        role="authenticated",
    )


@pytest.fixture
def non_owner_user_context(non_owner_user_id: uuid.UUID) -> UserContext:
    return UserContext(
        user_id=non_owner_user_id,
        email="other@example.com",
        role="authenticated",
    )


@pytest.mark.asyncio
async def test_delete_meeting_success(owner_user_context: UserContext) -> None:
    """Owner can delete a meeting: returns 204 No Content."""
    app = create_app()
    meeting_id = uuid.uuid4()

    mock_service = AsyncMock(spec=MeetingService)
    mock_service.delete_meeting.return_value = None

    app.dependency_overrides[get_current_user] = lambda: owner_user_context
    app.dependency_overrides[get_meeting_service] = lambda: mock_service

    client = TestClient(app)
    response = client.delete(f"/api/v1/meetings/{meeting_id}")

    assert response.status_code == 204
    mock_service.delete_meeting.assert_awaited_once_with(
        meeting_id=meeting_id,
        user_id=owner_user_context.user_id,
    )


@pytest.mark.asyncio
async def test_delete_meeting_unauthenticated_rejected() -> None:
    """Unauthenticated requests are rejected with 401."""
    app = create_app()
    meeting_id = uuid.uuid4()

    client = TestClient(app)
    response = client.delete(f"/api/v1/meetings/{meeting_id}")

    assert response.status_code == 401
    body = response.json()
    assert body["error"]["code"] == "UNAUTHORIZED" or response.status_code == 401


@pytest.mark.asyncio
async def test_delete_meeting_non_owner_returns_404(
    non_owner_user_context: UserContext,
) -> None:
    """Non-owner requests return 404 (IDOR anti-enumeration defense)."""
    app = create_app()
    meeting_id = uuid.uuid4()

    mock_service = AsyncMock(spec=MeetingService)
    mock_service.delete_meeting.side_effect = MeetingNotFoundError()

    app.dependency_overrides[get_current_user] = lambda: non_owner_user_context
    app.dependency_overrides[get_meeting_service] = lambda: mock_service

    client = TestClient(app)
    response = client.delete(f"/api/v1/meetings/{meeting_id}")

    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "NOT_FOUND"


@pytest.mark.asyncio
async def test_delete_missing_meeting_returns_404(owner_user_context: UserContext) -> None:
    """Deleting a non-existent recording returns 404."""
    app = create_app()
    missing_id = uuid.uuid4()

    mock_service = AsyncMock(spec=MeetingService)
    mock_service.delete_meeting.side_effect = MeetingNotFoundError()

    app.dependency_overrides[get_current_user] = lambda: owner_user_context
    app.dependency_overrides[get_meeting_service] = lambda: mock_service

    client = TestClient(app)
    response = client.delete(f"/api/v1/meetings/{missing_id}")

    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "NOT_FOUND"


@pytest.mark.asyncio
async def test_repeated_deletion_idempotency_and_404(owner_user_context: UserContext) -> None:
    """Repeated deletion request returns 404 after initial successful deletion."""
    app = create_app()
    meeting_id = uuid.uuid4()

    mock_service = AsyncMock(spec=MeetingService)
    # First call succeeds, second call raises MeetingNotFoundError
    mock_service.delete_meeting.side_effect = [None, MeetingNotFoundError()]

    app.dependency_overrides[get_current_user] = lambda: owner_user_context
    app.dependency_overrides[get_meeting_service] = lambda: mock_service

    client = TestClient(app)
    first_res = client.delete(f"/api/v1/meetings/{meeting_id}")
    assert first_res.status_code == 204

    second_res = client.delete(f"/api/v1/meetings/{meeting_id}")
    assert second_res.status_code == 404
    assert second_res.json()["error"]["code"] == "NOT_FOUND"


@pytest.mark.asyncio
async def test_delete_storage_failure_returns_502(owner_user_context: UserContext) -> None:
    """Storage deletion failure returns 502 STORAGE_ERROR and preserves retryability."""
    app = create_app()
    meeting_id = uuid.uuid4()

    mock_service = AsyncMock(spec=MeetingService)
    mock_service.delete_meeting.side_effect = StorageError("R2 connection timeout")

    app.dependency_overrides[get_current_user] = lambda: owner_user_context
    app.dependency_overrides[get_meeting_service] = lambda: mock_service

    client = TestClient(app)
    response = client.delete(f"/api/v1/meetings/{meeting_id}")

    assert response.status_code == 502
    body = response.json()
    assert body["error"]["code"] == "STORAGE_ERROR"
    assert "R2 connection timeout" in body["error"]["message"]


@pytest.mark.asyncio
async def test_meeting_service_delete_lifecycle_with_storage_and_celery() -> None:
    """Tests the MeetingService delete_meeting workflow with storage deletion and task revoking."""
    meeting_id = uuid.uuid4()
    user_id = uuid.uuid4()
    storage_key = f"recordings/{user_id}/{meeting_id}.mp4"

    mock_recording = Recording(
        id=uuid.uuid4(),
        meeting_id=meeting_id,
        user_id=user_id,
        storage_key=storage_key,
        original_filename="demo.mp4",
        content_type="video/mp4",
        file_size_bytes=1000,
        status=RecordingStatus.UPLOADED,
    )
    mock_job = ProcessingJob(
        id=uuid.uuid4(),
        meeting_id=meeting_id,
        user_id=user_id,
        celery_task_id="celery-task-999",
        status=JobStatus.RUNNING,
        stage=JobStage.TRANSCRIBING,
        attempt=1,
    )
    mock_meeting = Meeting(
        id=meeting_id,
        user_id=user_id,
        title="Architecture Discussion",
        status=MeetingStatus.ACTIVE,
    )
    mock_meeting.recording = mock_recording
    mock_meeting.job = mock_job

    mock_repo = AsyncMock()
    mock_repo.get_by_id.return_value = mock_meeting
    mock_repo.mark_deleting.return_value = mock_meeting
    mock_repo.delete.return_value = True

    mock_storage = MagicMock()

    service = MeetingService(meeting_repo=mock_repo, storage_provider=mock_storage)

    with patch("app.core.celery_app.celery_app.control.revoke") as mock_revoke:
        await service.delete_meeting(meeting_id=meeting_id, user_id=user_id)

        # 1. Verification of mark_deleting
        mock_repo.mark_deleting.assert_awaited_once_with(meeting_id=meeting_id, user_id=user_id)
        # 2. Verification of Celery revocation
        mock_revoke.assert_called_once_with("celery-task-999", terminate=True)
        # 3. Verification of R2 deletion
        mock_storage.delete_object.assert_called_once_with(storage_key)
        # 4. Verification of database cascade delete
        mock_repo.delete.assert_awaited_once_with(meeting_id=meeting_id, user_id=user_id)


@pytest.mark.asyncio
async def test_meeting_service_delete_retry_from_deleting_state() -> None:
    """When a previous attempt failed on storage and left meeting in DELETING, retry proceeds."""
    meeting_id = uuid.uuid4()
    user_id = uuid.uuid4()
    storage_key = f"recordings/{user_id}/{meeting_id}.mp4"

    mock_recording = Recording(
        id=uuid.uuid4(),
        meeting_id=meeting_id,
        user_id=user_id,
        storage_key=storage_key,
        original_filename="demo.mp4",
        content_type="video/mp4",
        file_size_bytes=1000,
        status=RecordingStatus.UPLOADED,
    )
    mock_meeting = Meeting(
        id=meeting_id,
        user_id=user_id,
        title="Retryable Delete",
        status=MeetingStatus.DELETING,  # Already DELETING
    )
    mock_meeting.recording = mock_recording
    mock_meeting.job = None

    mock_repo = AsyncMock()
    mock_repo.get_by_id.return_value = mock_meeting
    mock_repo.delete.return_value = True

    mock_storage = MagicMock()

    service = MeetingService(meeting_repo=mock_repo, storage_provider=mock_storage)

    await service.delete_meeting(meeting_id=meeting_id, user_id=user_id)

    # Should not re-mark DELETING
    mock_repo.mark_deleting.assert_not_awaited()
    # Should delete from storage and cascade DB
    mock_storage.delete_object.assert_called_once_with(storage_key)
    mock_repo.delete.assert_awaited_once_with(meeting_id=meeting_id, user_id=user_id)


@pytest.mark.asyncio
async def test_worker_aborts_when_meeting_is_deleting() -> None:
    """Worker detects DELETING status and safely marks job CANCELLED without race."""
    from app.services.processing_service import ProcessingPipelineError, ProcessingService

    meeting_id = uuid.uuid4()
    job_id = uuid.uuid4()
    user_id = uuid.uuid4()

    mock_meeting_repo = AsyncMock()
    # Return meeting in DELETING state
    deleting_meeting = Meeting(
        id=meeting_id,
        user_id=user_id,
        title="Deleting Meeting",
        status=MeetingStatus.DELETING,
    )
    mock_meeting_repo.get_by_id_system.return_value = deleting_meeting

    mock_job_repo = AsyncMock()
    mock_recording_repo = AsyncMock()
    mock_transcript_repo = AsyncMock()
    mock_storage = MagicMock()
    mock_audio = MagicMock()
    mock_transcription = MagicMock()
    mock_settings = MagicMock()
    mock_lease = AsyncMock()

    # Worker claimed job
    job = ProcessingJob(
        id=job_id,
        meeting_id=meeting_id,
        user_id=user_id,
        status=JobStatus.RUNNING,
        stage=JobStage.VALIDATING,
        attempt=1,
    )
    mock_lease.claim_job.return_value = job

    proc_service = ProcessingService(
        job_repo=mock_job_repo,
        meeting_repo=mock_meeting_repo,
        recording_repo=mock_recording_repo,
        transcript_repo=mock_transcript_repo,
        storage_provider=mock_storage,
        audio_service=mock_audio,
        transcription_provider=mock_transcription,
        settings=mock_settings,
    )

    with pytest.raises(ProcessingPipelineError) as exc_info:
        await proc_service.execute_job(
            job_id=job_id,
            meeting_id=meeting_id,
            worker_id="test_worker_1",
            lease_tracker=mock_lease,
        )

    assert exc_info.value.error_code == "MEETING_DELETED"
    assert exc_info.value.is_retryable is False
    # Verified lease was released as CANCELLED
    mock_lease.release_lease.assert_awaited_once_with(
        job_id=job_id,
        worker_id="test_worker_1",
        target_status=JobStatus.CANCELLED,
        target_stage=JobStage.FAILED,
        error_code="MEETING_DELETED",
        error_message=exc_info.value.message,
    )
