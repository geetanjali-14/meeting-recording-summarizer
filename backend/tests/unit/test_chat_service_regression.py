import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.config import Settings
from app.models.chat import ChatMessage, ChatRole, ChatSession
from app.models.meeting import Meeting, MeetingStatus
from app.models.transcript import Transcript, TranscriptSegment
from app.providers.llm.base import LLMProviderError, LLMResponse, LLMUsage
from app.services.chat_service import SYSTEM_PROMPT, ChatService


@pytest.fixture
def base_meeting_data():
    meeting_id = uuid.uuid4()
    user_id = uuid.uuid4()
    transcript_id = uuid.uuid4()

    meeting = Meeting(
        id=meeting_id,
        user_id=user_id,
        title="Weekly Operations & OD Sync",
        status=MeetingStatus.ACTIVE,
    )
    transcript = Transcript(
        id=transcript_id,
        meeting_id=meeting_id,
        user_id=user_id,
        provider="groq",
    )

    s1_id = uuid.uuid4()
    s2_id = uuid.uuid4()
    s3_id = uuid.uuid4()
    s4_id = uuid.uuid4()
    s5_id = uuid.uuid4()

    segments = [
        TranscriptSegment(
            id=s1_id,
            transcript_id=transcript_id,
            meeting_id=meeting_id,
            sequence_index=0,
            start_time=0.0,
            end_time=15.0,
            speaker="Alice",
            text="Welcome everyone. Today we are reviewing the OD Operating Plan and scheduling workshops.",
        ),
        TranscriptSegment(
            id=s2_id,
            transcript_id=transcript_id,
            meeting_id=meeting_id,
            sequence_index=1,
            start_time=16.0,
            end_time=30.0,
            speaker="Bob",
            text="We could maybe do a 5k fun run for charity, but that's just an initial idea to think about.",
        ),
        TranscriptSegment(
            id=s3_id,
            transcript_id=transcript_id,
            meeting_id=meeting_id,
            sequence_index=2,
            start_time=31.0,
            end_time=50.0,
            speaker="Alice",
            text="It is confirmed and decided: the OD website goes live next month on November 15th.",
        ),
        TranscriptSegment(
            id=s4_id,
            transcript_id=transcript_id,
            meeting_id=meeting_id,
            sequence_index=3,
            start_time=51.0,
            end_time=70.0,
            speaker="Charlie",
            text="Morgan, please circulate the finalized action list by 5pm today.",
        ),
        TranscriptSegment(
            id=s5_id,
            transcript_id=transcript_id,
            meeting_id=meeting_id,
            sequence_index=4,
            start_time=71.0,
            end_time=85.0,
            speaker="Morgan",
            text="I will circulate the action list by the end of the day.",
        ),
    ]

    return {
        "meeting": meeting,
        "transcript": transcript,
        "segments": segments,
        "meeting_id": meeting_id,
        "user_id": user_id,
    }


def create_chat_service(
    base_data,
    llm_provider,
    settings=None,
):
    mock_meeting_repo = AsyncMock()
    mock_meeting_repo.get_by_id.return_value = base_data["meeting"]

    mock_transcript_repo = AsyncMock()
    mock_transcript_repo.get_by_meeting_id.return_value = base_data["transcript"]
    mock_transcript_repo.get_segments_by_transcript.return_value = base_data["segments"]

    mock_chat_session = ChatSession(
        id=uuid.uuid4(),
        meeting_id=base_data["meeting_id"],
        user_id=base_data["user_id"],
        title="Test Chat",
    )
    mock_chat_repo = AsyncMock()
    mock_chat_repo.get_or_create_session.return_value = mock_chat_session

    async def mock_add_message(**kwargs):
        return ChatMessage(
            id=uuid.uuid4(),
            session_id=kwargs["session_id"],
            meeting_id=kwargs["meeting_id"],
            user_id=kwargs["user_id"],
            role=kwargs["role"],
            content=kwargs["content"],
            citation_segment_ids=kwargs.get("citation_segment_ids", []),
        )

    mock_chat_repo.add_message.side_effect = mock_add_message

    return ChatService(
        meeting_repo=mock_meeting_repo,
        transcript_repo=mock_transcript_repo,
        chat_repo=mock_chat_repo,
        llm_provider=llm_provider,
        settings=settings or Settings(),
    )


