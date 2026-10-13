from unittest.mock import MagicMock

from app.core.config import Settings
from app.providers.storage.r2_provider import R2StorageProvider


def test_r2_storage_provider_url_generation() -> None:
    settings = Settings(
        STORAGE_BUCKET_NAME="test-recordings",
        STORAGE_ENDPOINT_URL="https://test-account.r2.cloudflarestorage.com",
        STORAGE_ACCESS_KEY_ID="test_access_key",
        STORAGE_SECRET_ACCESS_KEY="test_secret_key",
    )
    provider = R2StorageProvider(settings)

    # Mock internal boto3 client
    provider.client = MagicMock()
    provider.client.generate_presigned_url.return_value = (
        "https://test-account.r2.cloudflarestorage.com/test-recordings/test-key?signature=xyz"
    )

    upload_url = provider.generate_presigned_upload_url(
        storage_key="users/u1/recordings/r1/audio.mp4",
        content_type="audio/mp4",
        expires_in_seconds=900,
    )
    assert upload_url.startswith("https://test-account.r2.cloudflarestorage.com")
    provider.client.generate_presigned_url.assert_called_once_with(
        "put_object",
        Params={
            "Bucket": "test-recordings",
            "Key": "users/u1/recordings/r1/audio.mp4",
            "ContentType": "audio/mp4",
        },
        ExpiresIn=900,
        HttpMethod="PUT",
    )

    download_url = provider.generate_presigned_download_url(
        storage_key="users/u1/recordings/r1/audio.mp4",
        expires_in_seconds=3600,
    )
    assert download_url.startswith("https://test-account.r2.cloudflarestorage.com")
