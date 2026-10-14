from app.core.config import Settings
from app.providers.transcription.base import TranscriptionProvider
from app.providers.transcription.groq_whisper_provider import GroqWhisperProvider
from app.providers.transcription.mock_whisper_provider import MockWhisperProvider


def get_transcription_provider(settings: Settings) -> TranscriptionProvider:
    """Factory creating the appropriate TranscriptionProvider based on application settings."""
    if settings.TRANSCRIPTION_PROVIDER == "mock":
        return MockWhisperProvider(settings)
    return GroqWhisperProvider(settings)
