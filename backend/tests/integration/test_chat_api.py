import uuid
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.api.deps import (
    get_chat_service,
)
from app.core.config import Settings, get_settings
from app.main import create_app
from app.models.chat import ChatRole
from app.schemas.chat import ChatCitation, ChatMessageResponse, ChatResponse
from app.services.chat_service import ChatService
from tests.security.test_tenant_isolation import create_token


def test_chat_api_end_to_end_flow_and_tenant_isolation() -> None:
    user_a_id = uuid.uuid4()
    user_b_id = uuid.uuid4()
    meeting_id = uuid.uuid4()
    seg_id = uuid.uuid4()
    session_id = uuid.uuid4()

    app = create_app()
    test_settings = Settings(
        JWT_ISSUER="https://auth.example.com",
        JWT_AUDIENCE="authenticated",
        JWT_ALGORITHMS=["HS256"],
        JWT_SIGNING_KEY_OR_JWKS="test-secret",
        LLM_PROVIDER="mock",
    )
    app.dependency_overrides[get_settings] = lambda: test_settings

    # Mock chat service
    mock_chat_service = AsyncMock(spec=ChatService)

    async def mock_answer_question(*args, **kwargs):
        user_id_arg = kwargs.get("user_id")
        if user_id_arg != user_a_id:
            raise ValueError("Meeting not found")
        return ChatResponse(
            session_id=session_id,
            message=ChatMessageResponse(
                message_id=uuid.uuid4(),
                session_id=session_id,
                meeting_id=meeting_id,
                role=ChatRole.ASSISTANT.value,
                content="The meeting confirmed PostgreSQL from day one with psycopg.",
                citations=[
                    ChatCitation(
                        segment_id=seg_id,
                        start_time=12.5,
                        end_time=24.0,
                        speaker="Alex",
                        text_snippet="We selected PostgreSQL from day one with psycopg.",
                    )
                ],
                created_at="2026-10-14T11:00:00Z",
            ),
        )

    async def mock_get_messages(*args, **kwargs):
        user_id_arg = kwargs.get("user_id")
        if user_id_arg != user_a_id:
            raise ValueError("Meeting not found")
        return [
            ChatMessageResponse(
                message_id=uuid.uuid4(),
                session_id=session_id,
                meeting_id=meeting_id,
                role=ChatRole.USER.value,
                content="What database was chosen?",
                citations=[],
                created_at="2026-10-14T10:59:00Z",
            ),
            ChatMessageResponse(
                message_id=uuid.uuid4(),
                session_id=session_id,
                meeting_id=meeting_id,
                role=ChatRole.ASSISTANT.value,
                content="The meeting confirmed PostgreSQL from day one with psycopg.",
                citations=[
                    ChatCitation(
                        segment_id=seg_id,
                        start_time=12.5,
                        end_time=24.0,
                        speaker="Alex",
                        text_snippet="We selected PostgreSQL from day one with psycopg.",
                    )
                ],
                created_at="2026-10-14T11:00:00Z",
            ),
        ]

    mock_chat_service.answer_question.side_effect = mock_answer_question
    mock_chat_service.get_messages.side_effect = mock_get_messages

    app.dependency_overrides[get_chat_service] = lambda: mock_chat_service

    client = TestClient(app)
    token_a = create_token(user_a_id)
    token_b = create_token(user_b_id)

    # 1. User B attempts to query User A's meeting -> 404 (Tenant Isolation)
    res_b = client.post(
        f"/api/v1/meetings/{meeting_id}/chat",
        json={"question": "What database was chosen?"},
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert res_b.status_code == 404
    assert res_b.json()["error"]["code"] == "NOT_FOUND"

    # 2. User A queries the meeting -> 200 with grounded response and citation
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

    # 3. Fetch message history for User A
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
