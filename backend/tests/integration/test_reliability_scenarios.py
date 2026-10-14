import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.exc import OperationalError

from app.models.meeting import Meeting, MeetingStatus
from app.models.processing_job import JobStage, JobStatus, ProcessingJob
from app.models.recording import Recording, RecordingStatus
from app.services.processing_service import ProcessingPipelineError, ProcessingService
from app.workers.job_lease import JobLeaseTracker


@pytest.mark.asyncio
async def test_worker_crash_stale_lease_recovery_scenario() -> None:
    """Scenario RS-02 & SC-08: Celery worker crashes or dies abruptly mid-task.

    A secondary healthy worker reclaims the stale lease after expiration,
    increments the attempt counter, and resumes/executes the processing pipeline.
    """
    session = AsyncMock()
    user_id = uuid.uuid4()
    meeting_id = uuid.uuid4()
    job_id = uuid.uuid4()

    # Simulate crashed worker's expired job
    expired_lease_time = datetime.now(UTC) - timedelta(minutes=5)
    stale_job = ProcessingJob(
        id=job_id,
        meeting_id=meeting_id,
        user_id=user_id,
        status=JobStatus.RUNNING,
        stage=JobStage.TRANSCRIBING,
        worker_id="crashed-worker-pod-99",
        lease_expires_at=expired_lease_time,
        attempt=1,
        max_attempts=3,
    )

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = stale_job
    session.execute.return_value = mock_result

    tracker = JobLeaseTracker(session, lease_duration_seconds=120)
    surviving_worker_id = "surviving-worker-pod-01"

    # Reclaim stale job
    claimed = await tracker.claim_job(job_id=job_id, worker_id=surviving_worker_id)
    assert claimed is not None
    assert claimed.worker_id == surviving_worker_id
    assert claimed.status == JobStatus.RUNNING
    assert claimed.attempt == 2
    assert claimed.lease_expires_at is not None
    assert claimed.lease_expires_at > datetime.now(UTC)


@pytest.mark.asyncio
async def test_database_temporary_disconnect_and_reconnect() -> None:
    """Scenario: Database connection drops transiently during lease renewal or query.

    System handles transient OperationalError and succeeds on reconnect.
    """
    session = AsyncMock()
    job_id = uuid.uuid4()
    worker_id = "worker-db-test"

    tracker = JobLeaseTracker(session, lease_duration_seconds=120)

    # First attempt raises transient database connection error
    # Second attempt succeeds
    mock_result = MagicMock()
    mock_job = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_job

    session.execute.side_effect = [
        OperationalError("connection closed unexpectedly", None, None),
        mock_result,
    ]

    with pytest.raises(OperationalError):
        await tracker.renew_heartbeat(job_id=job_id, worker_id=worker_id)

    # Reconnected session succeeds
    reconnected_success = await tracker.renew_heartbeat(job_id=job_id, worker_id=worker_id)
    assert reconnected_success is True


@pytest.mark.asyncio
async def test_storage_timeout_resilience() -> None:
    """Scenario: Object storage (R2/S3) download times out during worker ingestion.

    Pipeline wraps as retryable error and marks job as PENDING for Celery requeue.
    """
    job_repo = MagicMock()
    meeting_repo = MagicMock()
    recording_repo = MagicMock()
    transcript_repo = MagicMock()
    storage_provider = MagicMock()
    audio_service = MagicMock()
    transcription_provider = MagicMock()
    settings = MagicMock()

    user_id = uuid.uuid4()
    meeting_id = uuid.uuid4()
    job_id = uuid.uuid4()
    recording_id = uuid.uuid4()

    job = ProcessingJob(
        id=job_id,
        meeting_id=meeting_id,
        user_id=user_id,
        status=JobStatus.RUNNING,
        stage=JobStage.VALIDATING,
        attempt=1,
        max_attempts=3,
    )
    meeting = Meeting(id=meeting_id, user_id=user_id, title="Test", status=MeetingStatus.ACTIVE)
    recording = Recording(
        id=recording_id,
        meeting_id=meeting_id,
        user_id=user_id,
        storage_key="test.mp4",
        original_filename="test.mp4",
        content_type="video/mp4",
        file_size_bytes=1000,
        status=RecordingStatus.UPLOADED,
    )

    job_repo.get_by_id_system = AsyncMock(return_value=job)
    meeting_repo.get_by_id_system = AsyncMock(return_value=meeting)
    recording_repo.get_by_meeting_id_system = AsyncMock(return_value=recording)
    transcript_repo.get_by_meeting_id = AsyncMock(return_value=None)
    job_repo.update_stage = AsyncMock()

    lease_tracker = MagicMock(spec=JobLeaseTracker)
    lease_tracker.claim_job = AsyncMock(return_value=job)
    lease_tracker.renew_heartbeat = AsyncMock(return_value=True)
    lease_tracker.release_lease = AsyncMock()

    # Simulate storage timeout exception
    storage_provider.download_file.side_effect = TimeoutError("R2 connection timed out")

    service = ProcessingService(
        job_repo=job_repo,
        meeting_repo=meeting_repo,
        recording_repo=recording_repo,
        transcript_repo=transcript_repo,
        storage_provider=storage_provider,
        audio_service=audio_service,
        transcription_provider=transcription_provider,
        settings=settings,
    )

    with pytest.raises(ProcessingPipelineError) as exc_info:
        await service.execute_job(
            job_id=job_id,
            meeting_id=meeting_id,
            worker_id="worker-timeout-test",
            lease_tracker=lease_tracker,
        )

    # Storage errors are retryable
    assert exc_info.value.is_retryable is True
    assert exc_info.value.error_code == "STORAGE_DOWNLOAD_FAILED"
    # Released lease with target_status PENDING for retry
    lease_tracker.release_lease.assert_awaited_once()
    assert lease_tracker.release_lease.call_args.kwargs["target_status"] == JobStatus.PENDING


