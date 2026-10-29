import asyncio
import logging
import uuid
from typing import Any

from app.core.config import Settings
from app.models.meeting import MeetingStatus
from app.models.processing_job import JobStage, JobStatus, ProcessingJob
from app.providers.storage.base import StorageProvider
from app.providers.transcription.base import (
    TranscriptionProvider,
    TranscriptionProviderError,
)
from app.repositories.job_repository import JobRepository
from app.repositories.meeting_repository import MeetingRepository
from app.repositories.recording_repository import RecordingRepository
from app.repositories.transcript_repository import TranscriptRepository
from app.services.alignment_service import AlignmentService
from app.services.analysis_service import AnalysisService
from app.services.audio_service import AudioProcessingError, AudioService
from app.services.diarization_service import DiarizationProcessingError, DiarizationService
from app.workers.job_lease import JobLeaseTracker

logger = logging.getLogger(__name__)


class ProcessingPipelineError(Exception):
    """Base exception for pipeline execution errors."""

    def __init__(
        self, message: str, error_code: str = "PROCESSING_ERROR", is_retryable: bool = False
    ) -> None:
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.is_retryable = is_retryable


class ProcessingService:
    """Orchestrates recording download, media validation, FFmpeg normalization,
    transcription, speaker diarization, alignment, transcript persistence,
    and meeting intelligence analysis.
    """

    def __init__(
        self,
        job_repo: JobRepository,
        meeting_repo: MeetingRepository,
        recording_repo: RecordingRepository,
        transcript_repo: TranscriptRepository,
        storage_provider: StorageProvider,
        audio_service: AudioService,
        transcription_provider: TranscriptionProvider,
        settings: Settings,
        diarization_service: DiarizationService | None = None,
        alignment_service: AlignmentService | None = None,
        analysis_service: AnalysisService | None = None,
    ) -> None:
        self.job_repo = job_repo
        self.meeting_repo = meeting_repo
        self.recording_repo = recording_repo
        self.transcript_repo = transcript_repo
        self.storage_provider = storage_provider
        self.audio_service = audio_service
        self.transcription_provider = transcription_provider
        self.settings = settings
        self.diarization_service = diarization_service
        self.alignment_service = alignment_service or AlignmentService()
        self.analysis_service = analysis_service

    async def _safe_commit(self) -> None:
        """Safely commits the database session if available and awaitable."""
        session = getattr(self.job_repo, "session", None)
        commit_fn = getattr(session, "commit", None)
        if callable(commit_fn):
            res = commit_fn()
            if asyncio.iscoroutine(res) or hasattr(res, "__await__"):
                await res

    async def _safe_rollback(self) -> None:
        """Safely rolls back the database session if available and awaitable."""
        session = getattr(self.job_repo, "session", None)
        rollback_fn = getattr(session, "rollback", None)
        if callable(rollback_fn):
            res = rollback_fn()
            if asyncio.iscoroutine(res) or hasattr(res, "__await__"):
                await res

    async def execute_job(
        self,
        job_id: uuid.UUID,
        meeting_id: uuid.UUID,
        worker_id: str,
        lease_tracker: JobLeaseTracker,
    ) -> ProcessingJob:
        """Executes the media extraction and transcription pipeline for a meeting recording."""
        # 1. Lease Claim & Idempotency verification
        job = await lease_tracker.claim_job(job_id=job_id, worker_id=worker_id)
        if job is None:
            # Check current status
            existing_job = await self.job_repo.get_by_id_system(job_id=job_id)
            if existing_job and existing_job.status in (JobStatus.COMPLETED, JobStatus.CANCELLED):
                logger.info(
                    "Job %s is already in terminal state %s. Skipping.", job_id, existing_job.status
                )
                return existing_job
            raise ProcessingPipelineError(
                f"Failed to claim lease for job {job_id} on worker {worker_id}",
                error_code="LEASE_CLAIM_FAILED",
                is_retryable=True,
            )

        # Commit claimed lease state so worker ownership and RUNNING status are immediately visible
        await self._safe_commit()

        try:
            # Check meeting and recording existence
            meeting = await self.meeting_repo.get_by_id_system(meeting_id=meeting_id)
            if meeting is None or meeting.status in (MeetingStatus.DELETING, MeetingStatus.PURGED):
                raise ProcessingPipelineError(
                    f"Meeting {meeting_id} not found or deleted",
                    error_code="MEETING_DELETED",
                    is_retryable=False,
                )

            recording = await self.recording_repo.get_by_meeting_id_system(meeting_id=meeting_id)
            if recording is None:
                raise ProcessingPipelineError(
                    f"Recording for meeting {meeting_id} not found",
                    error_code="RECORDING_NOT_FOUND",
                    is_retryable=False,
                )

            # Check if transcript segments already exist (Idempotency checkpoint & Stage Resumption)
            existing_transcript = await self.transcript_repo.get_by_meeting_id(
                meeting_id=meeting_id, user_id=job.user_id
            )
            if (
                existing_transcript
                and existing_transcript.segment_count
                and existing_transcript.segment_count > 0
            ):
                logger.info(
                    "Transcript segments already exist for meeting %s (%d segments). Checking analysis checkpoint.",
                    meeting_id,
                    existing_transcript.segment_count,
                )
                existing_analysis = None
                if self.analysis_service:
                    existing_analysis = await self.analysis_service.analysis_repo.get_by_meeting_id(
                        meeting_id=meeting_id, user_id=job.user_id
                    )

                # If both transcript and analysis already exist, mark job as completed
                if existing_analysis or not self.analysis_service:
                    logger.info("Meeting %s already has valid transcript and analysis. Completing job.", meeting_id)
                    completed_job = await lease_tracker.release_lease(
                        job_id=job_id,
                        worker_id=worker_id,
                        target_status=JobStatus.COMPLETED,
                        target_stage=JobStage.COMPLETED,
                    )
                    await self._safe_commit()
                    return completed_job or job

                # Transcript is valid, but analysis is missing/incomplete: Resume directly from ANALYZING!
                logger.info(
                    "Meeting %s has transcript but missing analysis. Resuming from ANALYZING stage, avoiding re-transcription.",
                    meeting_id,
                )
                await self.job_repo.update_stage(job=job, stage=JobStage.ANALYZING)
                await lease_tracker.renew_heartbeat(job_id=job_id, worker_id=worker_id)

                db_segments = await self.transcript_repo.get_segments_by_transcript(
                    existing_transcript.id
                )

                async def record_verifying_stage() -> None:
                    await self.job_repo.update_stage(job=job, stage=JobStage.VERIFYING)
                    await lease_tracker.renew_heartbeat(job_id=job_id, worker_id=worker_id)

                try:
                    await self.analysis_service.execute_analysis(
                        meeting_id=meeting_id,
                        user_id=job.user_id,
                        segments=list(db_segments),
                        on_stage_change=record_verifying_stage,
                    )
                except Exception as exc:
                    raise ProcessingPipelineError(
                        f"Meeting intelligence extraction failed: {exc}",
                        error_code="ANALYSIS_FAILED",
                        is_retryable=False,
                    ) from exc

                current_meeting = await self.meeting_repo.get_by_id_system(meeting_id=meeting_id)
                if current_meeting is None or current_meeting.status in (
                    MeetingStatus.DELETING,
                    MeetingStatus.PURGED,
                ):
                    raise ProcessingPipelineError(
                        f"Meeting {meeting_id} deleted during processing",
                        error_code="MEETING_DELETED",
                        is_retryable=False,
                    )

                completed_job = await lease_tracker.release_lease(
                    job_id=job_id,
                    worker_id=worker_id,
                    target_status=JobStatus.COMPLETED,
                    target_stage=JobStage.COMPLETED,
                )
                await self._safe_commit()
                logger.info("Job %s completed successfully via resumed analysis.", job_id)
                return completed_job or job

            # Execute pipeline within clean isolated scratch directory
            with self.audio_service.temporary_scratch_dir(
                prefix=f"meeting_{meeting_id}_"
            ) as scratch_dir:
                # Stage 1: VALIDATING — Download & inspect
                await self.job_repo.update_stage(job=job, stage=JobStage.VALIDATING)
                await lease_tracker.renew_heartbeat(job_id=job_id, worker_id=worker_id)

                raw_filename = f"raw_media_{recording.original_filename}"
                local_raw_path = scratch_dir / raw_filename

                try:
                    self.storage_provider.download_file(
                        storage_key=recording.storage_key,
                        destination_path=str(local_raw_path),
                    )
                except Exception as exc:
                    raise ProcessingPipelineError(
                        f"Failed to download recording from storage: {exc}",
                        error_code="STORAGE_DOWNLOAD_FAILED",
                        is_retryable=True,
                    ) from exc

                try:
                    media_info = self.audio_service.validate_media_file(local_raw_path)
                except AudioProcessingError as exc:
                    raise ProcessingPipelineError(
                        f"Media validation failed: {exc}",
                        error_code="INVALID_MEDIA",
                        is_retryable=False,
                    ) from exc

                # Stage 2: EXTRACTING_AUDIO — FFmpeg normalization to 16 kHz mono WAV
                await self.job_repo.update_stage(job=job, stage=JobStage.EXTRACTING_AUDIO)
                await lease_tracker.renew_heartbeat(job_id=job_id, worker_id=worker_id)

                local_wav_path = scratch_dir / "normalized_16k_mono.wav"
                try:
                    self.audio_service.convert_to_wav_16k_mono(local_raw_path, local_wav_path)
                except AudioProcessingError as exc:
                    raise ProcessingPipelineError(
                        f"FFmpeg audio extraction failed: {exc}",
                        error_code="FFMPEG_EXTRACTION_FAILED",
                        is_retryable=False,
                    ) from exc

                # Stage 3: TRANSCRIBING — Call Whisper provider
                await self.job_repo.update_stage(job=job, stage=JobStage.TRANSCRIBING)
                await lease_tracker.renew_heartbeat(job_id=job_id, worker_id=worker_id)

                try:
                    transcription_result = self.transcription_provider.transcribe(
                        str(local_wav_path)
                    )
                except TranscriptionProviderError as exc:
                    raise ProcessingPipelineError(
                        f"Transcription failed: {exc.message}",
                        error_code="TRANSCRIPTION_FAILED",
                        is_retryable=exc.is_retryable,
                    ) from exc
                except Exception as exc:
                    raise ProcessingPipelineError(
                        f"Unexpected transcription error: {exc}",
                        error_code="TRANSCRIPTION_FAILED",
                        is_retryable=False,
                    ) from exc

                # Stage 4: DIARIZING — Call Diarization provider and align with segments
                await self.job_repo.update_stage(job=job, stage=JobStage.DIARIZING)
                await lease_tracker.renew_heartbeat(job_id=job_id, worker_id=worker_id)

                diarization_provider_name: str | None = None
                if self.diarization_service:
                    try:
                        diarization_result = self.diarization_service.diarize_audio(local_wav_path)
                        diarization_provider_name = diarization_result.provider
                        if diarization_result.turns:
                            transcription_result.segments = self.alignment_service.align(
                                segments=transcription_result.segments,
                                turns=diarization_result.turns,
                            )
                    except DiarizationProcessingError as exc:
                        if self.settings and self.settings.APP_ENV == "production":
                            raise ProcessingPipelineError(
                                f"Diarization stage failed in production: {exc.message}",
                                error_code="DIARIZATION_FAILED",
                                is_retryable=exc.is_retryable,
                            ) from exc
                        logger.warning(
                            "Diarization unavailable or failed for meeting %s: %s. "
                            "Continuing with non-diarized transcript segments in non-production environment.",
                            meeting_id,
                            exc.message,
                        )
                        diarization_provider_name = None
                    except Exception as exc:
                        if self.settings and self.settings.APP_ENV == "production":
                            raise ProcessingPipelineError(
                                f"Unexpected diarization failure in production: {exc}",
                                error_code="DIARIZATION_FAILED",
                                is_retryable=False,
                            ) from exc
                        logger.warning(
                            "Unexpected diarization exception for meeting %s: %s. "
                            "Continuing with non-diarized transcript segments in non-production environment.",
                            meeting_id,
                            exc,
                        )
                        diarization_provider_name = None

                # Stage 5: SAVING — Persist transcript and transcript_segments
                current_meeting = await self.meeting_repo.get_by_id_system(meeting_id=meeting_id)
                if current_meeting is None or current_meeting.status in (
                    MeetingStatus.DELETING,
                    MeetingStatus.PURGED,
                ):
                    raise ProcessingPipelineError(
                        f"Meeting {meeting_id} deleted during processing",
                        error_code="MEETING_DELETED",
                        is_retryable=False,
                    )

                await self.job_repo.update_stage(job=job, stage=JobStage.SAVING)
                await lease_tracker.renew_heartbeat(job_id=job_id, worker_id=worker_id)

                # Commit transcript records
                if existing_transcript:
                    transcript = await self.transcript_repo.update_transcript(
                        transcript=existing_transcript,
                        provider=transcription_result.provider,
                        language=transcription_result.language,
                        model=transcription_result.model,
                        diarization_provider=diarization_provider_name,
                        total_duration_seconds=transcription_result.total_duration_seconds
                        or media_info.get("duration"),
                        segment_count=len(transcription_result.segments),
                        raw_transcript_text=transcription_result.raw_transcript_text,
                    )
                    await self.transcript_repo.delete_segments(transcript.id)
                else:
                    transcript = await self.transcript_repo.create_transcript(
                        meeting_id=meeting_id,
                        user_id=job.user_id,
                        provider=transcription_result.provider,
                        language=transcription_result.language,
                        model=transcription_result.model,
                        diarization_provider=diarization_provider_name,
                        total_duration_seconds=transcription_result.total_duration_seconds
                        or media_info.get("duration"),
                        segment_count=len(transcription_result.segments),
                        raw_transcript_text=transcription_result.raw_transcript_text,
                    )

                segments_payload: list[dict[str, Any]] = [
                    {
                        "sequence_index": s.sequence_index,
                        "start_time": s.start_time,
                        "end_time": s.end_time,
                        "speaker_label": s.speaker_label or "SPEAKER_00",
                        "speaker": s.speaker,
                        "text": s.text,
                        "metadata": {"confidence": s.confidence}
                        if s.confidence is not None
                        else None,
                    }
                    for s in transcription_result.segments
                ]
                await self.transcript_repo.add_segments(
                    transcript_id=transcript.id,
                    meeting_id=meeting_id,
                    segments_data=segments_payload,
                )

                # Stage 5: ANALYZING & VERIFYING — Run meeting intelligence extraction
                if self.analysis_service:
                    await self.job_repo.update_stage(job=job, stage=JobStage.ANALYZING)
                    await lease_tracker.renew_heartbeat(job_id=job_id, worker_id=worker_id)

                    # Fetch persisted segments from DB for authoritative IDs and timestamps
                    db_segments = await self.transcript_repo.get_segments_by_transcript(
                        transcript.id
                    )

                    async def record_verifying_stage() -> None:
                        await self.job_repo.update_stage(job=job, stage=JobStage.VERIFYING)
                        await lease_tracker.renew_heartbeat(job_id=job_id, worker_id=worker_id)

                    try:
                        await self.analysis_service.execute_analysis(
                            meeting_id=meeting_id,
                            user_id=job.user_id,
                            segments=list(db_segments),
                            on_stage_change=record_verifying_stage,
                        )
                    except Exception as exc:
                        raise ProcessingPipelineError(
                            f"Meeting intelligence extraction failed: {exc}",
                            error_code="ANALYSIS_FAILED",
                            is_retryable=False,
                        ) from exc

                # Stage 6: Release lease as COMPLETED
                current_meeting = await self.meeting_repo.get_by_id_system(meeting_id=meeting_id)
                if current_meeting is None or current_meeting.status in (
                    MeetingStatus.DELETING,
                    MeetingStatus.PURGED,
                ):
                    raise ProcessingPipelineError(
                        f"Meeting {meeting_id} deleted during processing",
                        error_code="MEETING_DELETED",
                        is_retryable=False,
                    )

                completed_job = await lease_tracker.release_lease(
                    job_id=job_id,
                    worker_id=worker_id,
                    target_status=JobStatus.COMPLETED,
                    target_stage=JobStage.COMPLETED,
                )
                await self._safe_commit()
                logger.info(
                    "Job %s completed successfully with %d transcript segments.",
                    job_id,
                    len(segments_payload),
                )
                return completed_job or job

        except ProcessingPipelineError as exc:
            logger.error(
                "ProcessingPipelineError for job %s: %s (retryable=%s)",
                job_id,
                exc.message,
                exc.is_retryable,
            )
            # Read attempt counters before rollback to avoid expired attribute reload
            attempt = job.attempt or 0
            max_attempts = job.max_attempts or 3

            # Roll back dirty state (e.g. partial analysis or transcript records)
            try:
                await self._safe_rollback()
            except Exception as rb_err:
                logger.warning("Session rollback warning for job %s: %s", job_id, rb_err)

            if exc.error_code == "MEETING_DELETED":
                # Meeting was deleted; cleanly mark job CANCELLED without retry
                await lease_tracker.release_lease(
                    job_id=job_id,
                    worker_id=worker_id,
                    target_status=JobStatus.CANCELLED,
                    target_stage=JobStage.FAILED,
                    error_code=exc.error_code,
                    error_message=exc.message,
                )
            elif exc.is_retryable and attempt < max_attempts:
                # Mark as PENDING so it can be re-attempted
                await lease_tracker.release_lease(
                    job_id=job_id,
                    worker_id=worker_id,
                    target_status=JobStatus.PENDING,
                    target_stage=JobStage.CREATED,
                    error_code=exc.error_code,
                    error_message=exc.message,
                )
            else:
                # Terminal failure
                await lease_tracker.release_lease(
                    job_id=job_id,
                    worker_id=worker_id,
                    target_status=JobStatus.FAILED,
                    target_stage=JobStage.FAILED,
                    error_code=exc.error_code,
                    error_message=exc.message,
                )
            try:
                await self._safe_commit()
            except Exception as commit_err:
                logger.error("Failed to commit job terminal state: %s", commit_err)
            raise
        except Exception as exc:
            logger.error("Unexpected error in pipeline for job %s: %s", job_id, exc, exc_info=True)
            # Roll back any uncommitted dirty state before setting terminal failure
            try:
                await self._safe_rollback()
            except Exception as rb_err:
                logger.warning("Session rollback warning for job %s: %s", job_id, rb_err)

            await lease_tracker.release_lease(
                job_id=job_id,
                worker_id=worker_id,
                target_status=JobStatus.FAILED,
                target_stage=JobStage.FAILED,
                error_code="UNEXPECTED_ERROR",
                error_message=str(exc),
            )
            try:
                await self._safe_commit()
            except Exception as commit_err:
                logger.error("Failed to commit job unexpected failure state: %s", commit_err)
            raise
