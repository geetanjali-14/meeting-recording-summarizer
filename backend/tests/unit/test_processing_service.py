import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.config import Settings
from app.models.meeting import Meeting, MeetingStatus
from app.models.processing_job import JobStage, JobStatus, ProcessingJob
from app.models.recording import Recording, RecordingStatus
from app.models.transcript import Transcript
from app.providers.storage.base import StorageProvider
from app.providers.transcription.base import (
    TranscriptionProvider,
    TranscriptionProviderError,
    TranscriptionResult,
    TranscriptSegmentResult,
)
from app.repositories.job_repository import JobRepository
from app.repositories.meeting_repository import MeetingRepository
from app.repositories.recording_repository import RecordingRepository
from app.repositories.transcript_repository import TranscriptRepository
from app.services.audio_service import AudioProcessingError, AudioService
from app.services.processing_service import ProcessingPipelineError, ProcessingService
from app.workers.job_lease import JobLeaseTracker


class InMemoryStorageProvider(StorageProvider):
    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}

    def generate_presigned_upload_url(
        self, storage_key: str, content_type: str, expires_in_seconds: int = 900
    ) -> str:
        return f"https://mock/{storage_key}"

    def generate_presigned_download_url(
        self, storage_key: str, expires_in_seconds: int = 3600
    ) -> str:
        return f"https://mock/{storage_key}"

    def delete_object(self, storage_key: str) -> None:
        self.files.pop(storage_key, None)

    def object_exists(self, storage_key: str) -> bool:
        return storage_key in self.files

    def download_file(self, storage_key: str, destination_path: str) -> None:
        if storage_key not in self.files:
            raise RuntimeError(f"Key {storage_key} not found")
        with open(destination_path, "wb") as f:
            f.write(self.files[storage_key])


@pytest.mark.asyncio
async def test_successful_recording_to_transcript_pipeline() -> None:
    session = AsyncMock()
    user_id = uuid.uuid4()
    meeting_id = uuid.uuid4()
    job_id = uuid.uuid4()
    recording_id = uuid.uuid4()

    job = ProcessingJob(
        id=job_id,
        meeting_id=meeting_id,
        user_id=user_id,
        status=JobStatus.PENDING,
        stage=JobStage.CREATED,
        attempt=0,
    )
    meeting = Meeting(
        id=meeting_id, user_id=user_id, title="Sprint Review", status=MeetingStatus.ACTIVE
    )
    recording = Recording(
        id=recording_id,
        meeting_id=meeting_id,
        user_id=user_id,
        storage_key="test/recording.mp4",
        original_filename="recording.mp4",
        content_type="audio/mp4",
        file_size_bytes=1024,
        status=RecordingStatus.UPLOADED,
    )

    # Repositories
    job_repo = JobRepository(session)
    job_repo.get_by_id_system = AsyncMock(return_value=job)
    job_repo.update_stage = AsyncMock(return_value=job)

    meeting_repo = MeetingRepository(session)
    meeting_repo.get_by_id_system = AsyncMock(return_value=meeting)

    recording_repo = RecordingRepository(session)
    recording_repo.get_by_meeting_id_system = AsyncMock(return_value=recording)

    created_transcript = Transcript(
        id=uuid.uuid4(),
        meeting_id=meeting_id,
        user_id=user_id,
        provider="mock",
        language="en",
    )
    transcript_repo = TranscriptRepository(session)
    transcript_repo.get_by_meeting_id = AsyncMock(return_value=None)
    transcript_repo.create_transcript = AsyncMock(return_value=created_transcript)
    transcript_repo.add_segments = AsyncMock(return_value=[])

    # Storage
    storage = InMemoryStorageProvider()
    storage.files["test/recording.mp4"] = b"dummy_audio_bytes"

    # Audio service
    audio_service = AudioService()
    audio_service.validate_media_file = MagicMock(
        return_value={"duration": 15.0, "has_audio": True}
    )
    audio_service.convert_to_wav_16k_mono = MagicMock(return_value="/tmp/test.wav")

    # Transcription provider
    transcription_provider = MagicMock(spec=TranscriptionProvider)
    transcription_provider.transcribe.return_value = TranscriptionResult(
        provider="groq_whisper_turbo",
        model="whisper-large-v3-turbo",
        language="en",
        total_duration_seconds=15.0,
        raw_transcript_text="Let us begin the sprint review.",
        segments=[
            TranscriptSegmentResult(
                sequence_index=0,
                start_time=0.0,
                end_time=5.0,
                text="Let us begin the sprint review.",
                speaker_label="SPEAKER_00",
            )
        ],
    )

    settings = Settings()
    lease_tracker = JobLeaseTracker(session, lease_duration_seconds=120)
    lease_tracker.claim_job = AsyncMock(return_value=job)
    lease_tracker.renew_heartbeat = AsyncMock(return_value=True)
    lease_tracker.release_lease = AsyncMock(return_value=job)

    service = ProcessingService(
        job_repo=job_repo,
        meeting_repo=meeting_repo,
        recording_repo=recording_repo,
        transcript_repo=transcript_repo,
        storage_provider=storage,
        audio_service=audio_service,
        transcription_provider=transcription_provider,
        settings=settings,
    )

    result_job = await service.execute_job(
        job_id=job_id,
        meeting_id=meeting_id,
        worker_id="worker-test-1",
        lease_tracker=lease_tracker,
    )

    assert result_job is not None
    # Verify stages updated
    assert job_repo.update_stage.await_count >= 3
    # Verify transcript created and segments added
    transcript_repo.create_transcript.assert_awaited_once()
    transcript_repo.add_segments.assert_awaited_once()
    # Verify lease released as COMPLETED
    lease_tracker.release_lease.assert_awaited_with(
        job_id=job_id,
        worker_id="worker-test-1",
        target_status=JobStatus.COMPLETED,
        target_stage=JobStage.COMPLETED,
    )


