import base64
import hashlib
import hmac
import json
import logging
import time
import uuid

from app.core.celery_app import celery_app
from app.core.config import Settings
from app.models.meeting import Meeting, MeetingStatus
from app.models.processing_job import ProcessingJob
from app.models.recording import Recording, RecordingStatus
from app.providers.storage.base import StorageProvider
from app.repositories.job_repository import JobRepository
from app.repositories.meeting_repository import MeetingRepository
from app.repositories.recording_repository import RecordingRepository
from app.repositories.user_repository import UserRepository
from app.schemas.meeting import (
    ALLOWED_CONTENT_TYPES,
    MAX_FILE_SIZE_BYTES,
    MeetingCreateRequest,
)

logger = logging.getLogger(__name__)


class UploadServiceError(Exception):
    """Base exception for upload service operations."""

    def __init__(self, message: str, code: str = "INTERNAL_ERROR", status_code: int = 500) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code


class UploadValidationError(UploadServiceError):
    def __init__(self, message: str) -> None:
        super().__init__(message, code="VALIDATION_ERROR", status_code=422)


class UploadNotFoundError(UploadServiceError):
    def __init__(self, message: str = "Resource not found") -> None:
        super().__init__(message, code="NOT_FOUND", status_code=404)


class UploadConflictError(UploadServiceError):
    def __init__(self, message: str) -> None:
        super().__init__(message, code="CONFLICT", status_code=409)


class UploadStorageError(UploadServiceError):
    def __init__(self, message: str = "Upstream object storage error") -> None:
        super().__init__(message, code="STORAGE_ERROR", status_code=502)


class UploadDispatchError(UploadServiceError):
    def __init__(self, message: str = "Background job dispatch failed") -> None:
        super().__init__(message, code="INTERNAL_ERROR", status_code=500)


