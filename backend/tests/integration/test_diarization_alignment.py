import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.config import Settings
from app.models.meeting import Meeting
from app.models.processing_job import JobStage, JobStatus, ProcessingJob
from app.models.recording import Recording
from app.models.transcript import Transcript
from app.providers.diarization.base import (
    DiarizationProvider,
    DiarizationProviderError,
    DiarizationResult,
    DiarizationTurn,
)
from app.providers.storage.base import StorageProvider
from app.providers.transcription.base import (
    TranscriptionProvider,
    TranscriptionResult,
    TranscriptSegmentResult,
)
from app.repositories.job_repository import JobRepository
from app.repositories.meeting_repository import MeetingRepository
from app.repositories.recording_repository import RecordingRepository
from app.repositories.transcript_repository import TranscriptRepository
from app.services.alignment_service import AlignmentService
from app.services.audio_service import AudioService
from app.services.diarization_service import DiarizationService
from app.services.processing_service import ProcessingPipelineError, ProcessingService
from app.workers.job_lease import JobLeaseTracker


@pytest.fixture
def mock_dependencies():
    job_repo = MagicMock(spec=JobRepository)
    meeting_repo = MagicMock(spec=MeetingRepository)
    recording_repo = MagicMock(spec=RecordingRepository)
    transcript_repo = MagicMock(spec=TranscriptRepository)
    storage_provider = MagicMock(spec=StorageProvider)
    audio_service = MagicMock(spec=AudioService)
    transcription_provider = MagicMock(spec=TranscriptionProvider)
    diarization_provider = MagicMock(spec=DiarizationProvider)

    # Async methods on repositories
    job_repo.update_stage = AsyncMock()
    meeting_repo.get_by_id = AsyncMock()
    recording_repo.get_by_meeting_id = AsyncMock()
    transcript_repo.get_by_meeting_id = AsyncMock(return_value=None)
    transcript_repo.create_transcript = AsyncMock()
    transcript_repo.update_transcript = AsyncMock()
    transcript_repo.add_segments = AsyncMock()
    transcript_repo.delete_segments = AsyncMock()

    settings = Settings(
        STORAGE_BUCKET_NAME="test-recordings",
        TRANSCRIPTION_PROVIDER="mock",
        DIARIZATION_PROVIDER="mock",
    )

    diarization_service = DiarizationService(diarization_provider, settings)
    alignment_service = AlignmentService()

    return {
        "job_repo": job_repo,
        "meeting_repo": meeting_repo,
        "recording_repo": recording_repo,
        "transcript_repo": transcript_repo,
        "storage_provider": storage_provider,
        "audio_service": audio_service,
        "transcription_provider": transcription_provider,
        "diarization_provider": diarization_provider,
        "diarization_service": diarization_service,
        "alignment_service": alignment_service,
        "settings": settings,
    }


