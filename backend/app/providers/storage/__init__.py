from app.core.config import Settings
from app.providers.storage.base import StorageProvider
from app.providers.storage.r2_provider import R2StorageProvider


def get_storage_provider(settings: Settings) -> StorageProvider:
    """Factory creating the appropriate StorageProvider based on settings."""
    # When r2 or s3 is configured, R2StorageProvider acts as the S3-compatible provider
    return R2StorageProvider(settings)

