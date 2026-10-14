import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user, get_db_session
from app.core.security import UserContext
from app.main import create_app
from app.models.meeting import Meeting, MeetingStatus
from app.models.processing_job import JobStage, JobStatus, ProcessingJob
from app.models.transcript import Transcript, TranscriptSegment


@pytest.fixture
def test_user_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def other_user_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def mock_user_context(test_user_id: uuid.UUID) -> UserContext:
    return UserContext(
        user_id=test_user_id,
        email="test_user@example.com",
        role="authenticated",
    )


@pytest.mark.asyncio
async def test_get_processing_status_success(mock_user_context: UserContext) -> None:
    app = create_app()
    meeting_id = uuid.uuid4()
    job_id = uuid.uuid4()

    mock_meeting = Meeting(
        id=meeting_id,
        user_id=mock_user_context.user_id,
        title="Weekly Sync",
        status=MeetingStatus.ACTIVE,
    )
    mock_job = ProcessingJob(
        id=job_id,
        meeting_id=meeting_id,
        user_id=mock_user_context.user_id,
        celery_task_id="celery-1234",
        status=JobStatus.RUNNING,
        stage=JobStage.TRANSCRIBING,
        attempt=1,
    )

    mock_session = AsyncMock()

    # MeetingRepo mock execute
    mock_result_meeting = MagicMock()
    mock_result_meeting.scalar_one_or_none.return_value = mock_meeting

    # JobRepo mock execute
    mock_result_job = MagicMock()
    mock_result_job.scalar_one_or_none.return_value = mock_job

    mock_session.execute.side_effect = [mock_result_meeting, mock_result_job]

    app.dependency_overrides[get_current_user] = lambda: mock_user_context
    app.dependency_overrides[get_db_session] = lambda: mock_session

    client = TestClient(app)
    response = client.get(f"/api/v1/meetings/{meeting_id}/status")

    assert response.status_code == 200
    data = response.json()
    assert data["data"]["meeting_id"] == str(meeting_id)
    assert data["data"]["job_id"] == str(job_id)
    assert data["data"]["status"] == "RUNNING"
    assert data["data"]["stage"] == "TRANSCRIBING"
    assert data["data"]["celery_task_id"] == "celery-1234"
    assert "meta" in data
    assert "request_id" in data["meta"]


@pytest.mark.asyncio
async def test_get_processing_status_tenant_isolation(
    mock_user_context: UserContext,
) -> None:
    app = create_app()
    unowned_meeting_id = uuid.uuid4()

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None  # Scoped by user_id returns None
    mock_session.execute.return_value = mock_result

    app.dependency_overrides[get_current_user] = lambda: mock_user_context
    app.dependency_overrides[get_db_session] = lambda: mock_session

    client = TestClient(app)
    response = client.get(f"/api/v1/meetings/{unowned_meeting_id}/status")

    assert response.status_code == 404
    data = response.json()
    assert data["error"]["code"] == "NOT_FOUND"


@pytest.mark.asyncio
async def test_database_error_handling_and_logging(
    mock_user_context: UserContext,
) -> None:
    """Verifies that database operational/programming errors return 500 without leaking stack traces or credentials."""
    app = create_app()
    meeting_id = uuid.uuid4()

    mock_session = AsyncMock()
    # Simulate psycopg ProgrammingError / prepared statement error
    mock_session.execute.side_effect = Exception("prepared statement '_pg3_7' does not exist")

    app.dependency_overrides[get_current_user] = lambda: mock_user_context
    app.dependency_overrides[get_db_session] = lambda: mock_session

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get(
        f"/api/v1/meetings/{meeting_id}/status",
        headers={"X-Request-ID": "test-req-tracing-123"},
    )

    assert response.status_code == 500
    data = response.json()
    assert "error" in data
    assert data["error"]["code"] == "INTERNAL_ERROR"
    assert data["error"]["message"] == "An unexpected internal server error occurred."
    assert data["error"]["request_id"] == "test-req-tracing-123"
    # Verify no raw exception or sql statement leaked to HTTP response
    assert "_pg3_7" not in response.text
    assert "ProgrammingError" not in response.text