@pytest.mark.asyncio
async def test_provider_429_rate_limit_exponential_backoff_handling() -> None:
    """Scenario RS-03: STT or LLM Provider responds with 429 Rate Limit.

    Processing pipeline catches 429, flags as retryable, and Celery tasks module
    triggers retry with exponential countdown.
    """
    job_repo = MagicMock()
    meeting_repo = MagicMock()
    recording_repo = MagicMock()
    transcript_repo = MagicMock()
    storage_provider = MagicMock()
    audio_service = MagicMock()
    transcription_provider = MagicMock()
    settings = MagicMock()

    user_id = uuid.uuid4()
    meeting_id = uuid.uuid4()
    job_id = uuid.uuid4()
    recording_id = uuid.uuid4()

    job = ProcessingJob(
        id=job_id,
        meeting_id=meeting_id,
        user_id=user_id,
        status=JobStatus.RUNNING,
        stage=JobStage.VALIDATING,
        attempt=1,
        max_attempts=3,
    )
    meeting = Meeting(
        id=meeting_id, user_id=user_id, title="Rate Limit", status=MeetingStatus.ACTIVE
    )
    recording = Recording(
        id=recording_id,
        meeting_id=meeting_id,
        user_id=user_id,
        storage_key="test.mp3",
        original_filename="test.mp3",
        content_type="audio/mpeg",
        file_size_bytes=1000,
        status=RecordingStatus.UPLOADED,
    )

    job_repo.get_by_id_system = AsyncMock(return_value=job)
    meeting_repo.get_by_id_system = AsyncMock(return_value=meeting)
    recording_repo.get_by_meeting_id_system = AsyncMock(return_value=recording)
    transcript_repo.get_by_meeting_id = AsyncMock(return_value=None)
    job_repo.update_stage = AsyncMock()

    lease_tracker = MagicMock(spec=JobLeaseTracker)
    lease_tracker.claim_job = AsyncMock(return_value=job)
    lease_tracker.renew_heartbeat = AsyncMock(return_value=True)
    lease_tracker.release_lease = AsyncMock()

    storage_provider.download_file.return_value = "/tmp/fake.mp3"
    audio_service.validate_media_file.return_value = {"duration": 60.0}
    audio_service.convert_to_wav_16k_mono.return_value = "/tmp/fake.wav"

    from app.providers.transcription.base import TranscriptionProviderError

    # Simulate Groq 429 rate limit
    transcription_provider.transcribe.side_effect = TranscriptionProviderError(
        "Rate limit exceeded (HTTP 429)", is_retryable=True
    )

    service = ProcessingService(
        job_repo=job_repo,
        meeting_repo=meeting_repo,
        recording_repo=recording_repo,
        transcript_repo=transcript_repo,
        storage_provider=storage_provider,
        audio_service=audio_service,
        transcription_provider=transcription_provider,
        settings=settings,
    )

    with pytest.raises(ProcessingPipelineError) as exc_info:
        await service.execute_job(
            job_id=job_id,
            meeting_id=meeting_id,
            worker_id="worker-rate-limit-test",
            lease_tracker=lease_tracker,
        )

    assert exc_info.value.is_retryable is True
    assert exc_info.value.error_code == "TRANSCRIPTION_FAILED"
    # Retains retryable state in lease release
    assert lease_tracker.release_lease.call_args.kwargs["target_status"] == JobStatus.PENDING