@pytest.mark.asyncio
async def test_regression_1_meeting_overview_question(base_meeting_data) -> None:
    """1. Basic 'What was this meeting about?' receives an accurate overview."""
    s1_id = base_meeting_data["segments"][0].id
    mock_llm = MagicMock()
    mock_llm.generate_structured.return_value = LLMResponse(
        provider="mock",
        model="gpt-oss-120b",
        content="",
        parsed_json={
            "answer": "The meeting was about reviewing the OD Operating Plan and scheduling workshops.",
            "cited_segment_ids": [str(s1_id)],
        },
    )

    service = create_chat_service(base_meeting_data, mock_llm)
    res = await service.answer_question(
        meeting_id=base_meeting_data["meeting_id"],
        user_id=base_meeting_data["user_id"],
        question="What was this meeting about?",
    )

    assert "OD Operating Plan" in res.message.content
    assert len(res.message.citations) == 1
    assert res.message.citations[0].segment_id == s1_id


@pytest.mark.asyncio
async def test_regression_2_meeting_objective_without_literal_keyword(base_meeting_data) -> None:
    """2. Question about meeting's objective succeeds even when nobody literally labels it 'objective'."""
    s1_id = base_meeting_data["segments"][0].id
    mock_llm = MagicMock()
    mock_llm.generate_structured.return_value = LLMResponse(
        provider="mock",
        model="gpt-oss-120b",
        content="",
        parsed_json={
            "answer": "The main objective was to review the OD Operating Plan and plan workshop sessions.",
            "cited_segment_ids": [str(s1_id)],
        },
    )

    service = create_chat_service(base_meeting_data, mock_llm)
    res = await service.answer_question(
        meeting_id=base_meeting_data["meeting_id"],
        user_id=base_meeting_data["user_id"],
        question="What was the main objective of the meeting?",
    )

    assert "review the OD Operating Plan" in res.message.content
    assert "does not contain information" not in res.message.content


@pytest.mark.asyncio
async def test_regression_3_decisions_distinguished_from_proposals(base_meeting_data) -> None:
    """3. Decisions are extracted without confusing proposals (e.g. 5k fun run) with confirmed decisions."""
    s3_id = base_meeting_data["segments"][2].id
    mock_llm = MagicMock()
    mock_llm.generate_structured.return_value = LLMResponse(
        provider="mock",
        model="gpt-oss-120b",
        content="",
        parsed_json={
            "answer": "The confirmed decision was that the OD website will go live next month on November 15th. A charity fun run was only proposed as an idea.",
            "cited_segment_ids": [str(s3_id)],
        },
    )

    service = create_chat_service(base_meeting_data, mock_llm)
    res = await service.answer_question(
        meeting_id=base_meeting_data["meeting_id"],
        user_id=base_meeting_data["user_id"],
        question="What was decided in the meeting?",
    )

    assert "OD website will go live" in res.message.content
    assert res.message.citations[0].segment_id == s3_id


@pytest.mark.asyncio
async def test_regression_4_action_items_assigned_person_and_deadline(base_meeting_data) -> None:
    """4. Action items preserve assigned people and explicitly stated deadlines."""
    s4_id = base_meeting_data["segments"][3].id
    s5_id = base_meeting_data["segments"][4].id
    mock_llm = MagicMock()
    mock_llm.generate_structured.return_value = LLMResponse(
        provider="mock",
        model="gpt-oss-120b",
        content="",
        parsed_json={
            "answer": "Morgan was assigned to circulate the finalized action list by 5pm today (the end of the day).",
            "cited_segment_ids": [str(s4_id), str(s5_id)],
        },
    )

    service = create_chat_service(base_meeting_data, mock_llm)
    res = await service.answer_question(
        meeting_id=base_meeting_data["meeting_id"],
        user_id=base_meeting_data["user_id"],
        question="What action items were assigned, and to whom?",
    )

    assert "Morgan" in res.message.content
    assert "end of the day" in res.message.content or "5pm" in res.message.content
    assert len(res.message.citations) == 2


@pytest.mark.asyncio
async def test_regression_5_unsupported_factual_question_returns_grounded_uncertainty(base_meeting_data) -> None:
    """5. Genuinely unsupported factual question returns grounded uncertainty response."""
    mock_llm = MagicMock()
    mock_llm.generate_structured.return_value = LLMResponse(
        provider="mock",
        model="gpt-oss-120b",
        content="",
        parsed_json={
            "answer": "The meeting transcript does not contain information to answer this question.",
            "cited_segment_ids": [],
        },
    )

    service = create_chat_service(base_meeting_data, mock_llm)
    res = await service.answer_question(
        meeting_id=base_meeting_data["meeting_id"],
        user_id=base_meeting_data["user_id"],
        question="What is the CEO's favorite car brand?",
    )

    assert "The meeting transcript does not contain information to answer this question." in res.message.content
    assert len(res.message.citations) == 0


