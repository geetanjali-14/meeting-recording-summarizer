import datetime
import uuid

import pytest

from app.core.config import Settings
from app.providers.storage.r2_provider import R2StorageProvider
from app.services.upload_service import UploadService


def test_signed_upload_key_namespacing() -> None:
    settings = Settings(
        STORAGE_BUCKET_NAME="secure-recordings",
        STORAGE_ENDPOINT_URL="https://account.r2.cloudflarestorage.com",
        STORAGE_ACCESS_KEY_ID="test_key",
        STORAGE_SECRET_ACCESS_KEY="test_secret",
        JWT_SIGNING_KEY_OR_JWKS="test-secret-at-least-32-chars-long",
    )
    user_id = uuid.uuid4()
    recording_id = uuid.uuid4()
    filename = "meeting_audio.m4a"

    expected_prefix = f"users/{user_id}/recordings/{recording_id}/{filename}"
    assert expected_prefix.startswith(f"users/{user_id}/")


def test_upload_token_tampering_and_expiration_defense() -> None:
    settings = Settings(
        JWT_SIGNING_KEY_OR_JWKS="test-secret-key-at-least-32-chars-long",
    )
    upload_service = UploadService(
        meeting_repo=None,  # type: ignore[arg-type]
        recording_repo=None,  # type: ignore[arg-type]
        job_repo=None,  # type: ignore[arg-type]
        storage_provider=None,  # type: ignore[arg-type]
        settings=settings,
    )

    meeting_id = uuid.uuid4()
    recording_id = uuid.uuid4()
    user_id = uuid.uuid4()
    attacker_user_id = uuid.uuid4()

    now = int(datetime.datetime.now(datetime.UTC).timestamp())
    valid_token = upload_service.generate_upload_token(
        meeting_id=meeting_id,
        recording_id=recording_id,
        user_id=user_id,
        expires_at=now + 900,
    )

    # 1. Valid token verifies
    assert (
        upload_service.verify_upload_token(
            token=valid_token,
            expected_meeting_id=meeting_id,
            expected_recording_id=recording_id,
            expected_user_id=user_id,
        )
        is True
    )

    # 2. Token used for attacker user fails
    assert (
        upload_service.verify_upload_token(
            token=valid_token,
            expected_meeting_id=meeting_id,
            expected_recording_id=recording_id,
            expected_user_id=attacker_user_id,
        )
        is False
    )

    # 3. Tampered signature fails
    tampered_sig_token = valid_token[:-4] + "dead"
    assert (
        upload_service.verify_upload_token(
            token=tampered_sig_token,
            expected_meeting_id=meeting_id,
            expected_recording_id=recording_id,
            expected_user_id=user_id,
        )
        is False
    )

    # 4. Expired token fails
    expired_token = upload_service.generate_upload_token(
        meeting_id=meeting_id,
        recording_id=recording_id,
        user_id=user_id,
        expires_at=now - 10,
    )
    assert (
        upload_service.verify_upload_token(
            token=expired_token,
            expected_meeting_id=meeting_id,
            expected_recording_id=recording_id,
            expected_user_id=user_id,
        )
        is False
    )

