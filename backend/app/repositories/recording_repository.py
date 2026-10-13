import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.recording import Recording, RecordingStatus


class RecordingRepository:
    """Repository for Recording operations, strictly scoped by user_id."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        meeting_id: uuid.UUID,
        user_id: uuid.UUID,
        storage_key: str,
        original_filename: str,
        content_type: str,
        file_size_bytes: int,
        status: RecordingStatus = RecordingStatus.PRESIGNED,
        recording_id: uuid.UUID | None = None,
    ) -> Recording:
        recording = Recording(
            id=recording_id or uuid.uuid4(),
            meeting_id=meeting_id,
            user_id=user_id,
            storage_key=storage_key,
            original_filename=original_filename,
            content_type=content_type,
            file_size_bytes=file_size_bytes,
            status=status,
        )
        self.session.add(recording)
        await self.session.flush()
        return recording

    async def get_by_id(
        self,
        recording_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> Recording | None:
        stmt = select(Recording).where(
            Recording.id == recording_id,
            Recording.user_id == user_id,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_meeting_id(
        self,
        meeting_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> Recording | None:
        stmt = select(Recording).where(
            Recording.meeting_id == meeting_id,
            Recording.user_id == user_id,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_meeting_id_system(
        self,
        meeting_id: uuid.UUID,
    ) -> Recording | None:
        """Fetches recording by meeting ID without user scope, for worker background task."""
        stmt = select(Recording).where(Recording.meeting_id == meeting_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def mark_uploaded(
        self,
        recording: Recording,
    ) -> Recording:
        recording.status = RecordingStatus.UPLOADED
        recording.uploaded_at = datetime.now(UTC)
        await self.session.flush()
        return recording

    async def mark_deleted(
        self,
        recording: Recording,
    ) -> Recording:
        recording.status = RecordingStatus.DELETED
        await self.session.flush()
        return recording