@pytest.mark.asyncio
async def test_regression_6_partially_answerable_question(base_meeting_data) -> None:
    """6. Partially answerable question receives partial answer rather than blanket refusal."""
    s3_id = base_meeting_data["segments"][2].id
    mock_llm = MagicMock()
    mock_llm.generate_structured.return_value = LLMResponse(
        provider="mock",
        model="gpt-oss-120b",
        content="",
        parsed_json={
            "answer": "The OD website goes live on November 15th, but the transcript does not specify who is hosting the website infrastructure.",
            "cited_segment_ids": [str(s3_id)],
        },
    )

    service = create_chat_service(base_meeting_data, mock_llm)
    res = await service.answer_question(
        meeting_id=base_meeting_data["meeting_id"],
        user_id=base_meeting_data["user_id"],
        question="When is the OD website going live, and which cloud hosting provider is being used?",
    )

    assert "November 15th" in res.message.content
    assert "does not specify" in res.message.content or "not" in res.message.content
    assert len(res.message.citations) == 1


@pytest.mark.asyncio
async def test_regression_7_evidence_spread_across_multiple_segments(base_meeting_data) -> None:
    """7. Relevant evidence spread across multiple transcript segments is synthesized correctly."""
    s4_id = base_meeting_data["segments"][3].id
    s5_id = base_meeting_data["segments"][4].id
    mock_llm = MagicMock()
    mock_llm.generate_structured.return_value = LLMResponse(
        provider="mock",
        model="gpt-oss-120b",
        content="",
        parsed_json={
            "answer": "Charlie requested the action list to be circulated by 5pm today, and Morgan agreed to complete it by the end of the day.",
            "cited_segment_ids": [str(s4_id), str(s5_id)],
        },
    )

    service = create_chat_service(base_meeting_data, mock_llm)
    res = await service.answer_question(
        meeting_id=base_meeting_data["meeting_id"],
        user_id=base_meeting_data["user_id"],
        question="Who agreed to circulate the action list and when?",
    )

    assert "Morgan" in res.message.content
    assert len(res.message.citations) == 2


@pytest.mark.asyncio
async def test_regression_8_long_transcript_budgeting_preserves_context(base_meeting_data) -> None:
    """8. Long transcripts do not cause relevant context to be silently lost."""
    many_segments = []
    meeting_id = base_meeting_data["meeting_id"]
    t_id = base_meeting_data["transcript"].id

    for i in range(120):
        many_segments.append(
            TranscriptSegment(
                id=uuid.uuid4(),
                transcript_id=t_id,
                meeting_id=meeting_id,
                sequence_index=i,
                start_time=float(i * 10),
                end_time=float(i * 10 + 9),
                speaker=f"Speaker_{i % 3}",
                text=f"This is routine discussion chunk {i} about various project items.",
            )
        )

    # Insert target question content in middle
    target_id = uuid.uuid4()
    many_segments[60] = TranscriptSegment(
        id=target_id,
        transcript_id=t_id,
        meeting_id=meeting_id,
        sequence_index=60,
        start_time=600.0,
        end_time=610.0,
        speaker="Director",
        text="Crucial milestone: All database migrations must freeze on December 1st.",
    )

    data = {
        "meeting": base_meeting_data["meeting"],
        "transcript": base_meeting_data["transcript"],
        "segments": many_segments,
        "meeting_id": meeting_id,
        "user_id": base_meeting_data["user_id"],
    }

    mock_llm = MagicMock()
    mock_llm.generate_structured.return_value = LLMResponse(
        provider="mock",
        model="gpt-oss-120b",
        content="",
        parsed_json={
            "answer": "All database migrations must freeze on December 1st.",
            "cited_segment_ids": [str(target_id)],
        },
    )

    service = create_chat_service(data, mock_llm)
    res = await service.answer_question(
        meeting_id=meeting_id,
        user_id=data["user_id"],
        question="When is the database migrations freeze date?",
    )

    assert "December 1st" in res.message.content
    assert res.message.citations[0].segment_id == target_id

    # Verify that the prompt sent to LLM included segment 60 and structural boundaries
    sent_prompt = mock_llm.generate_structured.call_args[1]["messages"][1]["content"]
    assert str(target_id) in sent_prompt
    assert "migrations must freeze" in sent_prompt


