from abc import ABC, abstractmethod

from pydantic import BaseModel, Field


class DiarizationTurn(BaseModel):
    """Detected speaker turn with start/end bounds in seconds."""

    start_time: float
    end_time: float
    speaker_label: str


class DiarizationResult(BaseModel):
    """Collection of detected speaker turns returned by a DiarizationProvider."""

    provider: str
    turns: list[DiarizationTurn] = Field(default_factory=list)


class DiarizationProviderError(Exception):
    """Exception raised when a diarization provider encounters a processing error."""

    def __init__(self, message: str, is_retryable: bool = False) -> None:
        super().__init__(message)
        self.message = message
        self.is_retryable = is_retryable


class DiarizationProvider(ABC):
    """Abstract interface for speaker turn diarization providers."""

    @abstractmethod
    def diarize(self, audio_file_path: str) -> DiarizationResult:
        """Processes a normalized 16 kHz mono WAV audio file and returns detected speaker turns."""
        pass
