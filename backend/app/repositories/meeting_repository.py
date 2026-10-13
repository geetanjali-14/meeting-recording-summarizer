import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

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
        meeting_date: date | None = None,
    ) -> Meeting:
        meeting = Meeting(
            user_id=user_id,
            title=title,
            description=description,
            status=MeetingStatus.CREATED,
        )
        if meeting_date is not None:
            meeting.meeting_date = meeting_date
        self.session.add(meeting)
        await self.session.flush()
        return meeting

    async def get_by_id(
        self,
        meeting_id: uuid.UUID,
        user_id: uuid.UUID,
        include_relations: bool = False,
    ) -> Meeting | None:
        """Retrieves a meeting by ID, enforcing user_id tenant boundary."""
        stmt = select(Meeting).where(
            Meeting.id == meeting_id,
            Meeting.user_id == user_id,
            Meeting.status != MeetingStatus.PURGED,
        )
        if include_relations:
            stmt = stmt.options(
                selectinload(Meeting.recording),
                selectinload(Meeting.job),
            )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_id_system(
        self,
        meeting_id: uuid.UUID,
    ) -> Meeting | None:
        """Retrieves a meeting by ID without user scope, for worker process."""
        stmt = select(Meeting).where(Meeting.id == meeting_id)
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

    async def mark_active(
        self,
        meeting: Meeting,
    ) -> Meeting:
        meeting.status = MeetingStatus.ACTIVE
        await self.session.flush()
        return meeting

    async def count_by_user(
        self,
        user_id: uuid.UUID,
    ) -> int:
        """Counts total non-purged meetings for a user."""
        stmt = select(func.count(Meeting.id)).where(
            Meeting.user_id == user_id,
            Meeting.status != MeetingStatus.PURGED,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one() or 0

    async def mark_deleting(
        self,
        meeting_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> Meeting | None:
        """Transitions meeting to DELETING state, blocking read/write access."""
        meeting = await self.get_by_id(
            meeting_id=meeting_id, user_id=user_id, include_relations=True
        )
        if meeting is None or meeting.status in (MeetingStatus.DELETING, MeetingStatus.PURGED):
            return None
        meeting.status = MeetingStatus.DELETING
        meeting.deleted_at = datetime.now(UTC)
        await self.session.flush()
        return meeting

    async def delete(
        self,
        meeting_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> bool:
        """Permanently removes meeting row or marks PURGED after cleanup."""
        meeting = await self.get_by_id(
            meeting_id=meeting_id, user_id=user_id, include_relations=True
        )
        if meeting is None:
            return False
        await self.session.delete(meeting)
        await self.session.flush()
        return True
