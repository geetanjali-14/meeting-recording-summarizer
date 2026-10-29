import asyncio
import json
import logging
import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db_session
from app.api.v1.utils import create_error_envelope, create_meta
from app.core.celery_app import celery_app
from app.core.database import async_session_factory
from app.core.rate_limiter import job_control_limiter, rate_limit, status_polling_limiter
from app.core.security import UserContext
from app.models.meeting_analysis import MeetingAnalysis
from app.models.processing_job import JobStage, JobStatus, ProcessingJob
from app.models.transcript import Transcript
from app.repositories.analysis_repository import AnalysisRepository
from app.repositories.job_repository import JobRepository
from app.repositories.meeting_repository import MeetingRepository
from app.repositories.transcript_repository import TranscriptRepository
from app.schemas.envelope import ErrorEnvelope, SuccessEnvelope
from app.schemas.status import JobStatusResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/meetings", tags=["Status"])


def _calculate_elapsed(job: ProcessingJob | Any) -> float | None:
    started_at = getattr(job, "started_at", None)
    if isinstance(started_at, datetime):
        completed_at = getattr(job, "completed_at", None)
        end_time: datetime = (
            completed_at if isinstance(completed_at, datetime) else datetime.now(UTC)
        )
        return float(round((end_time - started_at).total_seconds(), 1))
    return None


@router.get(
    "/{meeting_id}/status",
    response_model=SuccessEnvelope[JobStatusResponse],
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(rate_limit(status_polling_limiter))],
    responses={
        401: {"model": ErrorEnvelope},
        404: {"model": ErrorEnvelope},
        429: {"model": ErrorEnvelope},
    },
    summary="Get processing status of a meeting recording",
)
async def get_processing_status(
    meeting_id: uuid.UUID,
    request: Request,
    current_user: Annotated[UserContext, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> JSONResponse:
    """Retrieves current processing job status and pipeline stage for a meeting."""
    meeting_repo = MeetingRepository(session)
    meeting = await meeting_repo.get_by_id(meeting_id=meeting_id, user_id=current_user.user_id)
    if meeting is None:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content=create_error_envelope("NOT_FOUND", "Meeting not found", request).model_dump(
                mode="json"
            ),
        )

    job_repo = JobRepository(session)
    job = await job_repo.get_by_meeting_id(meeting_id=meeting_id, user_id=current_user.user_id)
    if job is None:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content=create_error_envelope(
                "NOT_FOUND", "Processing job not found", request
            ).model_dump(mode="json"),
        )

    response_data = JobStatusResponse(
        meeting_id=job.meeting_id,
        job_id=job.id,
        celery_task_id=job.celery_task_id,
        status=job.status,
        stage=job.stage,
        attempt=job.attempt or 0,
        error_code=job.error_code,
        error_message=job.error_message,
        started_at=job.started_at.isoformat() if job.started_at else None,
        completed_at=job.completed_at.isoformat() if job.completed_at else None,
        elapsed_seconds=_calculate_elapsed(job),
    )

    envelope = SuccessEnvelope(data=response_data, meta=create_meta(request))
    return JSONResponse(content=envelope.model_dump(mode="json"))


