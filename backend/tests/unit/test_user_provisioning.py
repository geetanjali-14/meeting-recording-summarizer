import datetime
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.config import Settings
from app.models.meeting import Meeting, MeetingStatus
from app.models.recording import Recording, RecordingStatus
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.schemas.meeting import MeetingCreateRequest
from app.services.upload_service import UploadService


@pytest.fixture
def mock_settings() -> Settings:
    return Settings(
        JWT_SIGNING_KEY_OR_JWKS="https://auth.example.com/.well-known/jwks.json",
        UPLOAD_TOKEN_SECRET="test-upload-token-secret-at-least-32-chars",
    )


@pytest.mark.asyncio
async def test_first_time_user_provisioning_on_upload(mock_settings: Settings) -> None:
    """When a newly authenticated Supabase user creates their first meeting,

    UploadService automatically provisions a local User row before inserting the Meeting.
    """
    user_id = uuid.uuid4()
    user_email = "newuser@example.com"

    mock_meeting_repo = MagicMock()
    mock_meeting = Meeting(
        id=uuid.uuid4(),
        user_id=user_id,
        title="First Meeting",
        status=MeetingStatus.CREATED,
    )
    mock_meeting_repo.create = AsyncMock(return_value=mock_meeting)

    mock_recording_repo = MagicMock()
    mock_recording = Recording(
        id=uuid.uuid4(),
        meeting_id=mock_meeting.id,
        user_id=user_id,
        storage_key="test-key",
        original_filename="audio.mp3",
        content_type="audio/mpeg",
        file_size_bytes=1000,
        status=RecordingStatus.PRESIGNED,
    )
    mock_recording_repo.create = AsyncMock(return_value=mock_recording)

    mock_storage = MagicMock()
    mock_storage.generate_presigned_upload_url = MagicMock(
        return_value="https://storage.example.com/put"
    )

    # Mock user repository
    mock_user_repo = MagicMock(spec=UserRepository)
    mock_user_repo.get_by_id = AsyncMock(return_value=None)  # Not yet in local DB
    provisioned_user = User(id=user_id, email=user_email)
    mock_user_repo.upsert_user = AsyncMock(return_value=provisioned_user)

    upload_service = UploadService(
        meeting_repo=mock_meeting_repo,
        recording_repo=mock_recording_repo,
        job_repo=MagicMock(),
        storage_provider=mock_storage,
        settings=mock_settings,
        user_repo=mock_user_repo,
    )

    request = MeetingCreateRequest(
        title="First Meeting",
        meeting_date=datetime.date.today(),
        filename="audio.mp3",
        content_type="audio/mpeg",
        file_size_bytes=1000,
    )

    res = await upload_service.initiate_meeting_upload(
        user_id=user_id,
        request=request,
        user_email=user_email,
    )
    meeting, recording, upload_url, upload_token, expires_in = res

    # Verifications
    mock_user_repo.get_by_id.assert_awaited_once_with(user_id)
    mock_user_repo.upsert_user.assert_awaited_once_with(user_id=user_id, email=user_email)
    mock_meeting_repo.create.assert_awaited_once()
    assert meeting.id == mock_meeting.id


@pytest.mark.asyncio
async def test_existing_user_no_redundant_provisioning(mock_settings: Settings) -> None:
    """When an existing user creates a meeting, redundant user upsert is skipped."""
    user_id = uuid.uuid4()
    existing_user = User(id=user_id, email="existing@example.com")

    mock_meeting_repo = MagicMock()
    mock_meeting = Meeting(
        id=uuid.uuid4(),
        user_id=user_id,
        title="Second Meeting",
        status=MeetingStatus.CREATED,
    )
    mock_meeting_repo.create = AsyncMock(return_value=mock_meeting)

    mock_recording_repo = MagicMock()
    mock_recording = Recording(
        id=uuid.uuid4(),
        meeting_id=mock_meeting.id,
        user_id=user_id,
        storage_key="test-key",
        original_filename="audio.mp3",
        content_type="audio/mpeg",
        file_size_bytes=1000,
        status=RecordingStatus.PRESIGNED,
    )
    mock_recording_repo.create = AsyncMock(return_value=mock_recording)

    mock_storage = MagicMock()
    mock_storage.generate_presigned_upload_url = MagicMock(
        return_value="https://storage.example.com/put"
    )

    mock_user_repo = MagicMock(spec=UserRepository)
    mock_user_repo.get_by_id = AsyncMock(return_value=existing_user)
    mock_user_repo.upsert_user = AsyncMock()

    upload_service = UploadService(
        meeting_repo=mock_meeting_repo,
        recording_repo=mock_recording_repo,
        job_repo=MagicMock(),
        storage_provider=mock_storage,
        settings=mock_settings,
        user_repo=mock_user_repo,
    )

    request = MeetingCreateRequest(
        title="Second Meeting",
        meeting_date=datetime.date.today(),
        filename="audio.mp3",
        content_type="audio/mpeg",
        file_size_bytes=1000,
    )

    await upload_service.initiate_meeting_upload(
        user_id=user_id,
        request=request,
        user_email="existing@example.com",
    )

    mock_user_repo.get_by_id.assert_awaited_once_with(user_id)
    mock_user_repo.upsert_user.assert_not_awaited()


def test_upload_token_signing_isolated_from_jwks_url(mock_settings: Settings) -> None:
    """Verifies that UploadService signs and validates tokens using UPLOAD_TOKEN_SECRET

    even when JWT_SIGNING_KEY_OR_JWKS is an HTTPS URL.
    """
    upload_service = UploadService(
        meeting_repo=MagicMock(),
        recording_repo=MagicMock(),
        job_repo=MagicMock(),
        storage_provider=MagicMock(),
        settings=mock_settings,
    )

    mid = uuid.uuid4()
    rid = uuid.uuid4()
    uid = uuid.uuid4()
    exp = int(datetime.datetime.now(datetime.UTC).timestamp()) + 900

    token = upload_service.generate_upload_token(
        meeting_id=mid,
        recording_id=rid,
        user_id=uid,
        expires_at=exp,
    )

    assert token.startswith("up_tok_")
    assert upload_service.verify_upload_token(token, mid, rid, uid) is True

    # Tampered token fails
    tampered_token = token[:-4] + "abcd"
    assert upload_service.verify_upload_token(tampered_token, mid, rid, uid) is False