@pytest.mark.asyncio
async def test_pipeline_idempotency_checkpoint() -> None:
    session = AsyncMock()
    user_id = uuid.uuid4()
    meeting_id = uuid.uuid4()
    job_id = uuid.uuid4()

    job = ProcessingJob(
        id=job_id,
        meeting_id=meeting_id,
        user_id=user_id,
        status=JobStatus.PENDING,
        stage=JobStage.CREATED,
    )
    meeting = Meeting(
        id=meeting_id, user_id=user_id, title="Sprint Review", status=MeetingStatus.ACTIVE
    )
    existing_transcript = Transcript(
        id=uuid.uuid4(),
        meeting_id=meeting_id,
        user_id=user_id,
        provider="mock",
        segment_count=5,
    )

    job_repo = JobRepository(session)
    meeting_repo = MeetingRepository(session)
    meeting_repo.get_by_id_system = AsyncMock(return_value=meeting)
    recording_repo = RecordingRepository(session)
    recording_repo.get_by_meeting_id_system = AsyncMock(return_value=MagicMock())

    transcript_repo = TranscriptRepository(session)
    transcript_repo.get_by_meeting_id = AsyncMock(return_value=existing_transcript)

    storage = InMemoryStorageProvider()
    audio_service = AudioService()
    transcription_provider = MagicMock()

    lease_tracker = JobLeaseTracker(session, lease_duration_seconds=120)
    lease_tracker.claim_job = AsyncMock(return_value=job)
    lease_tracker.release_lease = AsyncMock(return_value=job)

    service = ProcessingService(
        job_repo=job_repo,
        meeting_repo=meeting_repo,
        recording_repo=recording_repo,
        transcript_repo=transcript_repo,
        storage_provider=storage,
        audio_service=audio_service,
        transcription_provider=transcription_provider,
        settings=Settings(),
    )

    result_job = await service.execute_job(
        job_id=job_id,
        meeting_id=meeting_id,
        worker_id="worker-test-1",
        lease_tracker=lease_tracker,
    )

    assert result_job is not None
    # Transcription provider should not be called since segments already exist
    transcription_provider.transcribe.assert_not_called()
    lease_tracker.release_lease.assert_awaited_with(
        job_id=job_id,
        worker_id="worker-test-1",
        target_status=JobStatus.COMPLETED,
        target_stage=JobStage.COMPLETED,
    )