@router.post(
    "/{meeting_id}/retry",
    response_model=SuccessEnvelope[JobStatusResponse],
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(rate_limit(job_control_limiter))],
    responses={
        401: {"model": ErrorEnvelope},
        404: {"model": ErrorEnvelope},
        409: {"model": ErrorEnvelope},
        429: {"model": ErrorEnvelope},
        500: {"model": ErrorEnvelope},
        503: {"model": ErrorEnvelope},
    },
    summary="Retry a failed or stalled processing job from the earliest incomplete step",
)
async def retry_processing_job(
    meeting_id: uuid.UUID,
    request: Request,
    current_user: Annotated[UserContext, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> JSONResponse:
    """Retries a failed, cancelled, or lease-expired job without discarding valid saved outputs."""
    meeting_repo = MeetingRepository(session)
    meeting = await meeting_repo.get_by_id(meeting_id=meeting_id, user_id=current_user.user_id)
    if meeting is None:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content=create_error_envelope("NOT_FOUND", "Meeting not found", request).model_dump(
                mode="json"
            ),
        )

    job_repo = JobRepository(session)
    job = await job_repo.get_by_meeting_id(
        meeting_id=meeting_id, user_id=current_user.user_id, for_update=True
    )
    if job is None:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content=create_error_envelope(
                "NOT_FOUND", "Processing job not found", request
            ).model_dump(mode="json"),
        )

    # Concurrency & Idempotency check: Stale worker protection
    now = datetime.now(UTC)
    is_active_running = (
        job.status == JobStatus.RUNNING
        and job.lease_expires_at is not None
        and job.lease_expires_at > now
    )
    if is_active_running:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content=create_error_envelope(
                "JOB_ACTIVE",
                "A worker is actively processing this meeting. Cannot retry while running.",
                request,
            ).model_dump(mode="json"),
        )

    if job.status == JobStatus.PENDING:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content=create_error_envelope(
                "JOB_PENDING",
                "Job is already pending execution in the queue.",
                request,
            ).model_dump(mode="json"),
        )

    # Transition job to PENDING
    job.status = JobStatus.PENDING
    job.worker_id = None
    job.lease_expires_at = None
    job.claimed_at = None
    job.heartbeat_at = None
    job.error_code = None
    job.error_message = None
    job.started_at = None
    job.completed_at = None
    job.enqueued_at = now

    # Dispatch Celery task safely
    task_name = "process_meeting_recording"
    try:
        celery_result = celery_app.send_task(
            task_name,
            args=[str(job.id), str(meeting.id)],
        )
        job.celery_task_id = celery_result.id
        await session.commit()
    except Exception as exc:
        logger.error(
            "Failed to dispatch Celery retry task for meeting %s: %s",
            meeting_id,
            exc,
            exc_info=True,
        )
        job.status = JobStatus.FAILED
        job.error_code = "DISPATCH_FAILED"
        job.error_message = f"Failed to queue background worker: {exc}"
        await session.commit()
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=create_error_envelope(
                "DISPATCH_FAILED",
                f"Failed to queue background worker: {exc}",
                request,
            ).model_dump(mode="json"),
        )

    response_data = JobStatusResponse(
        meeting_id=job.meeting_id,
        job_id=job.id,
        celery_task_id=job.celery_task_id,
        status=job.status,
        stage=job.stage,
        attempt=job.attempt or 0,
        error_code=job.error_code,
        error_message=job.error_message,
        started_at=None,
        completed_at=None,
        elapsed_seconds=None,
    )
    envelope = SuccessEnvelope(data=response_data, meta=create_meta(request))
    return JSONResponse(content=envelope.model_dump(mode="json"))


@router.post(
    "/{meeting_id}/restart",
    response_model=SuccessEnvelope[JobStatusResponse],
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(rate_limit(job_control_limiter))],
    responses={
        401: {"model": ErrorEnvelope},
        404: {"model": ErrorEnvelope},
        409: {"model": ErrorEnvelope},
        429: {"model": ErrorEnvelope},
        500: {"model": ErrorEnvelope},
        503: {"model": ErrorEnvelope},
    },
    summary="Restart the processing pipeline from the original recording with clean state",
)
async def restart_processing_job(
    meeting_id: uuid.UUID,
    request: Request,
    current_user: Annotated[UserContext, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> JSONResponse:
    """Restarts processing from the beginning, clearing previously generated transcripts and analysis."""
    meeting_repo = MeetingRepository(session)
    meeting = await meeting_repo.get_by_id(meeting_id=meeting_id, user_id=current_user.user_id)
    if meeting is None:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content=create_error_envelope("NOT_FOUND", "Meeting not found", request).model_dump(
                mode="json"
            ),
        )

    job_repo = JobRepository(session)
    job = await job_repo.get_by_meeting_id(
        meeting_id=meeting_id, user_id=current_user.user_id, for_update=True
    )
    if job is None:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content=create_error_envelope(
                "NOT_FOUND", "Processing job not found", request
            ).model_dump(mode="json"),
        )

    now = datetime.now(UTC)
    is_active_running = (
        job.status == JobStatus.RUNNING
        and job.lease_expires_at is not None
        and job.lease_expires_at > now
    )
    if is_active_running:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content=create_error_envelope(
                "JOB_ACTIVE",
                "A worker is actively processing this meeting. Cannot restart while running.",
                request,
            ).model_dump(mode="json"),
        )

    # Clean existing generated artifacts (Transcript, TranscriptSegment, MeetingAnalysis, and children)
    analysis_repo = AnalysisRepository(session)
    existing_analysis = await analysis_repo.get_by_meeting_id(
        meeting_id=meeting_id, user_id=current_user.user_id
    )
    if existing_analysis:
        await analysis_repo.delete_child_entities(existing_analysis.id)
        await session.delete(existing_analysis)
        await session.flush()

    transcript_repo = TranscriptRepository(session)
    existing_transcript = await transcript_repo.get_by_meeting_id(
        meeting_id=meeting_id, user_id=current_user.user_id
    )
    if existing_transcript:
        await transcript_repo.delete_segments(existing_transcript.id)
        await session.delete(existing_transcript)
        await session.flush()

    # Reset job to fresh PENDING / CREATED state
    job.status = JobStatus.PENDING
    job.stage = JobStage.CREATED
    job.attempt = 0
    job.worker_id = None
    job.lease_expires_at = None
    job.claimed_at = None
    job.heartbeat_at = None
    job.error_code = None
    job.error_message = None
    job.started_at = None
    job.completed_at = None
    job.enqueued_at = now

    # Dispatch Celery task safely
    task_name = "process_meeting_recording"
    try:
        celery_result = celery_app.send_task(
            task_name,
            args=[str(job.id), str(meeting.id)],
        )
        job.celery_task_id = celery_result.id
        await session.commit()
    except Exception as exc:
        logger.error(
            "Failed to dispatch Celery restart task for meeting %s: %s",
            meeting_id,
            exc,
            exc_info=True,
        )
        job.status = JobStatus.FAILED
        job.error_code = "DISPATCH_FAILED"
        job.error_message = f"Failed to queue background worker: {exc}"
        await session.commit()
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=create_error_envelope(
                "DISPATCH_FAILED",
                f"Failed to queue background worker: {exc}",
                request,
            ).model_dump(mode="json"),
        )

    response_data = JobStatusResponse(
        meeting_id=job.meeting_id,
        job_id=job.id,
        celery_task_id=job.celery_task_id,
        status=job.status,
        stage=job.stage,
        attempt=job.attempt or 0,
        error_code=job.error_code,
        error_message=job.error_message,
        started_at=None,
        completed_at=None,
        elapsed_seconds=None,
    )
    envelope = SuccessEnvelope(data=response_data, meta=create_meta(request))
    return JSONResponse(content=envelope.model_dump(mode="json"))


