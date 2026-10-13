import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse

from app.api.deps import get_chat_service, get_current_user
from app.api.v1.utils import create_error_envelope, create_meta
from app.core.rate_limiter import general_read_limiter, rate_limit
from app.core.security import UserContext
from app.schemas.chat import ChatMessageResponse, ChatRequest, ChatResponse
from app.schemas.envelope import ErrorEnvelope, SuccessEnvelope
from app.services.chat_service import ChatService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/meetings", tags=["Chat"])


@router.post(
    "/{meeting_id}/chat",
    response_model=SuccessEnvelope[ChatResponse],
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(rate_limit(general_read_limiter))],
    responses={
        400: {"model": ErrorEnvelope},
        401: {"model": ErrorEnvelope},
        404: {"model": ErrorEnvelope},
        429: {"model": ErrorEnvelope},
    },
    summary="Ask questions about a meeting transcript with evidence citations",
)
async def post_meeting_chat(
    meeting_id: uuid.UUID,
    payload: ChatRequest,
    request: Request,
    current_user: Annotated[UserContext, Depends(get_current_user)],
    chat_service: Annotated[ChatService, Depends(get_chat_service)],
) -> JSONResponse:
    """Answers natural language questions strictly grounded in the meeting transcript."""
    try:
        response_data = await chat_service.answer_question(
            meeting_id=meeting_id,
            user_id=current_user.user_id,
            question=payload.question,
            session_id=payload.session_id,
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
            content=create_error_envelope("BAD_REQUEST", err_msg, request).model_dump(
                mode="json"
            ),
        )


@router.get(
    "/{meeting_id}/chat/messages",
    response_model=SuccessEnvelope[list[ChatMessageResponse]],
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(rate_limit(general_read_limiter))],
    responses={
        401: {"model": ErrorEnvelope},
        404: {"model": ErrorEnvelope},
        429: {"model": ErrorEnvelope},
    },
    summary="Get conversation history for a meeting",
)
async def get_meeting_chat_messages(
    meeting_id: uuid.UUID,
    request: Request,
    current_user: Annotated[UserContext, Depends(get_current_user)],
    chat_service: Annotated[ChatService, Depends(get_chat_service)],
    session_id: uuid.UUID | None = None,
) -> JSONResponse:
    """Retrieves conversation messages and citations for the meeting."""
    try:
        messages = await chat_service.get_messages(
            meeting_id=meeting_id,
            user_id=current_user.user_id,
            session_id=session_id,
        )
        envelope = SuccessEnvelope(data=messages, meta=create_meta(request))
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=envelope.model_dump(mode="json"),
        )
    except ValueError as err:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content=create_error_envelope("NOT_FOUND", str(err), request).model_dump(
                mode="json"
            ),
        )