@pytest.mark.asyncio
async def test_get_transcript_success(mock_user_context: UserContext) -> None:
    app = create_app()
    meeting_id = uuid.uuid4()
    transcript_id = uuid.uuid4()

    mock_meeting = Meeting(
        id=meeting_id,
        user_id=mock_user_context.user_id,
        title="Weekly Sync",
        status=MeetingStatus.ACTIVE,
    )
    mock_transcript = Transcript(
        id=transcript_id,
        meeting_id=meeting_id,
        user_id=mock_user_context.user_id,
        provider="groq_whisper_turbo",
        language="en",
        total_duration_seconds=120.0,
        segment_count=2,
    )
    seg1 = TranscriptSegment(
        id=uuid.uuid4(),
        transcript_id=transcript_id,
        meeting_id=meeting_id,
        sequence_index=0,
        start_time=0.0,
        end_time=5.0,
        speaker_label="SPEAKER_00",
        speaker="SPEAKER_00",
        text="Hello team.",
    )
    seg2 = TranscriptSegment(
        id=uuid.uuid4(),
        transcript_id=transcript_id,
        meeting_id=meeting_id,
        sequence_index=1,
        start_time=5.2,
        end_time=12.0,
        speaker_label="SPEAKER_01",
        speaker="SPEAKER_01",
        text="Let us review the deliverables.",
    )

    mock_session = AsyncMock()

    mock_result_meeting = MagicMock()
    mock_result_meeting.scalar_one_or_none.return_value = mock_meeting

    mock_result_transcript = MagicMock()
    mock_result_transcript.scalar_one_or_none.return_value = mock_transcript

    mock_result_segments = MagicMock()
    mock_result_segments.scalars.return_value.all.return_value = [seg1, seg2]

    mock_session.execute.side_effect = [
        mock_result_meeting,
        mock_result_transcript,
        mock_result_segments,
    ]

    app.dependency_overrides[get_current_user] = lambda: mock_user_context
    app.dependency_overrides[get_db_session] = lambda: mock_session

    client = TestClient(app)
    response = client.get(f"/api/v1/meetings/{meeting_id}/transcript")

    assert response.status_code == 200
    data = response.json()
    assert data["data"]["transcript_id"] == str(transcript_id)
    assert data["data"]["segment_count"] == 2
    assert len(data["data"]["segments"]) == 2
    assert data["data"]["segments"][0]["text"] == "Hello team."
    assert data["data"]["segments"][1]["speaker_label"] == "SPEAKER_01"
    assert "meta" in data


@pytest.mark.asyncio
async def test_get_transcript_unauthenticated_rejected() -> None:
    app = create_app()
    client = TestClient(app)
    meeting_id = uuid.uuid4()
    response = client.get(f"/api/v1/meetings/{meeting_id}/transcript")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_stream_processing_events_sse(mock_user_context: UserContext) -> None:
    """Verifies that the /events endpoint connects and streams SSE events."""
    app = create_app()
    meeting_id = uuid.uuid4()
    job_id = uuid.uuid4()

    mock_meeting = MagicMock()
    mock_meeting.id = meeting_id
    mock_meeting.user_id = mock_user_context.user_id

    mock_job = MagicMock()
    mock_job.id = job_id
    mock_job.meeting_id = meeting_id
    mock_job.celery_task_id = "test-task-123"
    mock_job.status = JobStatus.COMPLETED
    mock_job.stage = JobStage.COMPLETED
    mock_job.attempt = 1
    mock_job.error_code = None
    mock_job.error_message = None
    mock_job.started_at = None
    mock_job.completed_at = None

    mock_session = AsyncMock()
    mock_result_meeting = MagicMock()
    mock_result_meeting.scalar_one_or_none.return_value = mock_meeting
    mock_result_job = MagicMock()
    mock_result_job.scalar_one_or_none.return_value = mock_job

    mock_session.execute.side_effect = [
        mock_result_meeting,
        mock_result_job,
    ]

    app.dependency_overrides[get_current_user] = lambda: mock_user_context
    app.dependency_overrides[get_db_session] = lambda: mock_session

    from unittest.mock import patch
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def mock_async_session_factory():
        yield mock_session

    with patch("app.api.v1.status.async_session_factory", side_effect=mock_async_session_factory):
        client = TestClient(app)
        response = client.get(f"/api/v1/meetings/{meeting_id}/events")

    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]
    assert "event: status" in response.text
    assert "event: done" in response.text
