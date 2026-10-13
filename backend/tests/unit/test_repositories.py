import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.meeting import Meeting, MeetingStatus
from app.repositories.meeting_repository import MeetingRepository


@pytest.mark.asyncio
async def test_meeting_repository_create_and_get() -> None:
    session = AsyncMock()
    session.add = MagicMock()
    repo = MeetingRepository(session)

    user_a_id = uuid.uuid4()
    user_b_id = uuid.uuid4()
    meeting_id = uuid.uuid4()

    # Test create
    meeting = await repo.create(
        user_id=user_a_id,
        title="Weekly Sync",
        description="Weekly product sync",
    )
    assert meeting.user_id == user_a_id
    assert meeting.title == "Weekly Sync"
    session.add.assert_called_once_with(meeting)
    session.flush.assert_awaited_once()

    # Test get_by_id tenant scoping: returns None when user_b tries to query User A's meeting
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    session.execute.return_value = mock_result

    fetched_unowned = await repo.get_by_id(meeting_id=meeting_id, user_id=user_b_id)
    assert fetched_unowned is None

    # Test get_by_id owner: returns meeting when User A queries
    owned_meeting = Meeting(
        id=meeting_id, user_id=user_a_id, title="Weekly Sync", status=MeetingStatus.CREATED
    )
    mock_result.scalar_one_or_none.return_value = owned_meeting

    fetched_owned = await repo.get_by_id(meeting_id=meeting_id, user_id=user_a_id)
    assert fetched_owned is not None
    assert fetched_owned.id == meeting_id
    assert fetched_owned.user_id == user_a_id
