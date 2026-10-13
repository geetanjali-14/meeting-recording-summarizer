import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agents.meeting_analysis_agent import MeetingAnalysisAgent
from app.agents.verification_agent import VerificationAgent
from app.core.config import Settings
from app.models.meeting_analysis import MeetingAnalysis
from app.models.transcript import TranscriptSegment
from app.providers.llm.base import LLMResponse, LLMUsage
from app.repositories.analysis_repository import AnalysisRepository
from app.schemas.analysis import (
    ActionItemOutput,
    DecisionConfidence,
    DecisionOutput,
    MeetingAnalysisOutput,
    TopicOutput,
)
from app.services.analysis_service import AnalysisService


@pytest.mark.asyncio
async def test_evidence_grounding_and_timestamp_derivation() -> None:
    analysis_repo = MagicMock(spec=AnalysisRepository)
    analysis_repo.get_by_meeting_id = AsyncMock(return_value=None)
    analysis_repo.create_analysis = AsyncMock()
    analysis_repo.add_topics = AsyncMock()
    analysis_repo.add_decisions = AsyncMock()
    analysis_repo.add_action_items = AsyncMock()
    analysis_repo.add_risks = AsyncMock()
    analysis_repo.add_open_questions = AsyncMock()

    analysis_agent = MagicMock(spec=MeetingAnalysisAgent)
    verification_agent = MagicMock(spec=VerificationAgent)

    settings = Settings(LLM_MODEL="gpt-oss-120b")
    service = AnalysisService(
        analysis_repo=analysis_repo,
        analysis_agent=analysis_agent,
        verification_agent=verification_agent,
        settings=settings,
    )

    meeting_id = uuid.uuid4()
    user_id = uuid.uuid4()
    seg1_id = uuid.uuid4()
    seg2_id = uuid.uuid4()
    fake_hallucinated_id = uuid.uuid4()

    db_segments = [
        TranscriptSegment(
            id=seg1_id,
            transcript_id=uuid.uuid4(),
            meeting_id=meeting_id,
            sequence_index=0,
            start_time=5.0,
            end_time=12.0,
            speaker_label="SPEAKER_00",
            speaker="Alice",
            text="We must use PostgreSQL.",
        ),
        TranscriptSegment(
            id=seg2_id,
            transcript_id=uuid.uuid4(),
            meeting_id=meeting_id,
            sequence_index=1,
            start_time=14.0,
            end_time=20.0,
            speaker_label="SPEAKER_01",
            speaker="Bob",
            text="Agreed. I will write migrations.",
        ),
    ]

    # Agent returns output containing real IDs and one hallucinated fake ID
    agent_output = MeetingAnalysisOutput(
        title="DB Decision",
        executive_summary="Team decided on PostgreSQL.",
        topics=[
            TopicOutput(
                title="Database",
                summary="PostgreSQL adoption.",
                sequence_index=0,
                evidence_segment_ids=[seg1_id, seg2_id],
            )
        ],
        decisions=[
            DecisionOutput(
                decision_text="Deploy PostgreSQL.",
                confidence=DecisionConfidence.EXPLICIT,
                sequence_index=0,
                evidence_segment_ids=[seg1_id, fake_hallucinated_id],  # fake ID should be filtered
            )
        ],
        action_items=[
            ActionItemOutput(
                action_text="Write migrations.",
                owner="Bob",
                due_date=None,
                sequence_index=0,
                evidence_segment_ids=[seg2_id],
            )
        ],
        risks=[],
        open_questions=[],
    )

    llm_resp = LLMResponse(
        provider="groq",
        model="openai/gpt-oss-120b",
        content="{}",
        usage=LLMUsage(prompt_tokens=200, completion_tokens=100, total_tokens=300),
    )
    analysis_agent.analyze_transcript.return_value = (agent_output, llm_resp)

    # Verification agent verifies owner "Bob" matches text in seg2
    verification_agent.verify_action_item_owner.return_value = True

    mock_analysis_record = MeetingAnalysis(
        id=uuid.uuid4(),
        meeting_id=meeting_id,
        user_id=user_id,
        provider="groq",
        model="openai/gpt-oss-120b",
    )
    analysis_repo.create_analysis.return_value = mock_analysis_record

    await service.execute_analysis(
        meeting_id=meeting_id,
        user_id=user_id,
        segments=db_segments,
    )

    # Assert create_analysis was called with valid cost calculation
    analysis_repo.create_analysis.assert_called_once()
    create_kwargs = analysis_repo.create_analysis.call_args.kwargs
    assert create_kwargs["prompt_tokens"] == 200
    assert create_kwargs["completion_tokens"] == 100
    assert isinstance(create_kwargs["estimated_cost_usd"], Decimal)

    # Assert timestamps were derived deterministically:
    # Topic spans seg1 (5.0s) and seg2 (20.0s) -> start=5.0, end=20.0
    topics_saved = analysis_repo.add_topics.call_args.args[2]
    assert topics_saved[0]["start_time"] == 5.0
    assert topics_saved[0]["end_time"] == 20.0

    # Decision had [seg1_id, fake_hallucinated_id] -> fake_hallucinated_id filtered out
    decisions_saved = analysis_repo.add_decisions.call_args.args[2]
    assert decisions_saved[0]["evidence_segment_ids"] == [seg1_id]
    assert decisions_saved[0]["start_time"] == 5.0
    assert decisions_saved[0]["end_time"] == 12.0
