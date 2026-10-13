from abc import ABC, abstractmethod

from pydantic import BaseModel, Field


class TranscriptSegmentResult(BaseModel):
    """Normalized transcript segment returned by transcription providers."""

    sequence_index: int
    start_time: float
    end_time: float
    text: str
    speaker_label: str | None = None
    speaker: str | None = None
    confidence: float | None = None


class TranscriptionResult(BaseModel):
    """Normalized transcription result containing full text and timestamped segments."""

    provider: str
    model: str
    language: str | None = "en"
    total_duration_seconds: float | None = None
    raw_transcript_text: str = ""
    segments: list[TranscriptSegmentResult] = Field(default_factory=list)


class TranscriptionProviderError(Exception):
    """Base exception for transcription provider failures."""

    def __init__(self, message: str, is_retryable: bool = False) -> None:
        super().__init__(message)
        self.message = message
        self.is_retryable = is_retryable


class TranscriptionProvider(ABC):
    """Abstract interface for speech-to-text transcription providers."""

    @abstractmethod
    def transcribe(self, audio_file_path: str, language: str | None = None) -> TranscriptionResult:
        """Transcribes a local 16 kHz mono WAV audio file into timestamped segments."""
        pass
