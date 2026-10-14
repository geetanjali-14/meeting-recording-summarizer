import asyncio
import logging
import uuid
from typing import Any

from celery import Task  # type: ignore[import-untyped]

from app.agents.meeting_analysis_agent import MeetingAnalysisAgent
from app.agents.verification_agent import VerificationAgent
from app.core.celery_app import celery_app
from app.core.config import get_settings
from app.core.database import get_session
from app.providers.diarization import get_diarization_provider
from app.providers.llm import get_llm_provider
from app.providers.storage import get_storage_provider
from app.providers.transcription import get_transcription_provider
from app.repositories.analysis_repository import AnalysisRepository
from app.repositories.job_repository import JobRepository
from app.repositories.meeting_repository import MeetingRepository
from app.repositories.recording_repository import RecordingRepository
from app.repositories.transcript_repository import TranscriptRepository
from app.services.alignment_service import AlignmentService
from app.services.analysis_service import AnalysisService
from app.services.audio_service import AudioService
from app.services.diarization_service import DiarizationService
from app.services.processing_service import ProcessingPipelineError, ProcessingService
from app.workers.job_lease import JobLeaseTracker

logger = logging.getLogger(__name__)


class ProcessingTask(Task):  # type: ignore[misc]
    """Custom Celery Task base with retry logic and late ack handling."""

    autoretry_for = ()
    max_retries = 3
    default_retry_delay = 5  # seconds exponential backoff


@celery_app.task(
    name="process_meeting_recording",
    bind=True,
    base=ProcessingTask,
    acks_late=True,
    reject_on_worker_lost=True,
)
def process_meeting_recording(self: Task, job_id_str: str, meeting_id_str: str) -> dict[str, Any]:
    """Celery background task orchestrating the recording-to-transcript processing pipeline."""
    job_id = uuid.UUID(job_id_str)
    meeting_id = uuid.UUID(meeting_id_str)
    worker_id = getattr(self.request, "hostname", None) or f"worker_{uuid.uuid4().hex[:8]}"

    logger.info(
        "Celery task started: process_meeting_recording",
        extra={
            "job_id": str(job_id),
            "meeting_id": str(meeting_id),
            "celery_task_id": self.request.id,
            "worker_id": worker_id,
        },
    )

    async def _run() -> dict[str, Any]:
        settings = get_settings()
        async with get_session() as session:
            job_repo = JobRepository(session)
            meeting_repo = MeetingRepository(session)
            recording_repo = RecordingRepository(session)
            transcript_repo = TranscriptRepository(session)
            analysis_repo = AnalysisRepository(session)
            storage_provider = get_storage_provider(settings)
            audio_service = AudioService()
            transcription_provider = get_transcription_provider(settings)
            diarization_provider = get_diarization_provider(settings)
            diarization_service = DiarizationService(diarization_provider, settings)
            alignment_service = AlignmentService()

            llm_provider = get_llm_provider(settings)
            analysis_agent = MeetingAnalysisAgent(llm_provider, settings)
            verification_agent = VerificationAgent(llm_provider, settings)
            analysis_service = AnalysisService(
                analysis_repo=analysis_repo,
                analysis_agent=analysis_agent,
                verification_agent=verification_agent,
                settings=settings,
            )

            lease_tracker = JobLeaseTracker(
                session,
                lease_duration_seconds=settings.WORKER_LEASE_DURATION_SECONDS,
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
                diarization_service=diarization_service,
                alignment_service=alignment_service,
                analysis_service=analysis_service,
            )

            job = await service.execute_job(
                job_id=job_id,
                meeting_id=meeting_id,
                worker_id=worker_id,
                lease_tracker=lease_tracker,
            )

            return {
                "job_id": str(job.id),
                "meeting_id": str(job.meeting_id),
                "status": job.status.value,
                "stage": job.stage.value,
            }

    try:
        return asyncio.run(_run())

    except ProcessingPipelineError as exc:
        if exc.is_retryable and self.request.retries < self.max_retries:
            logger.warning(
                "Retryable error in process_meeting_recording: %s. Scheduling retry.",
                exc.message,
            )
            countdown = 2**self.request.retries * 5
            raise self.retry(exc=exc, countdown=countdown) from exc
        logger.error("Terminal failure in process_meeting_recording: %s", exc.message)
        raise
    except Exception as exc:
        logger.error("Unhandled failure in process_meeting_recording: %s", exc, exc_info=True)
        raise
