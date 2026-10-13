import logging
from pathlib import Path

from app.core.config import Settings
from app.providers.diarization.base import (
    DiarizationProvider,
    DiarizationProviderError,
    DiarizationResult,
)

logger = logging.getLogger(__name__)


class DiarizationProcessingError(Exception):
    """Raised when diarization service encounters an error."""

    def __init__(self, message: str, is_retryable: bool = False) -> None:
        super().__init__(message)
        self.message = message
        self.is_retryable = is_retryable


class DiarizationService:
    """Service wrapping DiarizationProvider to detect speaker turns from normalized audio."""

    def __init__(
        self,
        provider: DiarizationProvider,
        settings: Settings | None = None,
    ) -> None:
        self.provider = provider
        self.settings = settings

    def diarize_audio(self, audio_file_path: str | Path) -> DiarizationResult:
        """Diarizes an audio file using the configured provider."""
        path_str = str(audio_file_path)
        try:
            return self.provider.diarize(path_str)
        except DiarizationProviderError as exc:
            logger.error("Diarization provider failure: %s", exc.message)
            raise DiarizationProcessingError(
                f"Diarization failed: {exc.message}",
                is_retryable=exc.is_retryable,
            ) from exc
        except Exception as exc:
            logger.error("Unexpected error during diarization: %s", exc)
            raise DiarizationProcessingError(
                f"Unexpected diarization error: {exc}",
                is_retryable=False,
            ) from exc
