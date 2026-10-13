import boto3
from botocore.config import Config

from app.core.config import Settings
from app.providers.storage.base import StorageProvider


class R2StorageProvider(StorageProvider):
    """Cloudflare R2 / S3 compatible storage provider via boto3."""

    def __init__(self, settings: Settings) -> None:
        self.bucket_name = settings.STORAGE_BUCKET_NAME
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.STORAGE_ENDPOINT_URL,
            aws_access_key_id=settings.STORAGE_ACCESS_KEY_ID,
            aws_secret_access_key=settings.STORAGE_SECRET_ACCESS_KEY,
            region_name=settings.STORAGE_REGION,
            config=Config(signature_version="s3v4"),
        )

    def generate_presigned_upload_url(
        self,
        storage_key: str,
        content_type: str,
        expires_in_seconds: int = 900,
    ) -> str:
        url: str = self.client.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": self.bucket_name,
                "Key": storage_key,
                "ContentType": content_type,
            },
            ExpiresIn=expires_in_seconds,
            HttpMethod="PUT",
        )
        return url

    def generate_presigned_download_url(
        self,
        storage_key: str,
        expires_in_seconds: int = 3600,
    ) -> str:
        url: str = self.client.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": self.bucket_name,
                "Key": storage_key,
            },
            ExpiresIn=expires_in_seconds,
        )
        return url

    def delete_object(self, storage_key: str) -> None:
        self.client.delete_object(Bucket=self.bucket_name, Key=storage_key)

    def object_exists(self, storage_key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket_name, Key=storage_key)
            return True
        except Exception:
            return False
