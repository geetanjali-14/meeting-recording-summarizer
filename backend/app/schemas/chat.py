import uuid

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """Request payload for meeting conversational Q&A."""

    question: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="Natural language question",
    )
    session_id: uuid.UUID | None = Field(
        default=None,
        description="Optional existing chat session ID",
    )


class ChatCitation(BaseModel):
    """Citation linking answer to a specific transcript segment."""

    segment_id: uuid.UUID
    start_time: float
    end_time: float
    speaker: str | None = None
    text_snippet: str | None = None


class ChatMessageResponse(BaseModel):
    """Individual conversation message."""

    message_id: uuid.UUID
    session_id: uuid.UUID
    meeting_id: uuid.UUID
    role: str
    content: str
    citations: list[ChatCitation] = Field(default_factory=list)
    created_at: str


class ChatResponse(BaseModel):
    """Response payload for meeting conversational Q&A."""

    session_id: uuid.UUID
    message: ChatMessageResponse

