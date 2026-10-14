import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.config import Settings
from app.models.chat import ChatMessage, ChatRole, ChatSession
from app.models.meeting import Meeting, MeetingStatus
from app.models.transcript import Transcript, TranscriptSegment
from app.providers.llm.base import LLMResponse, LLMUsage
from app.services.chat_service import ChatService


@pytest.mark.asyncio
async def test_chat_service_answers_question_with_grounded_citations() -> None:
    # 1. Setup mocks
    meeting_id = uuid.uuid4()
    user_id = uuid.uuid4()
    seg1_id = uuid.uuid4()
    seg2_id = uuid.uuid4()

    mock_meeting = Meeting(
        id=meeting_id,
        user_id=user_id,
        title="Architecture Sync",
        status=MeetingStatus.ACTIVE,
    )
    mock_transcript = Transcript(
        id=uuid.uuid4(),
        meeting_id=meeting_id,
        user_id=user_id,
        provider="groq",
    )
    mock_segments = [
        TranscriptSegment(
            id=seg1_id,
            transcript_id=mock_transcript.id,
            meeting_id=meeting_id,
            sequence_index=0,
            start_time=10.0,
            end_time=25.0,
            speaker_label="SPEAKER_00",
            speaker="Alex",
            text="We decided to use PostgreSQL from day one with psycopg.",
        ),
        TranscriptSegment(
            id=seg2_id,
            transcript_id=mock_transcript.id,
            meeting_id=meeting_id,
            sequence_index=1,
            start_time=30.0,
            end_time=45.0,
            speaker_label="SPEAKER_01",
            speaker="Dana",
            text="Agreed, and Celery will consume tasks from Redis with acks_late.",
        ),
    ]

    mock_meeting_repo = AsyncMock()
    mock_meeting_repo.get_by_id.return_value = mock_meeting

    mock_transcript_repo = AsyncMock()
    mock_transcript_repo.get_by_meeting_id.return_value = mock_transcript
    mock_transcript_repo.get_segments_by_transcript.return_value = mock_segments

    mock_chat_session = ChatSession(
        id=uuid.uuid4(),
        meeting_id=meeting_id,
        user_id=user_id,
        title="Test Session",
    )
    mock_assistant_msg = ChatMessage(
        id=uuid.uuid4(),
        session_id=mock_chat_session.id,
        meeting_id=meeting_id,
        user_id=user_id,
        role=ChatRole.ASSISTANT,
        content="The team selected PostgreSQL from day one with psycopg.",
        citation_segment_ids=[seg1_id],
    )

    mock_chat_repo = AsyncMock()
    mock_chat_repo.get_or_create_session.return_value = mock_chat_session
    mock_chat_repo.add_message.return_value = mock_assistant_msg

    mock_llm_provider = MagicMock()
    mock_llm_provider.generate_structured.return_value = LLMResponse(
        provider="mock",
        model="gpt-oss-120b",
        content="",
        parsed_json={
            "answer": "The team selected PostgreSQL from day one with psycopg.",
            "cited_segment_ids": [str(seg1_id)],
        },
        usage=LLMUsage(prompt_tokens=100, completion_tokens=30, total_tokens=130),
    )

    settings = Settings()
    service = ChatService(
        meeting_repo=mock_meeting_repo,
        transcript_repo=mock_transcript_repo,
        chat_repo=mock_chat_repo,
        llm_provider=mock_llm_provider,
        settings=settings,
    )

    # Execute
    res = await service.answer_question(
        meeting_id=meeting_id,
        user_id=user_id,
        question="What database was chosen?",
    )

    # Verify
    assert res.session_id == mock_chat_session.id
    assert res.message.content == "The team selected PostgreSQL from day one with psycopg."
    assert len(res.message.citations) == 1
    assert res.message.citations[0].segment_id == seg1_id
    assert res.message.citations[0].start_time == 10.0
    assert res.message.citations[0].end_time == 25.0
    assert res.message.citations[0].speaker == "Alex"

    # Verify LLM messages format had prompt injection defense boundaries
    call_args = mock_llm_provider.generate_structured.call_args[1]
    messages = call_args["messages"]
    assert "<UNTRUSTED_TRANSCRIPT>" in messages[1]["content"]
    assert "</UNTRUSTED_TRANSCRIPT>" in messages[1]["content"]


