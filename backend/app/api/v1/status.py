import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db_session
from app.api.v1.utils import create_error_envelope, create_meta
from app.core.security import UserContext
from app.repositories.job_repository import JobRepository
from app.repositories.meeting_repository import MeetingRepository
from app.schemas.envelope import ErrorEnvelope, SuccessEnvelope
from app.schemas.status import JobStatusResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/meetings", tags=["Status"])


@router.get(
    "/{meeting_id}/status",
    response_model=SuccessEnvelope[JobStatusResponse],
    status_code=status.HTTP_200_OK,
    responses={
        401: {"model": ErrorEnvelope},
        404: {"model": ErrorEnvelope},
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
    )

    envelope = SuccessEnvelope(data=response_data, meta=create_meta(request))
    return JSONResponse(content=envelope.model_dump(mode="json"))
