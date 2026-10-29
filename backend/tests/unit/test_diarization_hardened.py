import pytest
from unittest.mock import AsyncMock, MagicMock
from app.core.config import Settings
from app.services.processing_service import ProcessingPipelineError, ProcessingService
from app.services.diarization_service import DiarizationProcessingError
from app.models.processing_job import JobStage, JobStatus, ProcessingJob
from app.models.meeting import Meeting, MeetingStatus
from app.models.recording import Recording
from app.providers.transcription.base import TranscriptionResult, TranscriptSegmentResult
from app.workers.job_lease import JobLeaseTracker
import uuid

def test_production_rejects_none_or_mock_diarization():
    """Confirms production configuration does not permit 'none' or 'mock' diarization."""
    with pytest.raises(ValueError, match="DIARIZATION_PROVIDER cannot be 'mock' or 'none' in production"):
        Settings(
            APP_ENV="production",
            DIARIZATION_PROVIDER="none",
            DATABASE_URL="postgresql+psycopg://user:pass@remotehost:5432/db",
            REDIS_URL="redis://remotehost:6379/0",
            STORAGE_PROVIDER="r2",
            STORAGE_ACCESS_KEY_ID="valid_key",
            STORAGE_SECRET_ACCESS_KEY="valid_secret",
            LLM_PROVIDER="groq",
            LLM_API_KEY="valid_llm_key",
            JWT_SIGNING_KEY_OR_JWKS="valid_jwt_key",
            UPLOAD_TOKEN_SECRET="valid_upload_token_secret",
        )

    with pytest.raises(ValueError, match="DIARIZATION_PROVIDER cannot be 'mock' or 'none' in production"):
        Settings(
            APP_ENV="production",
            DIARIZATION_PROVIDER="mock",
            DATABASE_URL="postgresql+psycopg://user:pass@remotehost:5432/db",
            REDIS_URL="redis://remotehost:6379/0",
            STORAGE_PROVIDER="r2",
            STORAGE_ACCESS_KEY_ID="valid_key",
            STORAGE_SECRET_ACCESS_KEY="valid_secret",
            LLM_PROVIDER="groq",
            LLM_API_KEY="valid_llm_key",
            JWT_SIGNING_KEY_OR_JWKS="valid_jwt_key",
            UPLOAD_TOKEN_SECRET="valid_upload_token_secret",
        )

@pytest.mark.asyncio
async def test_production_diarization_failure_raises_and_does_not_fabricate_single_speaker(tmp_path):
    """In production mode, if diarization fails, pipeline must raise ProcessingPipelineError
    instead of silently fabricating or accepting a single-speaker fallback.
    """
    settings = Settings(
        APP_ENV="production",
        DIARIZATION_PROVIDER="pyannote_community_1",
        DATABASE_URL="postgresql+psycopg://user:pass@remotehost:5432/db",
        REDIS_URL="redis://remotehost:6379/0",
        STORAGE_PROVIDER="r2",
        STORAGE_ACCESS_KEY_ID="valid_key",
        STORAGE_SECRET_ACCESS_KEY="valid_secret",
        LLM_PROVIDER="groq",
        LLM_API_KEY="valid_llm_key",
        JWT_SIGNING_KEY_OR_JWKS="valid_jwt_key",
        UPLOAD_TOKEN_SECRET="valid_upload_token_secret",
    )

    job_id = uuid.uuid4()
    meeting_id = uuid.uuid4()
    user_id = uuid.uuid4()

    job = ProcessingJob(
        id=job_id, meeting_id=meeting_id, user_id=user_id,
        status=JobStatus.RUNNING, stage=JobStage.CREATED
    )
    meeting = Meeting(id=meeting_id, user_id=user_id, title="Test", status=MeetingStatus.ACTIVE)
    recording = Recording(
        id=uuid.uuid4(),
        meeting_id=meeting_id,
        user_id=user_id,
        storage_key="test/key",
        original_filename="audio.wav",
        content_type="audio/wav",
        file_size_bytes=1024,
    )

    job_repo = MagicMock()
    job_repo.update_stage = AsyncMock()
    meeting_repo = MagicMock()
    meeting_repo.get_by_id_system = AsyncMock(return_value=meeting)
    recording_repo = MagicMock()
    recording_repo.get_by_meeting_id_system = AsyncMock(return_value=recording)
    transcript_repo = MagicMock()
    transcript_repo.get_by_meeting_id = AsyncMock(return_value=None)
    storage_provider = MagicMock()
    audio_service = MagicMock()
    audio_service.validate_media_file.return_value = {"duration": 10.0}

    # Context manager for scratch dir
    from contextlib import contextmanager
    @contextmanager
    def fake_scratch(prefix=""):
        yield tmp_path
    audio_service.temporary_scratch_dir = fake_scratch

    transcription_provider = MagicMock()
    transcription_provider.transcribe.return_value = TranscriptionResult(
        provider="whisper", model="v3", language="en", total_duration_seconds=10.0,
        raw_transcript_text="Test speech",
        segments=[
            TranscriptSegmentResult(sequence_index=0, start_time=0.0, end_time=5.0, text="Hello", speaker_label="SPEAKER_00"),
            TranscriptSegmentResult(sequence_index=1, start_time=5.0, end_time=10.0, text="World", speaker_label="SPEAKER_00"),
        ]
    )

    diarization_service = MagicMock()
    diarization_service.diarize_audio.side_effect = DiarizationProcessingError("Pyannote GPU out of memory", is_retryable=True)

    lease_tracker = MagicMock(spec=JobLeaseTracker)
    lease_tracker.claim_job.return_value = job

    service = ProcessingService(
        job_repo=job_repo,
        meeting_repo=meeting_repo,
        recording_repo=recording_repo,
        transcript_repo=transcript_repo,
        storage_provider=storage_provider,
        audio_service=audio_service,
        transcription_provider=transcription_provider,
        diarization_service=diarization_service,
        settings=settings,
    )

    with pytest.raises(ProcessingPipelineError) as exc_info:
        await service.execute_job(
            job_id=job_id, meeting_id=meeting_id, worker_id="worker_1", lease_tracker=lease_tracker
        )

    assert exc_info.value.error_code == "DIARIZATION_FAILED"
    assert "Diarization stage failed in production" in str(exc_info.value)