@pytest.mark.asyncio
async def test_chat_service_handles_insufficient_evidence_safely() -> None:
    meeting_id = uuid.uuid4()
    user_id = uuid.uuid4()
    seg_id = uuid.uuid4()

    mock_meeting = Meeting(
        id=meeting_id,
        user_id=user_id,
        title="Architecture Sync",
        status=MeetingStatus.ACTIVE,
    )
    mock_transcript = Transcript(
        id=uuid.uuid4(),
        meeting_id=meeting_id,
        user_id=user_id,
        provider="groq",
    )
    mock_segments = [
        TranscriptSegment(
            id=seg_id,
            transcript_id=mock_transcript.id,
            meeting_id=meeting_id,
            sequence_index=0,
            start_time=0.0,
            end_time=10.0,
            speaker_label="SPEAKER_00",
            text="We discussed frontend components and css.",
        )
    ]

    mock_meeting_repo = AsyncMock()
    mock_meeting_repo.get_by_id.return_value = mock_meeting
    mock_transcript_repo = AsyncMock()
    mock_transcript_repo.get_by_meeting_id.return_value = mock_transcript
    mock_transcript_repo.get_segments_by_transcript.return_value = mock_segments

    mock_chat_session = ChatSession(
        id=uuid.uuid4(),
        meeting_id=meeting_id,
        user_id=user_id,
        title="Test Session",
    )
    no_info_msg = ChatMessage(
        id=uuid.uuid4(),
        session_id=mock_chat_session.id,
        meeting_id=meeting_id,
        user_id=user_id,
        role=ChatRole.ASSISTANT,
        content="The meeting transcript does not contain information to answer this question.",
        citation_segment_ids=[],
    )

    mock_chat_repo = AsyncMock()
    mock_chat_repo.get_or_create_session.return_value = mock_chat_session
    mock_chat_repo.add_message.return_value = no_info_msg

    mock_llm_provider = MagicMock()
    mock_llm_provider.generate_structured.return_value = LLMResponse(
        provider="mock",
        model="gpt-oss-120b",
        content="",
        parsed_json={
            "answer": (
                "The meeting transcript does not contain information to answer this question."
            ),
            "cited_segment_ids": [],
        },
        usage=LLMUsage(prompt_tokens=50, completion_tokens=15, total_tokens=65),
    )

    service = ChatService(
        meeting_repo=mock_meeting_repo,
        transcript_repo=mock_transcript_repo,
        chat_repo=mock_chat_repo,
        llm_provider=mock_llm_provider,
        settings=Settings(),
    )

    res = await service.answer_question(
        meeting_id=meeting_id,
        user_id=user_id,
        question="What is the CEO's favorite car?",
    )

    assert "does not contain information" in res.message.content
    assert len(res.message.citations) == 0


@pytest.mark.asyncio
async def test_chat_service_enforces_tenant_isolation() -> None:
    meeting_id = uuid.uuid4()
    tenant_b = uuid.uuid4()

    mock_meeting_repo = AsyncMock()
    mock_meeting_repo.get_by_id.return_value = None

    service = ChatService(
        meeting_repo=mock_meeting_repo,
        transcript_repo=AsyncMock(),
        chat_repo=AsyncMock(),
        llm_provider=MagicMock(),
        settings=Settings(),
    )

    with pytest.raises(ValueError, match="Meeting not found"):
        await service.answer_question(
            meeting_id=meeting_id,
            user_id=tenant_b,
            question="Tell me the secrets",
        )
