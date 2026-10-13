import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.security import UserContext
from app.main import app
from app.models.meeting import Meeting
from app.models.meeting_analysis import (
    ActionItem,
    ConfidenceLevel,
    Decision,
    MeetingAnalysis,
    Topic,
)


@pytest.fixture
def auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer mock-token-test"}


@pytest.mark.asyncio
async def test_get_analysis_success(auth_headers: dict[str, str]) -> None:
    user_id = uuid.uuid4()
    meeting_id = uuid.uuid4()
    analysis_id = uuid.uuid4()
    seg_id = uuid.uuid4()

    mock_user = UserContext(
        user_id=user_id,
        email="analyst@example.com",
    )

    meeting = Meeting(
        id=meeting_id,
        user_id=user_id,
        title="Sprint Sync",
    )

    analysis = MeetingAnalysis(
        id=analysis_id,
        meeting_id=meeting_id,
        user_id=user_id,
        provider="groq",
        model="openai/gpt-oss-120b",
        title="Sprint Sync — Review",
        executive_summary="Team decided on deployment schedules.",
        prompt_tokens=150,
        completion_tokens=50,
        total_tokens=200,
        estimated_cost_usd=0.00005,
    )
    analysis.topics = [
        Topic(
            id=uuid.uuid4(),
            analysis_id=analysis_id,
            meeting_id=meeting_id,
            title="Deployments",
            summary="Schedule review.",
            sequence_index=0,
            start_time=0.0,
            end_time=10.0,
        )
    ]
    analysis.decisions = [
        Decision(
            id=uuid.uuid4(),
            analysis_id=analysis_id,
            meeting_id=meeting_id,
            decision_text="Ship on Monday.",
            confidence=ConfidenceLevel.EXPLICIT,
            sequence_index=0,
            start_time=2.0,
            end_time=5.0,
            evidence_segment_ids=[seg_id],
        )
    ]
    analysis.action_items = [
        ActionItem(
            id=uuid.uuid4(),
            analysis_id=analysis_id,
            meeting_id=meeting_id,
            action_text="Tag release.",
            owner="Alice",
            due_date=None,
            sequence_index=0,
            start_time=5.0,
            end_time=8.0,
            evidence_segment_ids=[seg_id],
        )
    ]
    analysis.risks = []
    analysis.open_questions = []

    meeting_repo_patch = "app.repositories.meeting_repository.MeetingRepository.get_by_id"
    analysis_repo_patch = (
        "app.repositories.analysis_repository.AnalysisRepository.get_by_meeting_id"
    )
    with (
        patch("app.api.deps.verify_jwt_token", AsyncMock(return_value=mock_user)),
        patch(meeting_repo_patch, AsyncMock(return_value=meeting)),
        patch(analysis_repo_patch, AsyncMock(return_value=analysis)),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(
                f"/api/v1/meetings/{meeting_id}/analysis",
                headers=auth_headers,
            )

    assert response.status_code == 200
    json_data = response.json()
    assert "data" in json_data
    data = json_data["data"]
    assert data["analysis_id"] == str(analysis_id)
    assert data["executive_summary"] == "Team decided on deployment schedules."
    assert len(data["topics"]) == 1
    assert len(data["decisions"]) == 1
    assert data["decisions"][0]["decision_text"] == "Ship on Monday."
    assert data["decisions"][0]["evidence_segment_ids"] == [str(seg_id)]
    assert len(data["action_items"]) == 1
    assert data["action_items"][0]["owner"] == "Alice"


@pytest.mark.asyncio
async def test_get_analysis_unauthenticated_rejected() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/api/v1/meetings/{uuid.uuid4()}/analysis")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_analysis_not_found(auth_headers: dict[str, str]) -> None:
    user_id = uuid.uuid4()
    mock_user = UserContext(
        user_id=user_id,
        email="analyst@example.com",
    )
    meeting_repo_patch = "app.repositories.meeting_repository.MeetingRepository.get_by_id"
    with (
        patch("app.api.deps.verify_jwt_token", AsyncMock(return_value=mock_user)),
        patch(meeting_repo_patch, AsyncMock(return_value=None)),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(
                f"/api/v1/meetings/{uuid.uuid4()}/analysis",
                headers=auth_headers,
            )
    assert response.status_code == 404
