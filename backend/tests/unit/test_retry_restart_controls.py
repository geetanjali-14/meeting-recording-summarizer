import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import Request

from app.api.v1.status import retry_processing_job, restart_processing_job
from app.core.security import UserContext
from app.models.meeting import Meeting, MeetingStatus
from app.models.meeting_analysis import MeetingAnalysis
from app.models.processing_job import JobStage, JobStatus, ProcessingJob
from app.models.transcript import Transcript, TranscriptSegment
from app.services.processing_service import ProcessingService
from app.workers.job_lease import JobLeaseTracker


@pytest.mark.asyncio
async def test_retry_skips_transcription_when_valid_transcript_segments_exist() -> None:
    """Retry must resume from ANALYZING, reusing existing transcript segments without calling transcription."""
    user_id = uuid.uuid4()
    meeting_id = uuid.uuid4()
    job_id = uuid.uuid4()

    job = ProcessingJob(
        id=job_id,
        meeting_id=meeting_id,
        user_id=user_id,
        status=JobStatus.RUNNING,
        stage=JobStage.ANALYZING,
        attempt=1,
    )
    meeting = Meeting(id=meeting_id, user_id=user_id, title="Test Meeting", status=MeetingStatus.ACTIVE)
    recording = MagicMock(original_filename="audio.wav", storage_key="recordings/audio.wav")

    # Existing transcript with segments
    transcript = Transcript(
        id=uuid.uuid4(),
        meeting_id=meeting_id,
        user_id=user_id,
        provider="groq_whisper",
        segment_count=2,
    )
    db_segment1 = TranscriptSegment(
        id=uuid.uuid4(),
        transcript_id=transcript.id,
        meeting_id=meeting_id,
        sequence_index=0,
        start_time=0.0,
        end_time=5.0,
        text="Hello team",
    )
    db_segment2 = TranscriptSegment(
        id=uuid.uuid4(),
        transcript_id=transcript.id,
        meeting_id=meeting_id,
        sequence_index=1,
        start_time=5.0,
        end_time=10.0,
        text="Let's review the plan",
    )

    # Mocks
    job_repo = AsyncMock()
    meeting_repo = AsyncMock()
    meeting_repo.get_by_id_system.return_value = meeting
    recording_repo = AsyncMock()
    recording_repo.get_by_meeting_id_system.return_value = recording

    transcript_repo = AsyncMock()
    transcript_repo.get_by_meeting_id.return_value = transcript
    transcript_repo.get_segments_by_transcript.return_value = [db_segment1, db_segment2]

    storage_provider = MagicMock()
    audio_service = MagicMock()
    transcription_provider = MagicMock()

    analysis_repo = AsyncMock()
    # Analysis not yet complete
    analysis_repo.get_by_meeting_id.return_value = None

    analysis_service = MagicMock()
    analysis_service.analysis_repo = analysis_repo
    analysis_service.execute_analysis = AsyncMock()

    lease_tracker = AsyncMock(spec=JobLeaseTracker)
    lease_tracker.claim_job.return_value = job
    lease_tracker.release_lease.return_value = job

    service = ProcessingService(
        job_repo=job_repo,
        meeting_repo=meeting_repo,
        recording_repo=recording_repo,
        transcript_repo=transcript_repo,
        storage_provider=storage_provider,
        audio_service=audio_service,
        transcription_provider=transcription_provider,
        settings=MagicMock(),
        analysis_service=analysis_service,
    )

    completed_job = await service.execute_job(
        job_id=job_id,
        meeting_id=meeting_id,
        worker_id="worker-test",
        lease_tracker=lease_tracker,
    )

    # Assertions
    # 1. Audio and Whisper transcription were NOT called!
    storage_provider.download_file.assert_not_called()
    audio_service.convert_to_wav_16k_mono.assert_not_called()
    transcription_provider.transcribe.assert_not_called()

    # 2. Resumed directly into analysis
    job_repo.update_stage.assert_any_call(job=job, stage=JobStage.ANALYZING)
    analysis_service.execute_analysis.assert_called_once()
    assert analysis_service.execute_analysis.call_args.kwargs["segments"] == [db_segment1, db_segment2]

    # 3. Completed lease release
    lease_tracker.release_lease.assert_called_once_with(
        job_id=job_id,
        worker_id="worker-test",
        target_status=JobStatus.COMPLETED,
        target_stage=JobStage.COMPLETED,
    )


