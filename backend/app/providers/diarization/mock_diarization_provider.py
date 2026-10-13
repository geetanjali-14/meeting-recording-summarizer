from pathlib import Path

from app.core.config import Settings
from app.providers.diarization.base import (
    DiarizationProvider,
    DiarizationProviderError,
    DiarizationResult,
    DiarizationTurn,
)


class MockDiarizationProvider(DiarizationProvider):
    """Deterministic mock diarization provider for testing without GPU/HuggingFace dependencies."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings

    def diarize(self, audio_file_path: str) -> DiarizationResult:
        path = Path(audio_file_path)
        if not path.exists():
            raise DiarizationProviderError(
                f"Audio file does not exist: {audio_file_path}", is_retryable=False
            )

        turns = [
            DiarizationTurn(start_time=0.0, end_time=4.5, speaker_label="SPEAKER_00"),
            DiarizationTurn(start_time=4.8, end_time=10.2, speaker_label="SPEAKER_01"),
        ]
        return DiarizationResult(provider="mock_diarization", turns=turns)