@router.get(
    "/{meeting_id}/events",
    responses={
        401: {"model": ErrorEnvelope},
        404: {"model": ErrorEnvelope},
    },
    summary="Stream realtime pipeline progress events via Server-Sent Events (SSE)",
)
async def stream_processing_events(
    meeting_id: uuid.UUID,
    request: Request,
    current_user: Annotated[UserContext, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> Response:
    """Streams real-time pipeline status and stage changes via SSE.

    Replaces continuous status polling with one resilient SSE stream per active meeting.
    Emits an initial snapshot immediately upon connect, heartbeats to keep proxy connections alive,
    and publishes stage transitions cleanly until terminal state (COMPLETED / FAILED) or disconnect.
    """
    # 1. Authorize tenant access to meeting
    meeting_repo = MeetingRepository(session)
    meeting = await meeting_repo.get_by_id(meeting_id=meeting_id, user_id=current_user.user_id)
    if meeting is None:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content=create_error_envelope("NOT_FOUND", "Meeting not found", request).model_dump(
                mode="json"
            ),
        )

    async def event_generator() -> AsyncGenerator[str, None]:
        last_status: JobStatus | None = None
        last_stage: JobStage | None = None
        last_error: str | None = None
        max_duration_seconds = 900  # 15 minutes max stream duration
        stream_start = datetime.now(UTC)

        try:
            while True:
                if await request.is_disconnected():
                    logger.debug("Client disconnected from SSE stream for meeting %s", meeting_id)
                    break

                now = datetime.now(UTC)
                if (now - stream_start).total_seconds() > max_duration_seconds:
                    timeout_msg = json.dumps({"message": "Stream exceeded maximum duration"})
                    yield f"event: error\ndata: {timeout_msg}\n\n"
                    break

                async with async_session_factory() as poll_session:
                    job_repo = JobRepository(poll_session)
                    job = await job_repo.get_by_meeting_id(
                        meeting_id=meeting_id, user_id=current_user.user_id
                    )

                    if job is None:
                        yield f"event: error\ndata: {json.dumps({'message': 'Job not found'})}\n\n"
                        break

                    has_changed = (
                        job.status != last_status
                        or job.stage != last_stage
                        or job.error_message != last_error
                    )

                    if has_changed:
                        last_status = job.status
                        last_stage = job.stage
                        last_error = job.error_message

                        status_payload = {
                            "meeting_id": str(job.meeting_id),
                            "job_id": str(job.id),
                            "celery_task_id": job.celery_task_id,
                            "status": job.status.value,
                            "stage": job.stage.value,
                            "attempt": job.attempt,
                            "error_code": job.error_code,
                            "error_message": job.error_message,
                            "started_at": job.started_at.isoformat() if job.started_at else None,
                            "completed_at": (
                                job.completed_at.isoformat() if job.completed_at else None
                            ),
                            "elapsed_seconds": _calculate_elapsed(job),
                        }
                        yield f"event: status\ndata: {json.dumps(status_payload)}\n\n"

                        is_terminal = job.status in (
                            JobStatus.COMPLETED,
                            JobStatus.FAILED,
                            JobStatus.CANCELLED,
                        )
                        if is_terminal:
                            # Clean closure after publishing terminal event
                            done_payload = json.dumps({"status": job.status.value})
                            yield f"event: done\ndata: {done_payload}\n\n"
                            break
                    else:
                        # Send comment heartbeat to prevent Render/Cloudflare proxy timeout
                        yield ": ping\n\n"

                await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            logger.debug("SSE stream cancelled for meeting %s", meeting_id)
            raise

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disables proxy buffering in Nginx / Render
        },
    )