@pytest.mark.asyncio
async def test_retry_endpoint_rejects_active_running_job() -> None:
    """POST /meetings/{id}/retry returns 409 Conflict if worker lease is currently active."""
    user_id = uuid.uuid4()
    meeting_id = uuid.uuid4()
    current_user = UserContext(user_id=user_id, email="test@example.com")

    meeting = Meeting(id=meeting_id, user_id=user_id, title="Test", status=MeetingStatus.ACTIVE)
    active_job = ProcessingJob(
        id=uuid.uuid4(),
        meeting_id=meeting_id,
        user_id=user_id,
        status=JobStatus.RUNNING,
        stage=JobStage.TRANSCRIBING,
        lease_expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )

    request = MagicMock(spec=Request)
    request.url.path = f"/api/v1/meetings/{meeting_id}/retry"

    session = AsyncMock()
    with patch("app.api.v1.status.MeetingRepository") as mock_meeting_cls, \
         patch("app.api.v1.status.JobRepository") as mock_job_cls:
        mock_m_repo = AsyncMock()
        mock_m_repo.get_by_id.return_value = meeting
        mock_meeting_cls.return_value = mock_m_repo

        mock_j_repo = AsyncMock()
        mock_j_repo.get_by_meeting_id.return_value = active_job
        mock_job_cls.return_value = mock_j_repo

        response = await retry_processing_job(
            meeting_id=meeting_id,
            request=request,
            current_user=current_user,
            session=session,
        )

        assert response.status_code == 409
        body = response.body.decode()
        assert "JOB_ACTIVE" in body


@pytest.mark.asyncio
async def test_retry_endpoint_enforces_tenant_authorization() -> None:
    """User B cannot retry User A's meeting (returns 404)."""
    user_a = uuid.uuid4()
    user_b = uuid.uuid4()
    meeting_id = uuid.uuid4()
    current_user_b = UserContext(user_id=user_b, email="user_b@example.com")

    request = MagicMock(spec=Request)
    request.url.path = f"/api/v1/meetings/{meeting_id}/retry"

    session = AsyncMock()
    with patch("app.api.v1.status.MeetingRepository") as mock_meeting_cls:
        mock_m_repo = AsyncMock()
        mock_m_repo.get_by_id.return_value = None  # Scoped by user_b -> not found
        mock_meeting_cls.return_value = mock_m_repo

        response = await retry_processing_job(
            meeting_id=meeting_id,
            request=request,
            current_user=current_user_b,
            session=session,
        )

        assert response.status_code == 404


@pytest.mark.asyncio
async def test_retry_endpoint_success_and_celery_dispatch() -> None:
    """Retry on a FAILED job transitions to PENDING and safely dispatches Celery task."""
    user_id = uuid.uuid4()
    meeting_id = uuid.uuid4()
    job_id = uuid.uuid4()
    current_user = UserContext(user_id=user_id, email="test@example.com")

    meeting = Meeting(id=meeting_id, user_id=user_id, title="Test", status=MeetingStatus.ACTIVE)
    failed_job = ProcessingJob(
        id=job_id,
        meeting_id=meeting_id,
        user_id=user_id,
        status=JobStatus.FAILED,
        stage=JobStage.ANALYZING,
        error_code="ANALYSIS_FAILED",
        error_message="LLM timeout",
    )

    request = MagicMock(spec=Request)
    request.url.path = f"/api/v1/meetings/{meeting_id}/retry"

    session = AsyncMock()
    with patch("app.api.v1.status.MeetingRepository") as mock_meeting_cls, \
         patch("app.api.v1.status.JobRepository") as mock_job_cls, \
         patch("app.api.v1.status.celery_app") as mock_celery:
        mock_m_repo = AsyncMock()
        mock_m_repo.get_by_id.return_value = meeting
        mock_meeting_cls.return_value = mock_m_repo

        mock_j_repo = AsyncMock()
        mock_j_repo.get_by_meeting_id.return_value = failed_job
        mock_job_cls.return_value = mock_j_repo

        mock_celery_result = MagicMock(id="celery-task-retry-123")
        mock_celery.send_task.return_value = mock_celery_result

        response = await retry_processing_job(
            meeting_id=meeting_id,
            request=request,
            current_user=current_user,
            session=session,
        )

        assert response.status_code == 200
        assert failed_job.status == JobStatus.PENDING
        assert failed_job.celery_task_id == "celery-task-retry-123"
        assert failed_job.error_code is None
        assert failed_job.error_message is None
        mock_celery.send_task.assert_called_once_with(
            "process_meeting_recording",
            args=[str(job_id), str(meeting_id)],
        )
        session.commit.assert_called_once()


