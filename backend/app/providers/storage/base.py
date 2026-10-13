from abc import ABC, abstractmethod


class StorageProvider(ABC):
    """Abstract interface for object storage operations."""

    @abstractmethod
    def generate_presigned_upload_url(
        self,
        storage_key: str,
        content_type: str,
        expires_in_seconds: int = 900,
    ) -> str:
        """Generates a pre-signed PUT URL for direct client upload."""
        pass

    @abstractmethod
    def generate_presigned_download_url(
        self,
        storage_key: str,
        expires_in_seconds: int = 3600,
    ) -> str:
        """Generates a pre-signed GET URL for temporary private object download."""
        pass

    @abstractmethod
    def delete_object(self, storage_key: str) -> None:
        """Deletes an object from storage."""
        pass

    @abstractmethod
    def object_exists(self, storage_key: str) -> bool:
        """Checks if an object exists in storage."""
        pass