@pytest.mark.asyncio
async def test_regression_9_429_transient_retry_succeeds(base_meeting_data) -> None:
    """9. A 429 response followed by success triggers bounded retries and returns the answer."""
    s1_id = base_meeting_data["segments"][0].id
    mock_llm = MagicMock()

    call_count = 0

    def fake_generate(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise LLMProviderError(
                "Rate limit reached on TPM",
                is_retryable=True,
                status_code=429,
                retry_after=0.05,
            )
        return LLMResponse(
            provider="mock",
            model="gpt-oss-120b",
            content="",
            parsed_json={
                "answer": "The meeting was about reviewing the OD Operating Plan.",
                "cited_segment_ids": [str(s1_id)],
            },
        )

    mock_llm.generate_structured.side_effect = fake_generate

    service = create_chat_service(base_meeting_data, mock_llm)
    res = await service.answer_question(
        meeting_id=base_meeting_data["meeting_id"],
        user_id=base_meeting_data["user_id"],
        question="What was this meeting about?",
    )

    assert call_count == 2
    assert "OD Operating Plan" in res.message.content


@pytest.mark.asyncio
async def test_regression_10_exhausted_429_returns_clear_temporary_error(base_meeting_data) -> None:
    """10. Repeated 429 responses exhaust retry budget and produce a clear temporary error message."""
    mock_llm = MagicMock()
    mock_llm.generate_structured.side_effect = LLMProviderError(
        "Rate limit reached",
        is_retryable=True,
        status_code=429,
        retry_after=0.01,
    )

    settings = Settings(LLM_MAX_RETRIES=1)
    service = create_chat_service(base_meeting_data, mock_llm, settings=settings)
    res = await service.answer_question(
        meeting_id=base_meeting_data["meeting_id"],
        user_id=base_meeting_data["user_id"],
        question="What was decided?",
    )

    assert "experiencing high demand" in res.message.content.lower()
    assert len(res.message.citations) == 0


@pytest.mark.asyncio
async def test_regression_11_permanent_error_not_retried(base_meeting_data) -> None:
    """11. Permanent provider errors (e.g. 401/400) are not repeatedly retried."""
    mock_llm = MagicMock()
    mock_llm.generate_structured.side_effect = LLMProviderError(
        "Invalid API Key",
        is_retryable=False,
        status_code=401,
    )

    service = create_chat_service(base_meeting_data, mock_llm)
    res = await service.answer_question(
        meeting_id=base_meeting_data["meeting_id"],
        user_id=base_meeting_data["user_id"],
        question="What was decided?",
    )

    # Should only attempt once because is_retryable=False
    assert mock_llm.generate_structured.call_count == 1
    assert "unable to answer this question at this time due to an error" in res.message.content


@pytest.mark.asyncio
async def test_regression_12_malformed_model_output_safe_handling(base_meeting_data) -> None:
    """12. Malformed model output (empty dict / missing fields) is handled safely."""
    mock_llm = MagicMock()
    mock_llm.generate_structured.return_value = LLMResponse(
        provider="mock",
        model="gpt-oss-120b",
        content="not valid",
        parsed_json={},  # Missing answer key
    )

    service = create_chat_service(base_meeting_data, mock_llm)
    res = await service.answer_question(
        meeting_id=base_meeting_data["meeting_id"],
        user_id=base_meeting_data["user_id"],
        question="What was decided?",
    )

    assert "does not contain information" in res.message.content


@pytest.mark.asyncio
async def test_regression_13_transcript_retrieval_failure_not_misreported_as_missing_info(base_meeting_data) -> None:
    """13. Transcript retrieval failure raises appropriate error and is not misreported as 'no info'."""
    mock_meeting_repo = AsyncMock()
    mock_meeting_repo.get_by_id.return_value = base_meeting_data["meeting"]

    mock_transcript_repo = AsyncMock()
    mock_transcript_repo.get_by_meeting_id.return_value = None  # No transcript record

    service = ChatService(
        meeting_repo=mock_meeting_repo,
        transcript_repo=mock_transcript_repo,
        chat_repo=AsyncMock(),
        llm_provider=MagicMock(),
        settings=Settings(),
    )

    with pytest.raises(ValueError, match="Transcript not found"):
        await service.answer_question(
            meeting_id=base_meeting_data["meeting_id"],
            user_id=base_meeting_data["user_id"],
            question="What was this meeting about?",
        )


@pytest.mark.asyncio
async def test_regression_14_tenant_isolation_unauthorized_user(base_meeting_data) -> None:
    """14. Users cannot query another tenant's meeting or transcript."""
    unauthorized_tenant = uuid.uuid4()
    mock_meeting_repo = AsyncMock()
    mock_meeting_repo.get_by_id.return_value = None  # Filtered out by user_id

    service = ChatService(
        meeting_repo=mock_meeting_repo,
        transcript_repo=AsyncMock(),
        chat_repo=AsyncMock(),
        llm_provider=MagicMock(),
        settings=Settings(),
    )

    with pytest.raises(ValueError, match="Meeting not found"):
        await service.answer_question(
            meeting_id=base_meeting_data["meeting_id"],
            user_id=unauthorized_tenant,
            question="Tell me the meeting secrets",
        )

