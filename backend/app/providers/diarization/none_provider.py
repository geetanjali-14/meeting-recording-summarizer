from pathlib import Path

from app.core.config import Settings
from app.providers.diarization.base import (
    DiarizationProvider,
    DiarizationProviderError,
    DiarizationResult,
)


class NoneDiarizationProvider(DiarizationProvider):
    """Explicit no-op diarization provider when diarization is disabled or unavailable."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings

    def diarize(self, audio_file_path: str) -> DiarizationResult:
        path = Path(audio_file_path)
        if not path.exists():
            raise DiarizationProviderError(
                f"Audio file does not exist: {audio_file_path}", is_retryable=False
            )
        # Returns empty turns so segments retain Whisper speaker labels (e.g. SPEAKER_00)
        # without fabricating fake speaker turns.
        return DiarizationResult(provider="none", turns=[])
