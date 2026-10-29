import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db_session
from app.api.v1.utils import create_error_envelope, create_meta
from app.core.rate_limiter import general_read_limiter, rate_limit
from app.core.security import UserContext
from app.repositories.analysis_repository import AnalysisRepository
from app.repositories.meeting_repository import MeetingRepository
from app.schemas.analysis import (
    ActionItemResponse,
    DecisionConfidence,
    DecisionResponse,
    MeetingAnalysisResponse,
    OpenQuestionResponse,
    RiskResponse,
    TopicResponse,
)
from app.schemas.envelope import ErrorEnvelope, SuccessEnvelope

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/meetings", tags=["Analysis"])


@router.get(
    "/{meeting_id}/analysis",
    response_model=SuccessEnvelope[MeetingAnalysisResponse],
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(rate_limit(general_read_limiter))],
    responses={
        401: {"model": ErrorEnvelope},
        404: {"model": ErrorEnvelope},
        429: {"model": ErrorEnvelope},
    },
    summary="Get structured meeting intelligence and evidence citations",
)
async def get_meeting_analysis(
    meeting_id: uuid.UUID,
    request: Request,
    current_user: Annotated[UserContext, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> JSONResponse:
    """Retrieves structured meeting intelligence (executive summary, topics, decisions,
    action items, risks, and questions) with evidence segment citations.
    """
    meeting_repo = MeetingRepository(session)
    meeting = await meeting_repo.get_by_id(meeting_id=meeting_id, user_id=current_user.user_id)
    if meeting is None:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content=create_error_envelope("NOT_FOUND", "Meeting not found", request).model_dump(
                mode="json"
            ),
        )

    analysis_repo = AnalysisRepository(session)
    analysis = await analysis_repo.get_by_meeting_id(
        meeting_id=meeting_id,
        user_id=current_user.user_id,
        include_children=True,
    )
    if analysis is None:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content=create_error_envelope(
                "NOT_FOUND", "Meeting analysis not found", request
            ).model_dump(mode="json"),
        )

    response_data = MeetingAnalysisResponse(
        analysis_id=analysis.id,
        title=analysis.title,
        executive_summary=analysis.executive_summary,
        model=analysis.model,
        estimated_cost_usd=float(analysis.estimated_cost_usd)
        if analysis.estimated_cost_usd is not None
        else None,
        topics=[
            TopicResponse(
                topic_id=t.id,
                sequence_index=t.sequence_index,
                title=t.title,
                summary=t.summary,
                discussion_progression=t.discussion_progression,
                start_time=t.start_time,
                end_time=t.end_time,
            )
            for t in sorted(analysis.topics, key=lambda x: x.sequence_index)
        ],
        decisions=[
            DecisionResponse(
                decision_id=d.id,
                sequence_index=d.sequence_index,
                decision_text=d.decision_text,
                confidence=DecisionConfidence(d.confidence.value),
                start_time=d.start_time,
                end_time=d.end_time,
                evidence_segment_ids=d.evidence_segment_ids or [],
            )
            for d in sorted(analysis.decisions, key=lambda x: x.sequence_index)
        ],
        action_items=[
            ActionItemResponse(
                action_item_id=a.id,
                sequence_index=a.sequence_index,
                action_text=a.action_text,
                owner=a.owner,
                due_date=a.due_date,
                start_time=a.start_time,
                end_time=a.end_time,
                evidence_segment_ids=a.evidence_segment_ids or [],
            )
            for a in sorted(analysis.action_items, key=lambda x: x.sequence_index)
        ],
        risks=[
            RiskResponse(
                risk_id=r.id,
                sequence_index=r.sequence_index,
                risk_text=r.risk_text,
                start_time=r.start_time,
                end_time=r.end_time,
                evidence_segment_ids=r.evidence_segment_ids or [],
            )
            for r in sorted(analysis.risks, key=lambda x: x.sequence_index)
        ],
        open_questions=[
            OpenQuestionResponse(
                question_id=q.id,
                sequence_index=q.sequence_index,
                question_text=q.question_text,
                start_time=q.start_time,
                end_time=q.end_time,
                evidence_segment_ids=q.evidence_segment_ids or [],
            )
            for q in sorted(analysis.open_questions, key=lambda x: x.sequence_index)
        ],
        speaker_contributions=analysis.speaker_contributions or {},
        context_and_details=analysis.context_and_details or [],
        next_steps=analysis.next_steps or [],
    )

    envelope = SuccessEnvelope(data=response_data, meta=create_meta(request))
    return JSONResponse(content=envelope.model_dump(mode="json"))
