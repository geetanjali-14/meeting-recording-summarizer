import json
import uuid
from unittest.mock import AsyncMock

import pytest

from app.models.meeting import Meeting, MeetingStatus
from app.models.meeting_analysis import ActionItem, Decision, MeetingAnalysis, Topic
from app.models.transcript import Transcript, TranscriptSegment
from app.schemas.analysis import DecisionConfidence
from app.schemas.export import ExportFormat
from app.services.export_service import ExportService


@pytest.mark.asyncio
async def test_export_service_markdown_and_json_format_correctness() -> None:
    meeting_id = uuid.uuid4()
    user_id = uuid.uuid4()
    seg_id = uuid.uuid4()

    mock_meeting = Meeting(
        id=meeting_id,
        user_id=user_id,
        title="Sprint 42 Architecture Review",
        description="Detailed review of database and celery workers",
        meeting_date="2026-10-13",
        status=MeetingStatus.ACTIVE,
    )

    mock_analysis = MeetingAnalysis(
        id=uuid.uuid4(),
        meeting_id=meeting_id,
        user_id=user_id,
        executive_summary="Team aligned on PostgreSQL and Celery late acknowledgements.",
        model="gpt-oss-120b",
        topics=[
            Topic(
                id=uuid.uuid4(),
                sequence_index=0,
                title="Database Scaling",
                summary="Connection pooling configured with psycopg.",
                start_time=10.0,
                end_time=30.0,
            )
        ],
        decisions=[
            Decision(
                id=uuid.uuid4(),
                sequence_index=0,
                decision_text="Use PostgreSQL pooling with 10 connections.",
                confidence=DecisionConfidence.EXPLICIT,
                start_time=15.0,
                end_time=25.0,
                evidence_segment_ids=[seg_id],
            )
        ],
        action_items=[
            ActionItem(
                id=uuid.uuid4(),
                sequence_index=0,
                action_text="Configure pool timeout to 30 seconds",
                owner="Charlie",
                due_date="2026-10-20",
                start_time=26.0,
                end_time=29.0,
                evidence_segment_ids=[seg_id],
            )
        ],
        risks=[],
        open_questions=[],
    )

    mock_transcript = Transcript(
        id=uuid.uuid4(),
        meeting_id=meeting_id,
        user_id=user_id,
        provider="groq_whisper_turbo",
    )
    mock_segments = [
        TranscriptSegment(
            id=seg_id,
            transcript_id=mock_transcript.id,
            meeting_id=meeting_id,
            sequence_index=0,
            start_time=10.0,
            end_time=30.0,
            speaker_label="SPEAKER_00",
            speaker="Charlie",
            text="Let's make sure pool timeout is 30 seconds.",
        )
    ]

    mock_meeting_repo = AsyncMock()
    mock_meeting_repo.get_by_id.return_value = mock_meeting
    mock_analysis_repo = AsyncMock()
    mock_analysis_repo.get_by_meeting_id.return_value = mock_analysis
    mock_transcript_repo = AsyncMock()
    mock_transcript_repo.get_by_meeting_id.return_value = mock_transcript
    mock_transcript_repo.get_segments_by_transcript.return_value = mock_segments

    service = ExportService(
        meeting_repo=mock_meeting_repo,
        analysis_repo=mock_analysis_repo,
        transcript_repo=mock_transcript_repo,
    )

    # 1. Test Markdown export
    md_res = await service.export_meeting(meeting_id, user_id, ExportFormat.MARKDOWN)
    assert md_res.format == "markdown"
    assert md_res.filename == "Sprint_42_Architecture_Review_analysis.md"
    assert md_res.content_type == "text/markdown"
    assert "# Sprint 42 Architecture Review" in md_res.content
    assert "## Summary" in md_res.content
    assert "PostgreSQL and Celery late acknowledgements" in md_res.content
    assert "## Transcript (1 segments)" in md_res.content
    assert (
        "[0:10 - 0:30] **Charlie:** Let's make sure pool timeout is 30 seconds." in md_res.content
    )

    # 2. Test JSON export
    json_res = await service.export_meeting(meeting_id, user_id, ExportFormat.JSON)
    assert json_res.format == "json"
    assert json_res.filename == "Sprint_42_Architecture_Review_analysis.json"
    assert json_res.content_type == "application/json"
    parsed = json.loads(json_res.content)
    assert parsed["meeting"]["title"] == "Sprint 42 Architecture Review"
    assert (
        parsed["analysis"]["executive_summary"]
        == "Team aligned on PostgreSQL and Celery late acknowledgements."
    )
    assert len(parsed["analysis"]["decisions"]) == 1
    assert (
        parsed["analysis"]["decisions"][0]["decision_text"]
        == "Use PostgreSQL pooling with 10 connections."
    )
    assert len(parsed["analysis"]["action_items"]) == 1
    assert parsed["analysis"]["action_items"][0]["owner"] == "Charlie"


@pytest.mark.asyncio
async def test_export_service_handles_missing_analysis_gracefully() -> None:
    meeting_id = uuid.uuid4()
    user_id = uuid.uuid4()

    mock_meeting = Meeting(
        id=meeting_id,
        user_id=user_id,
        title="Unprocessed Meeting",
        meeting_date="2026-10-13",
        status=MeetingStatus.CREATED,
    )

    mock_meeting_repo = AsyncMock()
    mock_meeting_repo.get_by_id.return_value = mock_meeting
    mock_analysis_repo = AsyncMock()
    mock_analysis_repo.get_by_meeting_id.return_value = None
    mock_transcript_repo = AsyncMock()
    mock_transcript_repo.get_by_meeting_id.return_value = None

    service = ExportService(
        meeting_repo=mock_meeting_repo,
        analysis_repo=mock_analysis_repo,
        transcript_repo=mock_transcript_repo,
    )

    md_res = await service.export_meeting(meeting_id, user_id, ExportFormat.MARKDOWN)
    assert "_No summary available for this meeting._" in md_res.content
    assert md_res.metadata["has_analysis"] is False


@pytest.mark.asyncio
async def test_export_service_enforces_tenant_isolation() -> None:
    meeting_id = uuid.uuid4()
    tenant_b = uuid.uuid4()

    mock_meeting_repo = AsyncMock()
    mock_meeting_repo.get_by_id.return_value = None  # Tenant B doesn't own meeting

    service = ExportService(
        meeting_repo=mock_meeting_repo,
        analysis_repo=AsyncMock(),
        transcript_repo=AsyncMock(),
    )

    with pytest.raises(ValueError, match="Meeting not found"):
        await service.export_meeting(meeting_id, tenant_b, ExportFormat.MARKDOWN)
