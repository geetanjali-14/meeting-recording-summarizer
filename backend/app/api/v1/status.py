import asyncio
import json
import logging
import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db_session
from app.api.v1.utils import create_error_envelope, create_meta
from app.core.database import async_session_factory
from app.core.rate_limiter import rate_limit, status_polling_limiter
from app.core.security import UserContext
from app.models.processing_job import JobStage, JobStatus
from app.repositories.job_repository import JobRepository
from app.repositories.meeting_repository import MeetingRepository
from app.schemas.envelope import ErrorEnvelope, SuccessEnvelope
from app.schemas.status import JobStatusResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/meetings", tags=["Status"])


def _calculate_elapsed(job) -> float | None:
    if job.started_at:
        end_time = job.completed_at or datetime.now(UTC)
        return round((end_time - job.started_at).total_seconds(), 1)
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
        attempt=job.attempt,
        error_code=job.error_code,
        error_message=job.error_message,
        started_at=job.started_at.isoformat() if job.started_at else None,
        completed_at=job.completed_at.isoformat() if job.completed_at else None,
        elapsed_seconds=_calculate_elapsed(job),
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
) -> StreamingResponse:
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
                    yield f"event: error\ndata: {json.dumps({'message': 'Stream exceeded maximum duration'})}\n\n"
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
                            "completed_at": job.completed_at.isoformat() if job.completed_at else None,
                            "elapsed_seconds": _calculate_elapsed(job),
                        }
                        yield f"event: status\ndata: {json.dumps(status_payload)}\n\n"

                        if job.status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
                            # Clean closure after publishing terminal event
                            yield f"event: done\ndata: {json.dumps({'status': job.status.value})}\n\n"
                            break
                    else:
                        # Send lightweight comment heartbeat to prevent Render / Cloudflare proxy timeout
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
