import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.responses import JSONResponse

from app.api.deps import (
    get_current_user,
    get_meeting_service,
    get_upload_service,
)
from app.api.v1.utils import create_error_envelope, create_list_meta, create_meta
from app.core.rate_limiter import (
    create_meeting_limiter,
    general_read_limiter,
    rate_limit,
)
from app.core.security import UserContext
from app.schemas.envelope import ErrorEnvelope, ListEnvelope, SuccessEnvelope
from app.schemas.meeting import (
    MeetingCreateRequest,
    MeetingCreateResponseData,
    MeetingDetailResponseData,
    MeetingJobDetail,
    MeetingListItem,
    MeetingRecordingDetail,
)
from app.services.meeting_service import MeetingNotFoundError, MeetingService
from app.services.upload_service import (
    UploadService,
    UploadStorageError,
    UploadValidationError,
)

router = APIRouter(prefix="/meetings", tags=["Meetings"])


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=SuccessEnvelope[MeetingCreateResponseData],
    dependencies=[Depends(rate_limit(create_meeting_limiter))],
    responses={
        401: {"model": ErrorEnvelope},
        422: {"model": ErrorEnvelope},
        429: {"model": ErrorEnvelope},
        502: {"model": ErrorEnvelope},
    },
)
async def create_meeting(
    payload: MeetingCreateRequest,
    request: Request,
    current_user: Annotated[UserContext, Depends(get_current_user)],
    upload_service: Annotated[UploadService, Depends(get_upload_service)],
) -> JSONResponse:
    """Creates a meeting and issues a pre-signed PUT URL for direct client upload."""
    try:
        (
            meeting,
            recording,
            upload_url,
            upload_token,
            expires_in,
        ) = await upload_service.initiate_meeting_upload(
            user_id=current_user.user_id,
            request=payload,
            user_email=current_user.email,
        )
    except UploadValidationError as err:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=create_error_envelope("VALIDATION_ERROR", err.message, request).model_dump(
                mode="json"
            ),
        )
    except UploadStorageError as err:
        return JSONResponse(
            status_code=status.HTTP_502_BAD_GATEWAY,
            content=create_error_envelope("STORAGE_ERROR", err.message, request).model_dump(
                mode="json"
            ),
        )

    response_data = MeetingCreateResponseData(
        meeting_id=meeting.id,
        recording_id=recording.id,
        status=meeting.status.value,
        upload_url=upload_url,
        upload_token=upload_token,
        expires_in_seconds=expires_in,
    )
    envelope = SuccessEnvelope(data=response_data, meta=create_meta(request))
    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content=envelope.model_dump(mode="json"),
    )


@router.get(
    "",
    response_model=ListEnvelope[MeetingListItem],
    dependencies=[Depends(rate_limit(general_read_limiter))],
    responses={
        401: {"model": ErrorEnvelope},
        429: {"model": ErrorEnvelope},
    },
)
async def list_meetings(
    request: Request,
    current_user: Annotated[UserContext, Depends(get_current_user)],
    meeting_service: Annotated[MeetingService, Depends(get_meeting_service)],
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
) -> JSONResponse:
    """Lists meetings owned by the authenticated user with pagination."""
    items, total_count = await meeting_service.list_meetings(
        user_id=current_user.user_id,
        page=page,
        per_page=per_page,
    )
    meeting_list = [
        MeetingListItem(
            meeting_id=m.id,
            title=m.title,
            meeting_date=m.meeting_date,
            status=m.status.value,
            created_at=m.created_at,
        )
        for m in items
    ]
    meta = create_list_meta(
        request=request,
        total_count=total_count,
        page=page,
        per_page=per_page,
    )
    envelope = ListEnvelope(data=meeting_list, meta=meta)
    return JSONResponse(content=envelope.model_dump(mode="json"))


@router.get(
    "/{meeting_id}",
    response_model=SuccessEnvelope[MeetingDetailResponseData],
    dependencies=[Depends(rate_limit(general_read_limiter))],
    responses={
        401: {"model": ErrorEnvelope},
        404: {"model": ErrorEnvelope},
        429: {"model": ErrorEnvelope},
    },
)
async def get_meeting_details(
    meeting_id: uuid.UUID,
    request: Request,
    current_user: Annotated[UserContext, Depends(get_current_user)],
    meeting_service: Annotated[MeetingService, Depends(get_meeting_service)],
) -> JSONResponse:
    """Retrieves meeting details, enforcing strict tenant isolation."""
    try:
        meeting = await meeting_service.get_meeting_details(
            meeting_id=meeting_id,
            user_id=current_user.user_id,
        )
    except MeetingNotFoundError:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content=create_error_envelope("NOT_FOUND", "Meeting not found", request).model_dump(
                mode="json"
            ),
        )

    recording_dto = None
    if meeting.recording is not None:
        recording_dto = MeetingRecordingDetail(
            recording_id=meeting.recording.id,
            filename=meeting.recording.original_filename,
            content_type=meeting.recording.content_type,
            file_size_bytes=meeting.recording.file_size_bytes,
            status=meeting.recording.status.value,
        )

    job_dto = None
    if meeting.job is not None:
        job_dto = MeetingJobDetail(
            job_id=meeting.job.id,
            status=meeting.job.status.value,
            attempt=meeting.job.attempt,
        )

    response_data = MeetingDetailResponseData(
        meeting_id=meeting.id,
        title=meeting.title,
        description=meeting.description,
        meeting_date=meeting.meeting_date,
        status=meeting.status.value,
        created_at=meeting.created_at or datetime.now(UTC),
        recording=recording_dto,
        job=job_dto,
    )
    envelope = SuccessEnvelope(data=response_data, meta=create_meta(request))
    return JSONResponse(content=envelope.model_dump(mode="json"))


@router.delete(
    "/{meeting_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        401: {"model": ErrorEnvelope},
        404: {"model": ErrorEnvelope},
    },
)
async def delete_meeting(
    meeting_id: uuid.UUID,
    request: Request,
    current_user: Annotated[UserContext, Depends(get_current_user)],
    meeting_service: Annotated[MeetingService, Depends(get_meeting_service)],
) -> Response:
    """Deletes a meeting cascading cleanly across storage and database."""
    try:
        await meeting_service.delete_meeting(
            meeting_id=meeting_id,
            user_id=current_user.user_id,
        )
    except MeetingNotFoundError:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content=create_error_envelope("NOT_FOUND", "Meeting not found", request).model_dump(
                mode="json"
            ),
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
