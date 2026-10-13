import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db_session
from app.api.v1.utils import create_error_envelope, create_meta
from app.core.security import UserContext
from app.repositories.meeting_repository import MeetingRepository
from app.repositories.transcript_repository import TranscriptRepository
from app.schemas.envelope import ErrorEnvelope, SuccessEnvelope
from app.schemas.status import TranscriptResponse, TranscriptSegmentResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/meetings", tags=["Transcript"])


@router.get(
    "/{meeting_id}/transcript",
    response_model=SuccessEnvelope[TranscriptResponse],
    status_code=status.HTTP_200_OK,
    responses={
        401: {"model": ErrorEnvelope},
        404: {"model": ErrorEnvelope},
    },
    summary="Get transcript segments of a meeting recording",
)
async def get_transcript(
    meeting_id: uuid.UUID,
    request: Request,
    current_user: Annotated[UserContext, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> JSONResponse:
    """Retrieves chronological transcript segments and speaker labels for a meeting."""
    meeting_repo = MeetingRepository(session)
    meeting = await meeting_repo.get_by_id(meeting_id=meeting_id, user_id=current_user.user_id)
    if meeting is None:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content=create_error_envelope("NOT_FOUND", "Meeting not found", request).model_dump(
                mode="json"
            ),
        )

    transcript_repo = TranscriptRepository(session)
    transcript = await transcript_repo.get_by_meeting_id(
        meeting_id=meeting_id, user_id=current_user.user_id
    )
    if transcript is None:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content=create_error_envelope("NOT_FOUND", "Transcript not found", request).model_dump(
                mode="json"
            ),
        )

    segments = await transcript_repo.get_segments_by_transcript(transcript_id=transcript.id)

    response_data = TranscriptResponse(
        transcript_id=transcript.id,
        language=transcript.language,
        total_duration_seconds=transcript.total_duration_seconds,
        segment_count=len(segments),
        segments=[
            TranscriptSegmentResponse(
                segment_id=seg.id,
                sequence_index=seg.sequence_index,
                start_time=seg.start_time,
                end_time=seg.end_time,
                speaker_label=seg.speaker_label,
                speaker=seg.speaker or seg.speaker_label,
                text=seg.text,
            )
            for seg in segments
        ],
    )

    envelope = SuccessEnvelope(data=response_data, meta=create_meta(request))
    return JSONResponse(content=envelope.model_dump(mode="json"))
