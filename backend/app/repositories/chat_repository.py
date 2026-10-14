import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import ChatMessage, ChatRole, ChatSession


class ChatRepository:
    """Repository for ChatSession and ChatMessage operations, strictly scoped by user_id."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_or_create_session(
        self,
        meeting_id: uuid.UUID,
        user_id: uuid.UUID,
        session_id: uuid.UUID | None = None,
        title: str | None = None,
    ) -> ChatSession:
        if session_id is not None:
            stmt = select(ChatSession).where(
                ChatSession.id == session_id,
                ChatSession.meeting_id == meeting_id,
                ChatSession.user_id == user_id,
            )
            result = await self.session.execute(stmt)
            existing = result.scalar_one_or_none()
            if existing is not None:
                return existing

        new_session = ChatSession(
            meeting_id=meeting_id,
            user_id=user_id,
            title=title or "Q&A Session",
        )
        self.session.add(new_session)
        await self.session.flush()
        return new_session

    async def add_message(
        self,
        session_id: uuid.UUID,
        meeting_id: uuid.UUID,
        user_id: uuid.UUID,
        role: ChatRole,
        content: str,
        citation_segment_ids: list[uuid.UUID] | None = None,
    ) -> ChatMessage:
        msg = ChatMessage(
            session_id=session_id,
            meeting_id=meeting_id,
            user_id=user_id,
            role=role,
            content=content,
            citation_segment_ids=citation_segment_ids or [],
        )
        self.session.add(msg)
        await self.session.flush()
        return msg

    async def get_messages_by_meeting(
        self,
        meeting_id: uuid.UUID,
        user_id: uuid.UUID,
        session_id: uuid.UUID | None = None,
    ) -> Sequence[ChatMessage]:
        stmt = (
            select(ChatMessage)
            .where(
                ChatMessage.meeting_id == meeting_id,
                ChatMessage.user_id == user_id,
            )
            .order_by(ChatMessage.created_at.asc())
        )
        if session_id is not None:
            stmt = stmt.where(ChatMessage.session_id == session_id)

        result = await self.session.execute(stmt)
        return result.scalars().all()