@pytest.mark.asyncio
async def test_pipeline_retryable_transcription_failure() -> None:
    session = AsyncMock()
    user_id = uuid.uuid4()
    meeting_id = uuid.uuid4()
    job_id = uuid.uuid4()

    job = ProcessingJob(
        id=job_id,
        meeting_id=meeting_id,
        user_id=user_id,
        status=JobStatus.PENDING,
        stage=JobStage.CREATED,
        attempt=1,
        max_attempts=3,
    )
    meeting = Meeting(
        id=meeting_id, user_id=user_id, title="Sprint Review", status=MeetingStatus.ACTIVE
    )
    recording = Recording(
        id=uuid.uuid4(),
        meeting_id=meeting_id,
        user_id=user_id,
        storage_key="test/recording.mp4",
        original_filename="recording.mp4",
        content_type="audio/mp4",
        file_size_bytes=1024,
    )

    job_repo = JobRepository(session)
    job_repo.update_stage = AsyncMock(return_value=job)
    meeting_repo = MeetingRepository(session)
    meeting_repo.get_by_id_system = AsyncMock(return_value=meeting)
    recording_repo = RecordingRepository(session)
    recording_repo.get_by_meeting_id_system = AsyncMock(return_value=recording)

    transcript_repo = TranscriptRepository(session)
    transcript_repo.get_by_meeting_id = AsyncMock(return_value=None)

    storage = InMemoryStorageProvider()
    storage.files["test/recording.mp4"] = b"audio"

    audio_service = AudioService()
    audio_service.validate_media_file = MagicMock(
        return_value={"duration": 10.0, "has_audio": True}
    )
    audio_service.convert_to_wav_16k_mono = MagicMock(return_value="/tmp/audio.wav")

    # Transcription provider raises retryable error (e.g. 429)
    transcription_provider = MagicMock(spec=TranscriptionProvider)
    transcription_provider.transcribe.side_effect = TranscriptionProviderError(
        "Rate limit", is_retryable=True
    )

    lease_tracker = JobLeaseTracker(session, lease_duration_seconds=120)
    lease_tracker.claim_job = AsyncMock(return_value=job)
    lease_tracker.renew_heartbeat = AsyncMock(return_value=True)
    lease_tracker.release_lease = AsyncMock(return_value=job)

    service = ProcessingService(
        job_repo=job_repo,
        meeting_repo=meeting_repo,
        recording_repo=recording_repo,
        transcript_repo=transcript_repo,
        storage_provider=storage,
        audio_service=audio_service,
        transcription_provider=transcription_provider,
        settings=Settings(),
    )

    with pytest.raises(ProcessingPipelineError) as exc_info:
        await service.execute_job(
            job_id=job_id,
            meeting_id=meeting_id,
            worker_id="worker-test-1",
            lease_tracker=lease_tracker,
        )

    assert exc_info.value.is_retryable is True
    # Should re-enqueue to PENDING
    lease_tracker.release_lease.assert_awaited_with(
        job_id=job_id,
        worker_id="worker-test-1",
        target_status=JobStatus.PENDING,
        target_stage=JobStage.CREATED,
        error_code="TRANSCRIPTION_FAILED",
        error_message="Transcription failed: Rate limit",
    )


