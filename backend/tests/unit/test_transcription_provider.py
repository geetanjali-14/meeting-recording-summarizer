import tempfile
from unittest.mock import MagicMock, patch

import pytest

from app.core.config import Settings
from app.providers.transcription.base import TranscriptionProviderError
from app.providers.transcription.groq_whisper_provider import GroqWhisperProvider
from app.providers.transcription.mock_whisper_provider import MockWhisperProvider


def test_mock_whisper_provider_transcribes() -> None:
    provider = MockWhisperProvider()
    with tempfile.NamedTemporaryFile() as tmp:
        result = provider.transcribe(tmp.name)
        assert result.provider == "mock"
        assert len(result.segments) == 2
        assert result.segments[0].speaker_label == "SPEAKER_00"
        assert result.segments[1].speaker_label == "SPEAKER_01"
        assert "PostgreSQL" in result.raw_transcript_text


def test_mock_whisper_provider_missing_file_raises() -> None:
    provider = MockWhisperProvider()
    with pytest.raises(TranscriptionProviderError) as exc_info:
        provider.transcribe("/path/does/not/exist.wav")
    assert exc_info.value.is_retryable is False


@patch("httpx.Client.post")
def test_groq_whisper_provider_success(mock_post: MagicMock) -> None:
    settings = Settings(
        TRANSCRIPTION_API_KEY="test_groq_key",
        TRANSCRIPTION_MODEL="whisper-large-v3-turbo",
    )
    provider = GroqWhisperProvider(settings)

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "text": "Hello world. Testing Groq Whisper.",
        "language": "en",
        "duration": 5.2,
        "segments": [
            {
                "id": 0,
                "start": 0.0,
                "end": 2.5,
                "text": "Hello world.",
                "speaker": "SPEAKER_00",
                "avg_logprob": -0.15,
            },
            {
                "id": 1,
                "start": 2.6,
                "end": 5.2,
                "text": "Testing Groq Whisper.",
                "speaker": "SPEAKER_01",
                "avg_logprob": -0.12,
            },
        ],
    }
    mock_post.return_value = mock_response

    with tempfile.NamedTemporaryFile() as tmp:
        result = provider.transcribe(tmp.name)
        assert result.provider == "groq_whisper_turbo"
        assert result.model == "whisper-large-v3-turbo"
        assert len(result.segments) == 2
        assert result.segments[0].text == "Hello world."
        assert result.segments[1].speaker_label == "SPEAKER_01"


@patch("httpx.Client.post")
def test_groq_whisper_provider_rate_limit_retryable(mock_post: MagicMock) -> None:
    settings = Settings(
        TRANSCRIPTION_API_KEY="test_groq_key",
        TRANSCRIPTION_MODEL="whisper-large-v3-turbo",
    )
    provider = GroqWhisperProvider(settings)

    mock_response = MagicMock()
    mock_response.status_code = 429
    mock_response.text = "Rate limit exceeded"
    mock_post.return_value = mock_response

    with tempfile.NamedTemporaryFile() as tmp:
        with pytest.raises(TranscriptionProviderError) as exc_info:
            provider.transcribe(tmp.name)
        assert exc_info.value.is_retryable is True


@patch("httpx.Client.post")
def test_groq_whisper_provider_client_error_permanent(mock_post: MagicMock) -> None:
    settings = Settings(
        TRANSCRIPTION_API_KEY="test_groq_key",
        TRANSCRIPTION_MODEL="whisper-large-v3-turbo",
    )
    provider = GroqWhisperProvider(settings)

    mock_response = MagicMock()
    mock_response.status_code = 400
    mock_response.text = "Invalid request format"
    mock_post.return_value = mock_response

    with tempfile.NamedTemporaryFile() as tmp:
        with pytest.raises(TranscriptionProviderError) as exc_info:
            provider.transcribe(tmp.name)
        assert exc_info.value.is_retryable is False

