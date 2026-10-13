import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.core.database import async_session_factory
from app.main import create_app
from app.models.meeting import Meeting, MeetingStatus
from app.models.transcript import Transcript, TranscriptSegment
from app.models.user import User
from app.providers.llm.mock_provider import MockLLMProvider
from tests.security.test_tenant_isolation import create_token


@pytest.mark.asyncio
async def test_chat_api_end_to_end_flow_and_tenant_isolation() -> None:
    # 1. Create real test users and meetings in PostgreSQL
    user_a_id = uuid.uuid4()
    user_b_id = uuid.uuid4()
    meeting_id = uuid.uuid4()
    transcript_id = uuid.uuid4()
    seg_id = uuid.uuid4()

    async with async_session_factory() as session:
        user_a = User(id=user_a_id, email=f"user_a_{user_a_id.hex[:6]}@example.com")
        user_b = User(id=user_b_id, email=f"user_b_{user_b_id.hex[:6]}@example.com")
        session.add_all([user_a, user_b])
        await session.flush()

        meeting = Meeting(
            id=meeting_id,
            user_id=user_a_id,
            title="Q4 Database Strategy",
            status=MeetingStatus.ACTIVE,
        )
        session.add(meeting)
        await session.flush()

        transcript = Transcript(
            id=transcript_id,
            meeting_id=meeting_id,
            user_id=user_a_id,
            provider="groq_whisper_turbo",
            language="en",
            total_duration_seconds=120.0,
            segment_count=1,
            raw_transcript_text="We selected PostgreSQL from day one with psycopg.",
        )
        session.add(transcript)
        await session.flush()

        segment = TranscriptSegment(
            id=seg_id,
            transcript_id=transcript_id,
            meeting_id=meeting_id,
            sequence_index=0,
            start_time=12.5,
            end_time=24.0,
            speaker_label="SPEAKER_00",
            speaker="Alex",
            text="We selected PostgreSQL from day one with psycopg.",
        )
        session.add(segment)
        await session.commit()

    # 2. Setup mock LLM response
    app = create_app()
    test_settings = Settings(
        JWT_ISSUER="https://auth.example.com",
        JWT_AUDIENCE="authenticated",
        JWT_ALGORITHMS=["HS256"],
        JWT_SIGNING_KEY_OR_JWKS="test-secret",
        LLM_PROVIDER="mock",
    )
    app.dependency_overrides[get_settings] = lambda: test_settings

    client = TestClient(app)
    token_a = create_token(user_a_id)
    token_b = create_token(user_b_id)

    # 3. User B attempts to query User A's meeting -> 404 (Tenant Isolation)
    res_b = client.post(
        f"/api/v1/meetings/{meeting_id}/chat",
        json={"question": "What database was chosen?"},
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert res_b.status_code == 404
    assert res_b.json()["error"]["code"] == "NOT_FOUND"

    # 4. User A queries the meeting -> 200 with grounded response and citation
    from app.api.deps import get_llm_provider

    mock_llm = MockLLMProvider()
    mock_llm.set_mock_response(
        {
            "answer": "The meeting confirmed PostgreSQL from day one with psycopg.",
            "cited_segment_ids": [str(seg_id)],
        }
    )
    app.dependency_overrides[get_llm_provider] = lambda: mock_llm

    res_a = client.post(
        f"/api/v1/meetings/{meeting_id}/chat",
        json={"question": "What database was chosen?"},
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert res_a.status_code == 200
    data = res_a.json()["data"]
    assert "session_id" in data
    assert data["message"]["role"] == "ASSISTANT"
    assert "PostgreSQL" in data["message"]["content"]
    assert len(data["message"]["citations"]) == 1
    assert data["message"]["citations"][0]["segment_id"] == str(seg_id)
    assert data["message"]["citations"][0]["start_time"] == 12.5
    assert data["message"]["citations"][0]["end_time"] == 24.0

    # 5. Fetch message history for User A
    session_id = data["session_id"]
    hist_res = client.get(
        f"/api/v1/meetings/{meeting_id}/chat/messages?session_id={session_id}",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert hist_res.status_code == 200
    hist = hist_res.json()["data"]
    assert len(hist) == 2  # 1 USER, 1 ASSISTANT
    assert hist[0]["role"] == "USER"
    assert hist[0]["content"] == "What database was chosen?"
    assert hist[1]["role"] == "ASSISTANT"
    assert len(hist[1]["citations"]) == 1