@pytest.mark.asyncio
async def test_pipeline_permanent_media_failure() -> None:
    session = AsyncMock()
    user_id = uuid.uuid4()
    meeting_id = uuid.uuid4()
    job_id = uuid.uuid4()

    job = ProcessingJob(
        id=job_id,
        meeting_id=meeting_id,
        user_id=user_id,
        status=JobStatus.PENDING,
        stage=JobStage.CREATED,
        attempt=1,
        max_attempts=3,
    )
    meeting = Meeting(
        id=meeting_id, user_id=user_id, title="Sprint Review", status=MeetingStatus.ACTIVE
    )
    recording = Recording(
        id=uuid.uuid4(),
        meeting_id=meeting_id,
        user_id=user_id,
        storage_key="test/corrupted.mp4",
        original_filename="corrupted.mp4",
        content_type="audio/mp4",
        file_size_bytes=1024,
    )

    job_repo = JobRepository(session)
    job_repo.update_stage = AsyncMock(return_value=job)
    meeting_repo = MeetingRepository(session)
    meeting_repo.get_by_id_system = AsyncMock(return_value=meeting)
    recording_repo = RecordingRepository(session)
    recording_repo.get_by_meeting_id_system = AsyncMock(return_value=recording)

    transcript_repo = TranscriptRepository(session)
    transcript_repo.get_by_meeting_id = AsyncMock(return_value=None)

    storage = InMemoryStorageProvider()
    storage.files["test/corrupted.mp4"] = b"corrupted"

    audio_service = AudioService()
    # Simulate corrupted media validation error
    audio_service.validate_media_file = MagicMock(
        side_effect=AudioProcessingError("Corrupted headers")
    )

    transcription_provider = MagicMock(spec=TranscriptionProvider)

    lease_tracker = JobLeaseTracker(session, lease_duration_seconds=120)
    lease_tracker.claim_job = AsyncMock(return_value=job)
    lease_tracker.renew_heartbeat = AsyncMock(return_value=True)
    lease_tracker.release_lease = AsyncMock(return_value=job)

    service = ProcessingService(
        job_repo=job_repo,
        meeting_repo=meeting_repo,
        recording_repo=recording_repo,
        transcript_repo=transcript_repo,
        storage_provider=storage,
        audio_service=audio_service,
        transcription_provider=transcription_provider,
        settings=Settings(),
    )

    with pytest.raises(ProcessingPipelineError) as exc_info:
        await service.execute_job(
            job_id=job_id,
            meeting_id=meeting_id,
            worker_id="worker-test-1",
            lease_tracker=lease_tracker,
        )

    assert exc_info.value.is_retryable is False
    # Should mark FAILED directly
    lease_tracker.release_lease.assert_awaited_with(
        job_id=job_id,
        worker_id="worker-test-1",
        target_status=JobStatus.FAILED,
        target_stage=JobStage.FAILED,
        error_code="INVALID_MEDIA",
        error_message="Media validation failed: Corrupted headers",
    )
    # Session must have been committed so failure persists despite exception
    session.commit.assert_awaited()


@pytest.mark.asyncio
async def test_processing_unexpected_error_persists_failure_and_commits() -> None:
    session = AsyncMock()
    user_id = uuid.uuid4()
    meeting_id = uuid.uuid4()
    job_id = uuid.uuid4()

    job = ProcessingJob(
        id=job_id,
        meeting_id=meeting_id,
        user_id=user_id,
        status=JobStatus.PENDING,
        stage=JobStage.CREATED,
        attempt=0,
    )
    meeting = Meeting(id=meeting_id, user_id=user_id, title="Test", status=MeetingStatus.ACTIVE)

    job_repo = JobRepository(session)
    meeting_repo = MeetingRepository(session)
    recording_repo = RecordingRepository(session)
    transcript_repo = TranscriptRepository(session)
    storage = InMemoryStorageProvider()
    audio_service = AudioService()
    transcription_provider = MagicMock(spec=TranscriptionProvider)

    # Simulate unexpected DB error during recording fetch
    meeting_repo.get_by_id_system = AsyncMock(return_value=meeting)
    recording_repo.get_by_meeting_id_system = AsyncMock(
        side_effect=RuntimeError("Unexpected connection drop")
    )

    lease_tracker = JobLeaseTracker(session, lease_duration_seconds=120)
    lease_tracker.claim_job = AsyncMock(return_value=job)
    lease_tracker.release_lease = AsyncMock(return_value=job)

    service = ProcessingService(
        job_repo=job_repo,
        meeting_repo=meeting_repo,
        recording_repo=recording_repo,
        transcript_repo=transcript_repo,
        storage_provider=storage,
        audio_service=audio_service,
        transcription_provider=transcription_provider,
        settings=Settings(),
    )

    with pytest.raises(RuntimeError):
        await service.execute_job(
            job_id=job_id,
            meeting_id=meeting_id,
            worker_id="worker-test-1",
            lease_tracker=lease_tracker,
        )

    lease_tracker.release_lease.assert_awaited_with(
        job_id=job_id,
        worker_id="worker-test-1",
        target_status=JobStatus.FAILED,
        target_stage=JobStage.FAILED,
        error_code="UNEXPECTED_ERROR",
        error_message="Unexpected connection drop",
    )
    session.rollback.assert_awaited()
    session.commit.assert_awaited()