class UploadService:
    """Service handling meeting creation, presigned upload URLs, validation, and confirmation."""

    def __init__(
        self,
        meeting_repo: MeetingRepository,
        recording_repo: RecordingRepository,
        job_repo: JobRepository,
        storage_provider: StorageProvider,
        settings: Settings,
        user_repo: UserRepository | None = None,
    ) -> None:
        self.meeting_repo = meeting_repo
        self.recording_repo = recording_repo
        self.job_repo = job_repo
        self.storage_provider = storage_provider
        self.settings = settings
        self.user_repo = user_repo

    def generate_upload_token(
        self,
        meeting_id: uuid.UUID,
        recording_id: uuid.UUID,
        user_id: uuid.UUID,
        expires_at: int,
    ) -> str:
        """Generates a secure HMAC-signed upload token encoding
        meeting, recording, and user identity.
        """
        payload = {
            "mid": str(meeting_id),
            "rid": str(recording_id),
            "uid": str(user_id),
            "exp": expires_at,
        }
        raw_json = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        payload_b64 = base64.urlsafe_b64encode(raw_json).decode("utf-8")
        secret = self.settings.UPLOAD_TOKEN_SECRET.encode("utf-8")
        signature = hmac.new(secret, payload_b64.encode("utf-8"), hashlib.sha256).hexdigest()
        return f"up_tok_{payload_b64}.{signature}"

    def verify_upload_token(
        self,
        token: str,
        expected_meeting_id: uuid.UUID,
        expected_recording_id: uuid.UUID,
        expected_user_id: uuid.UUID,
    ) -> bool:
        """Verifies token signature, expiration, and binding to meeting, recording, and user."""
        if not token.startswith("up_tok_") or "." not in token:
            return False
        stripped = token[len("up_tok_") :]
        parts = stripped.split(".")
        if len(parts) != 2:
            return False
        payload_b64, signature = parts
        secret = self.settings.UPLOAD_TOKEN_SECRET.encode("utf-8")
        expected_signature = hmac.new(
            secret, payload_b64.encode("utf-8"), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(signature, expected_signature):
            return False
        try:
            raw_json = base64.urlsafe_b64decode(payload_b64.encode("utf-8"))
            data = json.loads(raw_json.decode("utf-8"))
            if int(data.get("exp", 0)) < int(time.time()):
                return False
            if data.get("mid") != str(expected_meeting_id):
                return False
            if data.get("rid") != str(expected_recording_id):
                return False
            if data.get("uid") != str(expected_user_id):
                return False
            return True
        except Exception:
            return False

    async def initiate_meeting_upload(
        self,
        user_id: uuid.UUID,
        request: MeetingCreateRequest,
        user_email: str | None = None,
    ) -> tuple[Meeting, Recording, str, str, int]:
        """Creates meeting, recording entity, and generates presigned PUT upload URL."""
        # 1. Validation
        if request.content_type not in ALLOWED_CONTENT_TYPES:
            raise UploadValidationError(
                f"Content type '{request.content_type}' is not supported. "
                f"Permitted types: {', '.join(sorted(ALLOWED_CONTENT_TYPES))}"
            )
        if request.file_size_bytes <= 0 or request.file_size_bytes > MAX_FILE_SIZE_BYTES:
            raise UploadValidationError(
                f"File size must be between 1 and {MAX_FILE_SIZE_BYTES} bytes."
            )

        # 2. Ensure local user record exists for foreign-key constraint integrity
        if self.user_repo is not None:
            user = await self.user_repo.get_by_id(user_id)
            if user is None:
                # Provision local user row idempotently
                email_to_use = user_email or f"user_{user_id}@placeholder.app"
                await self.user_repo.upsert_user(
                    user_id=user_id,
                    email=email_to_use,
                )

        # 3. Persist meeting aggregate
        meeting = await self.meeting_repo.create(
            user_id=user_id,
            title=request.title,
            description=request.description,
            meeting_date=request.meeting_date,
        )

        # 3. Create Recording record
        recording_id = uuid.uuid4()
        storage_key = f"users/{user_id}/recordings/{recording_id}/{request.filename}"

        recording = await self.recording_repo.create(
            recording_id=recording_id,
            meeting_id=meeting.id,
            user_id=user_id,
            storage_key=storage_key,
            original_filename=request.filename,
            content_type=request.content_type,
            file_size_bytes=request.file_size_bytes,
            status=RecordingStatus.PRESIGNED,
        )

        # 4. Generate presigned PUT URL
        expires_in = self.settings.STORAGE_PRESIGNED_UPLOAD_EXPIRY_SECONDS
        try:
            upload_url = self.storage_provider.generate_presigned_upload_url(
                storage_key=storage_key,
                content_type=request.content_type,
                expires_in_seconds=expires_in,
            )
        except Exception as exc:
            logger.error("Failed to generate presigned upload URL", exc_info=True)
            raise UploadStorageError(f"Storage authorization failed: {exc}") from exc

        # 5. Generate secure upload token
        token_expires_at = int(time.time()) + expires_in
        upload_token = self.generate_upload_token(
            meeting_id=meeting.id,
            recording_id=recording.id,
            user_id=user_id,
            expires_at=token_expires_at,
        )

        return meeting, recording, upload_url, upload_token, expires_in

    async def confirm_upload(
        self,
        meeting_id: uuid.UUID,
        recording_id: uuid.UUID,
        upload_token: str,
        user_id: uuid.UUID,
    ) -> tuple[Meeting, ProcessingJob]:
        """Verifies uploaded object presence, transitions statuses,
        creates job, and dispatches Celery task.
        """
        # 1. Fetch meeting and recording
        meeting = await self.meeting_repo.get_by_id(
            meeting_id=meeting_id,
            user_id=user_id,
            include_relations=True,
        )
        if meeting is None or meeting.status in (MeetingStatus.DELETING, MeetingStatus.PURGED):
            raise UploadNotFoundError("Meeting not found")

        recording = await self.recording_repo.get_by_id(
            recording_id=recording_id,
            user_id=user_id,
        )
        if recording is None or recording.meeting_id != meeting_id:
            raise UploadNotFoundError("Recording not found")

        # 2. Token validation
        if not self.verify_upload_token(
            token=upload_token,
            expected_meeting_id=meeting_id,
            expected_recording_id=recording_id,
            expected_user_id=user_id,
        ):
            raise UploadValidationError("Invalid or expired upload token")

        # 3. Object existence check in object storage (HeadObject verify)
        try:
            exists = self.storage_provider.object_exists(recording.storage_key)
        except Exception as exc:
            logger.error(
                "Error checking object existence in storage",
                extra={"storage_key": recording.storage_key, "error": str(exc)},
            )
            raise UploadStorageError("Failed to verify object presence in storage") from exc

        if not exists:
            raise UploadConflictError(
                "Media binary not found in storage. Ensure direct upload "
                "completed before confirmation."
            )

        # 4. State transitions: Recording -> UPLOADED, Meeting -> ACTIVE
        await self.recording_repo.mark_uploaded(recording)
        await self.meeting_repo.mark_active(meeting)

        # 5. Check or create ProcessingJob
        job = await self.job_repo.get_by_meeting_id(meeting_id=meeting_id, user_id=user_id)
        if job is None:
            job = await self.job_repo.create(meeting_id=meeting_id, user_id=user_id)

        # 6. Dispatch Celery task
        task_name = "process_meeting_recording"
        try:
            celery_result = celery_app.send_task(
                task_name,
                args=[str(job.id), str(meeting.id)],
            )
            await self.job_repo.set_celery_task_id(job=job, celery_task_id=celery_result.id)
        except Exception as exc:
            logger.error(
                "Failed to dispatch Celery ingestion task",
                extra={"job_id": str(job.id), "error": str(exc)},
                exc_info=True,
            )
            raise UploadDispatchError(f"Failed to queue ingestion job: {exc}") from exc

        return meeting, job
