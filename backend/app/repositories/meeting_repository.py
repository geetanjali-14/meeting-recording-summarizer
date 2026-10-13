import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.meeting import Meeting, MeetingStatus


class MeetingRepository:
    """Repository for Meeting aggregate operations, strictly scoped by authenticated user_id."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        user_id: uuid.UUID,
        title: str,
        description: str | None = None,
    ) -> Meeting:
        meeting = Meeting(
            user_id=user_id,
            title=title,
            description=description,
            status=MeetingStatus.CREATED,
        )
        self.session.add(meeting)
        await self.session.flush()
        return meeting

    async def get_by_id(
        self,
        meeting_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> Meeting | None:
        """Retrieves a meeting by ID, enforcing user_id tenant boundary."""
        stmt = select(Meeting).where(
            Meeting.id == meeting_id,
            Meeting.user_id == user_id,
            Meeting.status != MeetingStatus.PURGED,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_user(
        self,
        user_id: uuid.UUID,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[Meeting]:
        """Lists active meetings for a user, enforcing user_id tenant boundary."""
        stmt = (
            select(Meeting)
            .where(
                Meeting.user_id == user_id,
                Meeting.status != MeetingStatus.PURGED,
            )
            .order_by(Meeting.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()