@pytest.mark.asyncio
async def test_processing_pipeline_error_rolls_back_partial_transaction() -> None:
    session = AsyncMock()
    user_id = uuid.uuid4()
    meeting_id = uuid.uuid4()
    job_id = uuid.uuid4()

    job = ProcessingJob(
        id=job_id,
        meeting_id=meeting_id,
        user_id=user_id,
        status=JobStatus.PENDING,
        stage=JobStage.CREATED,
        attempt=3,  # Exhausted retries -> terminal FAILED
        max_attempts=3,
    )
    meeting = Meeting(
        id=meeting_id, user_id=user_id, title="Sprint Review", status=MeetingStatus.ACTIVE
    )

    job_repo = JobRepository(session)
    job_repo.get_by_id_system = AsyncMock(return_value=job)
    meeting_repo = MeetingRepository(session)
    meeting_repo.get_by_id_system = AsyncMock(return_value=meeting)
    recording_repo = RecordingRepository(session)
    recording_repo.get_by_meeting_id_system = AsyncMock(return_value=None)  # RECORDING_NOT_FOUND

    lease_tracker = JobLeaseTracker(session, lease_duration_seconds=120)
    lease_tracker.claim_job = AsyncMock(return_value=job)
    lease_tracker.release_lease = AsyncMock(return_value=job)

    service = ProcessingService(
        job_repo=job_repo,
        meeting_repo=meeting_repo,
        recording_repo=recording_repo,
        transcript_repo=TranscriptRepository(session),
        storage_provider=InMemoryStorageProvider(),
        audio_service=AudioService(),
        transcription_provider=MagicMock(spec=TranscriptionProvider),
        settings=Settings(),
    )

    with pytest.raises(ProcessingPipelineError) as exc_info:
        await service.execute_job(
            job_id=job_id,
            meeting_id=meeting_id,
            worker_id="worker-test-1",
            lease_tracker=lease_tracker,
        )

    assert exc_info.value.error_code == "RECORDING_NOT_FOUND"
    session.rollback.assert_awaited()
    session.commit.assert_awaited()
    lease_tracker.release_lease.assert_awaited_with(
        job_id=job_id,
        worker_id="worker-test-1",
        target_status=JobStatus.FAILED,
        target_stage=JobStage.FAILED,
        error_code="RECORDING_NOT_FOUND",
        error_message=exc_info.value.message,
    )


