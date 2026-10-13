import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse

from app.api.deps import (
    get_current_user,
    get_upload_service,
)
from app.api.v1.utils import create_error_envelope, create_meta
from app.core.security import UserContext
from app.schemas.envelope import ErrorEnvelope, SuccessEnvelope
from app.schemas.upload import ConfirmUploadRequest, ConfirmUploadResponseData
from app.services.upload_service import (
    UploadConflictError,
    UploadDispatchError,
    UploadNotFoundError,
    UploadService,
    UploadStorageError,
    UploadValidationError,
)

router = APIRouter(prefix="/meetings", tags=["Uploads"])


@router.post(
    "/{meeting_id}/confirm-upload",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=SuccessEnvelope[ConfirmUploadResponseData],
    responses={
        401: {"model": ErrorEnvelope},
        404: {"model": ErrorEnvelope},
        409: {"model": ErrorEnvelope},
        422: {"model": ErrorEnvelope},
        502: {"model": ErrorEnvelope},
    },
)
async def confirm_upload(
    meeting_id: uuid.UUID,
    payload: ConfirmUploadRequest,
    request: Request,
    current_user: Annotated[UserContext, Depends(get_current_user)],
    upload_service: Annotated[UploadService, Depends(get_upload_service)],
) -> JSONResponse:
    """Confirms direct storage upload, transitions statuses, and dispatches background ingestion task."""
    try:
        meeting, job = await upload_service.confirm_upload(
            meeting_id=meeting_id,
            recording_id=payload.recording_id,
            upload_token=payload.upload_token,
            user_id=current_user.user_id,
        )
    except UploadNotFoundError as err:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content=create_error_envelope("NOT_FOUND", err.message, request).model_dump(
                mode="json"
            ),
        )
    except UploadValidationError as err:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=create_error_envelope("VALIDATION_ERROR", err.message, request).model_dump(
                mode="json"
            ),
        )
    except UploadConflictError as err:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content=create_error_envelope("CONFLICT", err.message, request).model_dump(
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
    except UploadDispatchError as err:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=create_error_envelope("INTERNAL_ERROR", err.message, request).model_dump(
                mode="json"
            ),
        )

    response_data = ConfirmUploadResponseData(
        meeting_id=meeting.id,
        job_id=job.id,
        status=meeting.status.value,
        job_status=job.status.value,
    )
    envelope = SuccessEnvelope(data=response_data, meta=create_meta(request))
    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content=envelope.model_dump(mode="json"),
    )
