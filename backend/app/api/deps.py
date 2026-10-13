import logging
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.database import async_session_factory
from app.core.security import SecurityError, UserContext, verify_jwt_token
from app.providers.storage import get_storage_provider as get_storage_provider_factory
from app.providers.storage.base import StorageProvider
from app.repositories.job_repository import JobRepository
from app.repositories.meeting_repository import MeetingRepository
from app.repositories.recording_repository import RecordingRepository

if TYPE_CHECKING:
    from app.services.meeting_service import MeetingService
    from app.services.upload_service import UploadService

logger = logging.getLogger(__name__)

# auto_error=False allows returning custom standardized 401 error envelope
http_bearer = HTTPBearer(auto_error=False)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency for yielding database session with automatic commit/rollback."""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Security(http_bearer),
    settings: Settings = Depends(get_settings),
) -> UserContext:
    """Reusable FastAPI dependency extracting and validating authenticated user identity.

    Fails closed:
    - Missing Authorization header -> 401 Unauthorized
    - Malformed or invalid JWT -> 401 Unauthorized
    - Expired or unverifiable token -> 401 Unauthorized
    - Invalid subject UUID -> 401 Unauthorized

    Never logs access tokens or sensitive payloads.
    """
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer authorization credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials
    try:
        user_context = await verify_jwt_token(token=token, settings=settings)
        return user_context
    except SecurityError as err:
        logger.warning("Authentication failed", extra={"reason": err.message})
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        ) from err
    except Exception as exc:
        logger.error("Unexpected error during authentication verification", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication failed",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


def get_storage_provider(
    settings: Settings = Depends(get_settings),
) -> StorageProvider:
    """Dependency providing the configured storage provider instance."""
    return get_storage_provider_factory(settings)


def get_meeting_repository(
    session: AsyncSession = Depends(get_db_session),
) -> MeetingRepository:
    """Dependency providing a MeetingRepository instance."""
    return MeetingRepository(session)


def get_recording_repository(
    session: AsyncSession = Depends(get_db_session),
) -> RecordingRepository:
    """Dependency providing a RecordingRepository instance."""
    return RecordingRepository(session)


def get_job_repository(
    session: AsyncSession = Depends(get_db_session),
) -> JobRepository:
    """Dependency providing a JobRepository instance."""
    return JobRepository(session)


def get_meeting_service(
    meeting_repo: MeetingRepository = Depends(get_meeting_repository),
    storage_provider: StorageProvider = Depends(get_storage_provider),
) -> "MeetingService":
    from app.services.meeting_service import MeetingService

    return MeetingService(meeting_repo=meeting_repo, storage_provider=storage_provider)


def get_transcript_repository(
    session: AsyncSession = Depends(get_db_session),
) -> "TranscriptRepository":
    from app.repositories.transcript_repository import TranscriptRepository

    return TranscriptRepository(session)


def get_chat_repository(
    session: AsyncSession = Depends(get_db_session),
) -> "ChatRepository":
    from app.repositories.chat_repository import ChatRepository

    return ChatRepository(session)


def get_llm_provider(
    settings: Settings = Depends(get_settings),
) -> "LLMProvider":
    from app.providers.llm import get_llm_provider as get_llm_provider_factory

    return get_llm_provider_factory(settings)


def get_upload_service(
    meeting_repo: MeetingRepository = Depends(get_meeting_repository),
    recording_repo: RecordingRepository = Depends(get_recording_repository),
    job_repo: JobRepository = Depends(get_job_repository),
    storage_provider: StorageProvider = Depends(get_storage_provider),
    settings: Settings = Depends(get_settings),
) -> "UploadService":
    from app.services.upload_service import UploadService

    return UploadService(
        meeting_repo=meeting_repo,
        recording_repo=recording_repo,
        job_repo=job_repo,
        storage_provider=storage_provider,
        settings=settings,
    )


def get_chat_service(
    meeting_repo: MeetingRepository = Depends(get_meeting_repository),
    transcript_repo: "TranscriptRepository" = Depends(get_transcript_repository),
    chat_repo: "ChatRepository" = Depends(get_chat_repository),
    llm_provider: "LLMProvider" = Depends(get_llm_provider),
    settings: Settings = Depends(get_settings),
) -> "ChatService":
    from app.services.chat_service import ChatService

    return ChatService(
        meeting_repo=meeting_repo,
        transcript_repo=transcript_repo,
        chat_repo=chat_repo,
        llm_provider=llm_provider,
        settings=settings,
    )