@pytest.mark.asyncio
async def test_failure_persistence_after_partial_writes() -> None:
    session = AsyncMock()
    user_id = uuid.uuid4()
    meeting_id = uuid.uuid4()
    job_id = uuid.uuid4()

    job = ProcessingJob(
        id=job_id,
        meeting_id=meeting_id,
        user_id=user_id,
        status=JobStatus.PENDING,
        stage=JobStage.CREATED,
        attempt=1,
        max_attempts=3,
    )
    meeting = Meeting(id=meeting_id, user_id=user_id, title="Test", status=MeetingStatus.ACTIVE)
    recording = Recording(
        id=uuid.uuid4(),
        meeting_id=meeting_id,
        user_id=user_id,
        storage_key="test.mp4",
        original_filename="test.mp4",
        content_type="audio/mp4",
        file_size_bytes=100,
        status=RecordingStatus.UPLOADED,
    )

    job_repo = JobRepository(session)
    job_repo.get_by_id_system = AsyncMock(return_value=job)
    job_repo.update_stage = AsyncMock(return_value=job)
    meeting_repo = MeetingRepository(session)
    meeting_repo.get_by_id_system = AsyncMock(return_value=meeting)
    recording_repo = RecordingRepository(session)
    recording_repo.get_by_meeting_id_system = AsyncMock(return_value=recording)

    transcript_repo = TranscriptRepository(session)
    transcript_repo.get_by_meeting_id = AsyncMock(return_value=None)
    mock_transcript = Transcript(
        id=uuid.uuid4(), meeting_id=meeting_id, user_id=user_id, provider="mock"
    )
    transcript_repo.create_transcript = AsyncMock(return_value=mock_transcript)
    transcript_repo.add_segments = AsyncMock(return_value=[])
    transcript_repo.get_segments_by_transcript = AsyncMock(return_value=[])

    storage = InMemoryStorageProvider()
    storage.files["test.mp4"] = b"audio"

    audio_service = AudioService()
    audio_service.validate_media_file = MagicMock(
        return_value={"duration": 10.0, "has_audio": True}
    )
    audio_service.convert_to_wav_16k_mono = MagicMock(return_value="/tmp/test.wav")

    transcription_provider = MagicMock(spec=TranscriptionProvider)
    transcription_provider.transcribe.return_value = TranscriptionResult(
        provider="mock",
        model="whisper",
        segments=[
            TranscriptSegmentResult(sequence_index=0, start_time=0.0, end_time=5.0, text="hello")
        ],
    )

    # Analysis fails after transcript has been written
    analysis_service = MagicMock()
    analysis_service.execute_analysis = AsyncMock(
        side_effect=RuntimeError("LLM API rate limit exceeded")
    )

    lease_tracker = JobLeaseTracker(session, lease_duration_seconds=120)
    lease_tracker.claim_job = AsyncMock(return_value=job)
    lease_tracker.renew_heartbeat = AsyncMock(return_value=True)
    lease_tracker.release_lease = AsyncMock(return_value=job)

    service = ProcessingService(
        job_repo=job_repo,
        meeting_repo=meeting_repo,
        recording_repo=recording_repo,
        transcript_repo=transcript_repo,
        storage_provider=storage,
        audio_service=audio_service,
        transcription_provider=transcription_provider,
        analysis_service=analysis_service,
        settings=Settings(),
    )

    with pytest.raises(ProcessingPipelineError) as exc_info:
        await service.execute_job(
            job_id=job_id,
            meeting_id=meeting_id,
            worker_id="worker-test-1",
            lease_tracker=lease_tracker,
        )

    assert exc_info.value.error_code == "ANALYSIS_FAILED"
    # Verifies partial writes were rolled back
    session.rollback.assert_awaited()
    # Verifies terminal FAILED state was persisted and committed
    lease_tracker.release_lease.assert_awaited_with(
        job_id=job_id,
        worker_id="worker-test-1",
        target_status=JobStatus.FAILED,
        target_stage=JobStage.FAILED,
        error_code="ANALYSIS_FAILED",
        error_message=exc_info.value.message,
    )
    session.commit.assert_awaited()


def test_scratch_dir_cleanup_on_success_and_failure() -> None:
    audio_service = AudioService()
    created_dir = None

    # Test success path cleanup
    with audio_service.temporary_scratch_dir() as scratch_path:
        created_dir = scratch_path
        assert created_dir.exists()
        (created_dir / "sample.wav").write_bytes(b"sample")
        assert (created_dir / "sample.wav").exists()
    assert not created_dir.exists()

    # Test exception/failure path cleanup
    failed_dir = None
    try:
        with audio_service.temporary_scratch_dir() as scratch_path:
            failed_dir = scratch_path
            assert failed_dir.exists()
            (failed_dir / "fail.mp3").write_bytes(b"fail")
            raise RuntimeError("Pipeline failed mid-processing")
    except RuntimeError:
        pass
    assert not failed_dir.exists()
