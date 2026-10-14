import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse

from app.api.deps import get_current_user, get_export_service
from app.api.v1.utils import create_error_envelope, create_meta
from app.core.rate_limiter import general_read_limiter, rate_limit
from app.core.security import UserContext
from app.schemas.envelope import ErrorEnvelope, SuccessEnvelope
from app.schemas.export import ExportRequest, ExportResponse
from app.services.export_service import ExportService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/meetings", tags=["Exports"])


@router.post(
    "/{meeting_id}/exports",
    response_model=SuccessEnvelope[ExportResponse],
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(rate_limit(general_read_limiter))],
    responses={
        400: {"model": ErrorEnvelope},
        401: {"model": ErrorEnvelope},
        404: {"model": ErrorEnvelope},
        429: {"model": ErrorEnvelope},
    },
    summary="Export meeting intelligence as Markdown or JSON",
)
async def export_meeting_analysis(
    meeting_id: uuid.UUID,
    payload: ExportRequest,
    request: Request,
    current_user: Annotated[UserContext, Depends(get_current_user)],
    export_service: Annotated[ExportService, Depends(get_export_service)],
) -> JSONResponse:
    """Exports structured meeting intelligence (executive summary, decisions, action items,
    risks, open questions, and transcript) formatted as Markdown or JSON.
    """
    try:
        response_data = await export_service.export_meeting(
            meeting_id=meeting_id,
            user_id=current_user.user_id,
            export_format=payload.format,
        )
        envelope = SuccessEnvelope(data=response_data, meta=create_meta(request))
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=envelope.model_dump(mode="json"),
        )
    except ValueError as err:
        err_msg = str(err)
        if "not found" in err_msg.lower():
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content=create_error_envelope("NOT_FOUND", err_msg, request).model_dump(
                    mode="json"
                ),
            )
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content=create_error_envelope("BAD_REQUEST", err_msg, request).model_dump(mode="json"),
        )
