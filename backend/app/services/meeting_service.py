import logging
import uuid
from collections.abc import Sequence

from app.models.meeting import Meeting, MeetingStatus
from app.models.recording import RecordingStatus
from app.providers.storage.base import StorageProvider
from app.repositories.meeting_repository import MeetingRepository
from app.schemas.meeting import MeetingCreateRequest

logger = logging.getLogger(__name__)


class MeetingServiceError(Exception):
    """Base exception for meeting service operations."""

    def __init__(self, message: str, code: str = "INTERNAL_ERROR", status_code: int = 500) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code


class MeetingNotFoundError(MeetingServiceError):
    """Raised when meeting is not found or unowned."""

    def __init__(self, message: str = "Meeting not found") -> None:
        super().__init__(message, code="NOT_FOUND", status_code=404)


class MeetingConflictError(MeetingServiceError):
    """Raised on invalid state transition conflict."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="CONFLICT", status_code=409)


class StorageError(MeetingServiceError):
    """Raised when upstream object storage fails."""

    def __init__(self, message: str = "Object storage operation failed") -> None:
        super().__init__(message, code="STORAGE_ERROR", status_code=502)


class MeetingService:
    """Deterministic business logic layer for Meeting aggregate operations."""

    def __init__(
        self,
        meeting_repo: MeetingRepository,
        storage_provider: StorageProvider,
    ) -> None:
        self.meeting_repo = meeting_repo
        self.storage_provider = storage_provider

    async def get_meeting_details(
        self,
        meeting_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> Meeting:
        """Retrieves meeting details, strictly enforcing user tenant boundary."""
        meeting = await self.meeting_repo.get_by_id(
            meeting_id=meeting_id,
            user_id=user_id,
            include_relations=True,
        )
        if meeting is None or meeting.status == MeetingStatus.DELETING:
            raise MeetingNotFoundError()
        return meeting

    async def list_meetings(
        self,
        user_id: uuid.UUID,
        page: int = 1,
        per_page: int = 20,
    ) -> tuple[Sequence[Meeting], int]:
        """Lists meetings for authenticated user with pagination."""
        offset = (page - 1) * per_page
        items = await self.meeting_repo.list_by_user(
            user_id=user_id,
            limit=per_page,
            offset=offset,
        )
        total_count = await self.meeting_repo.count_by_user(user_id=user_id)
        return items, total_count

    async def delete_meeting(
        self,
        meeting_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> None:
        """Executes deletion lifecycle cascading across storage and database cleanly.

        1. Finds meeting and verifies ownership.
        2. Transitions meeting status to DELETING.
        3. Cleans up binary in object storage.
        4. Permanently cascades deletion in PostgreSQL.
        """
        meeting = await self.meeting_repo.get_by_id(
            meeting_id=meeting_id,
            user_id=user_id,
            include_relations=True,
        )
        if meeting is None or meeting.status in (MeetingStatus.DELETING, MeetingStatus.PURGED):
            raise MeetingNotFoundError()

        # Mark DELETING
        await self.meeting_repo.mark_deleting(meeting_id=meeting_id, user_id=user_id)

        # Storage cleanup if recording exists
        if meeting.recording is not None and meeting.recording.storage_key:
            storage_key = meeting.recording.storage_key
            try:
                self.storage_provider.delete_object(storage_key)
                meeting.recording.status = RecordingStatus.DELETED
            except Exception as exc:
                logger.error(
                    "Failed to delete object from storage during meeting deletion",
                    extra={"storage_key": storage_key, "error": str(exc)},
                )
                raise StorageError(f"Failed to delete storage object: {exc}") from exc

        # Cascade delete from database
        await self.meeting_repo.delete(meeting_id=meeting_id, user_id=user_id)

