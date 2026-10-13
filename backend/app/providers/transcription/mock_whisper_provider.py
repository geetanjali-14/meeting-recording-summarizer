from pathlib import Path

from app.core.config import Settings
from app.providers.transcription.base import (
    TranscriptionProvider,
    TranscriptionProviderError,
    TranscriptionResult,
    TranscriptSegmentResult,
)


class MockWhisperProvider(TranscriptionProvider):
    """Mock/dev Whisper transcription provider for tests and local development."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings

    def transcribe(self, audio_file_path: str, language: str | None = None) -> TranscriptionResult:
        path = Path(audio_file_path)
        if not path.exists():
            raise TranscriptionProviderError(
                f"Audio file does not exist: {audio_file_path}", is_retryable=False
            )

        segments = [
            TranscriptSegmentResult(
                sequence_index=0,
                start_time=0.0,
                end_time=4.5,
                text="Let us review the database schema migration plan.",
                speaker_label="SPEAKER_00",
                speaker="SPEAKER_00",
            ),
            TranscriptSegmentResult(
                sequence_index=1,
                start_time=4.8,
                end_time=10.2,
                text="Agreed. We will use PostgreSQL from day one with renewable worker leases.",
                speaker_label="SPEAKER_01",
                speaker="SPEAKER_01",
            ),
        ]
        return TranscriptionResult(
            provider="mock",
            model="whisper-large-v3-turbo",
            language=language or "en",
            total_duration_seconds=10.2,
            raw_transcript_text=(
                "Let us review the database schema migration plan. "
                "Agreed. We will use PostgreSQL from day one with renewable worker leases."
            ),
            segments=segments,
        )