@pytest.mark.asyncio
async def test_restart_endpoint_cleans_artifacts_and_resets_state() -> None:
    """Restart clears existing transcript and analysis records, and resets job to CREATED/PENDING."""
    user_id = uuid.uuid4()
    meeting_id = uuid.uuid4()
    job_id = uuid.uuid4()
    analysis_id = uuid.uuid4()
    transcript_id = uuid.uuid4()
    current_user = UserContext(user_id=user_id, email="test@example.com")

    meeting = Meeting(id=meeting_id, user_id=user_id, title="Test", status=MeetingStatus.ACTIVE)
    completed_or_failed_job = ProcessingJob(
        id=job_id,
        meeting_id=meeting_id,
        user_id=user_id,
        status=JobStatus.COMPLETED,
        stage=JobStage.COMPLETED,
        attempt=2,
    )
    existing_analysis = MeetingAnalysis(id=analysis_id, meeting_id=meeting_id, user_id=user_id, provider="groq", model="gpt-oss-120b")
    existing_transcript = Transcript(id=transcript_id, meeting_id=meeting_id, user_id=user_id, provider="whisper")

    request = MagicMock(spec=Request)
    request.url.path = f"/api/v1/meetings/{meeting_id}/restart"

    session = AsyncMock()
    with patch("app.api.v1.status.MeetingRepository") as mock_meeting_cls, \
         patch("app.api.v1.status.JobRepository") as mock_job_cls, \
         patch("app.api.v1.status.AnalysisRepository") as mock_analysis_cls, \
         patch("app.api.v1.status.TranscriptRepository") as mock_transcript_cls, \
         patch("app.api.v1.status.celery_app") as mock_celery:
        mock_m_repo = AsyncMock()
        mock_m_repo.get_by_id.return_value = meeting
        mock_meeting_cls.return_value = mock_m_repo

        mock_j_repo = AsyncMock()
        mock_j_repo.get_by_meeting_id.return_value = completed_or_failed_job
        mock_job_cls.return_value = mock_j_repo

        mock_a_repo = AsyncMock()
        mock_a_repo.get_by_meeting_id.return_value = existing_analysis
        mock_analysis_cls.return_value = mock_a_repo

        mock_t_repo = AsyncMock()
        mock_t_repo.get_by_meeting_id.return_value = existing_transcript
        mock_transcript_cls.return_value = mock_t_repo

        mock_celery_result = MagicMock(id="celery-task-restart-456")
        mock_celery.send_task.return_value = mock_celery_result

        response = await restart_processing_job(
            meeting_id=meeting_id,
            request=request,
            current_user=current_user,
            session=session,
        )

        assert response.status_code == 200
        # Check deletion of child and top-level artifacts
        mock_a_repo.delete_child_entities.assert_called_once_with(analysis_id)
        mock_t_repo.delete_segments.assert_called_once_with(transcript_id)
        session.delete.assert_any_call(existing_analysis)
        session.delete.assert_any_call(existing_transcript)

        # Check job reset
        assert completed_or_failed_job.status == JobStatus.PENDING
        assert completed_or_failed_job.stage == JobStage.CREATED
        assert completed_or_failed_job.attempt == 0
        assert completed_or_failed_job.celery_task_id == "celery-task-restart-456"
        mock_celery.send_task.assert_called_once_with(
            "process_meeting_recording",
            args=[str(job_id), str(meeting_id)],
        )