@pytest.mark.asyncio
async def test_diarization_alignment_integration(mock_dependencies, tmp_path) -> None:
    job_id = uuid.uuid4()
    meeting_id = uuid.uuid4()
    user_id = uuid.uuid4()

    deps = mock_dependencies

    # Setup job and recording models
    job = ProcessingJob(
        id=job_id,
        meeting_id=meeting_id,
        user_id=user_id,
        status=JobStatus.RUNNING,
        stage=JobStage.CREATED,
    )
    meeting = Meeting(id=meeting_id, user_id=user_id, title="Planning Meeting")
    recording = Recording(
        id=uuid.uuid4(),
        meeting_id=meeting_id,
        user_id=user_id,
        storage_key=f"recordings/{user_id}/{meeting_id}/audio.mp4",
        original_filename="audio.mp4",
        content_type="audio/mp4",
        file_size_bytes=1024,
    )

    deps["meeting_repo"].get_by_id.return_value = meeting
    deps["recording_repo"].get_by_meeting_id.return_value = recording

    # Audio scratch directory mock
    from contextlib import contextmanager

    @contextmanager
    def mock_scratch(prefix=""):
        yield tmp_path

    deps["audio_service"].temporary_scratch_dir = mock_scratch
    deps["audio_service"].validate_media_file.return_value = {"duration": 20.0, "has_audio": True}
    deps["audio_service"].convert_to_wav_16k_mono.return_value = str(
        tmp_path / "normalized_16k_mono.wav"
    )

    # Transcription returns two segments
    deps["transcription_provider"].transcribe.return_value = TranscriptionResult(
        provider="groq_whisper_turbo",
        model="whisper-large-v3-turbo",
        language="en",
        total_duration_seconds=20.0,
        raw_transcript_text="Alice speaks first. Then Bob answers.",
        segments=[
            TranscriptSegmentResult(
                sequence_index=0,
                start_time=0.0,
                end_time=8.0,
                text="Alice speaks first.",
            ),
            TranscriptSegmentResult(
                sequence_index=1,
                start_time=8.5,
                end_time=18.0,
                text="Then Bob answers.",
            ),
        ],
    )

    # Diarization returns two turns
    deps["diarization_provider"].diarize.return_value = DiarizationResult(
        provider="pyannote_community_1",
        turns=[
            DiarizationTurn(start_time=0.0, end_time=8.0, speaker_label="SPEAKER_00"),
            DiarizationTurn(start_time=8.0, end_time=20.0, speaker_label="SPEAKER_01"),
        ],
    )

    mock_transcript = Transcript(
        id=uuid.uuid4(),
        meeting_id=meeting_id,
        user_id=user_id,
        provider="groq_whisper_turbo",
    )
    deps["transcript_repo"].create_transcript.return_value = mock_transcript

    lease_tracker = MagicMock(spec=JobLeaseTracker)
    lease_tracker.claim_job = AsyncMock(return_value=job)
    lease_tracker.renew_heartbeat = AsyncMock(return_value=True)
    lease_tracker.release_lease = AsyncMock(return_value=job)

    service = ProcessingService(
        job_repo=deps["job_repo"],
        meeting_repo=deps["meeting_repo"],
        recording_repo=deps["recording_repo"],
        transcript_repo=deps["transcript_repo"],
        storage_provider=deps["storage_provider"],
        audio_service=deps["audio_service"],
        transcription_provider=deps["transcription_provider"],
        settings=deps["settings"],
        diarization_service=deps["diarization_service"],
        alignment_service=deps["alignment_service"],
    )

    result_job = await service.execute_job(
        job_id=job_id,
        meeting_id=meeting_id,
        worker_id="worker_test",
        lease_tracker=lease_tracker,
    )

    assert result_job is not None

    # Verify stage progression included DIARIZING
    stage_calls = [c.kwargs["stage"] for c in deps["job_repo"].update_stage.call_args_list]
    assert JobStage.VALIDATING in stage_calls
    assert JobStage.EXTRACTING_AUDIO in stage_calls
    assert JobStage.TRANSCRIBING in stage_calls
    assert JobStage.DIARIZING in stage_calls
    assert JobStage.SAVING in stage_calls

    # Verify create_transcript was called with diarization_provider
    deps["transcript_repo"].create_transcript.assert_called_once()
    create_kwargs = deps["transcript_repo"].create_transcript.call_args.kwargs
    assert create_kwargs["diarization_provider"] == "pyannote_community_1"

    # Verify segments passed to add_segments have aligned speaker labels
    deps["transcript_repo"].add_segments.assert_called_once()
    segments_saved = deps["transcript_repo"].add_segments.call_args.kwargs["segments_data"]
    assert len(segments_saved) == 2
    assert segments_saved[0]["speaker_label"] == "SPEAKER_00"
    assert segments_saved[1]["speaker_label"] == "SPEAKER_01"


@pytest.mark.asyncio
async def test_diarization_failure_raises_pipeline_error(mock_dependencies, tmp_path) -> None:
    job_id = uuid.uuid4()
    meeting_id = uuid.uuid4()
    user_id = uuid.uuid4()

    deps = mock_dependencies

    job = ProcessingJob(
        id=job_id,
        meeting_id=meeting_id,
        user_id=user_id,
        status=JobStatus.RUNNING,
        stage=JobStage.CREATED,
    )
    meeting = Meeting(id=meeting_id, user_id=user_id, title="Meeting")
    recording = Recording(
        id=uuid.uuid4(),
        meeting_id=meeting_id,
        user_id=user_id,
        storage_key="test-key",
        original_filename="audio.wav",
        content_type="audio/wav",
        file_size_bytes=1024,
    )

    deps["meeting_repo"].get_by_id.return_value = meeting
    deps["recording_repo"].get_by_meeting_id.return_value = recording

    from contextlib import contextmanager

    @contextmanager
    def mock_scratch(prefix=""):
        yield tmp_path

    deps["audio_service"].temporary_scratch_dir = mock_scratch
    deps["audio_service"].validate_media_file.return_value = {"duration": 10.0, "has_audio": True}
    deps["audio_service"].convert_to_wav_16k_mono.return_value = str(tmp_path / "audio.wav")

    deps["transcription_provider"].transcribe.return_value = TranscriptionResult(
        provider="mock",
        model="whisper",
        language="en",
        segments=[],
    )

    deps["diarization_provider"].diarize.side_effect = DiarizationProviderError(
        "Model timeout", is_retryable=True
    )

    lease_tracker = MagicMock(spec=JobLeaseTracker)
    lease_tracker.claim_job = AsyncMock(return_value=job)
    lease_tracker.renew_heartbeat = AsyncMock(return_value=True)
    lease_tracker.release_lease = AsyncMock(return_value=job)

    service = ProcessingService(
        job_repo=deps["job_repo"],
        meeting_repo=deps["meeting_repo"],
        recording_repo=deps["recording_repo"],
        transcript_repo=deps["transcript_repo"],
        storage_provider=deps["storage_provider"],
        audio_service=deps["audio_service"],
        transcription_provider=deps["transcription_provider"],
        settings=deps["settings"],
        diarization_service=deps["diarization_service"],
        alignment_service=deps["alignment_service"],
    )

    with pytest.raises(ProcessingPipelineError) as exc_info:
        await service.execute_job(
            job_id=job_id,
            meeting_id=meeting_id,
            worker_id="worker_test",
            lease_tracker=lease_tracker,
        )

    assert exc_info.value.error_code == "DIARIZATION_FAILED"
    assert exc_info.value.is_retryable is True
