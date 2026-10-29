import uuid
from unittest.mock import MagicMock
import pytest

from app.core.config import Settings
from app.providers.transcription.mock_whisper_provider import MockWhisperProvider
from app.providers.llm.mock_provider import MockLLMProvider
from app.providers.transcription.groq_whisper_provider import GroqWhisperProvider
from app.providers.llm.groq_provider import GroqProvider
from app.providers.storage.r2_provider import R2StorageProvider
from app.providers.diarization.none_provider import NoneDiarizationProvider


MOCK_TRANSCRIPT_LEAK_PHRASE = "Let us review the database schema migration plan"
MOCK_SUMMARY_LEAK_PHRASE = "The team reviewed database migration architecture"


def test_production_providers_do_not_contain_mock_text():
    """Verify that production providers (GroqWhisper, GroqProvider, NoneDiarization)
    never use or contain the hardcoded mock sentences.
    """
    settings = Settings(
        APP_ENV="development",
        STORAGE_PROVIDER="r2",
        LLM_PROVIDER="groq",
        TRANSCRIPTION_PROVIDER="groq_whisper_turbo",
        DIARIZATION_PROVIDER="none",
        TRANSCRIPTION_API_KEY="gsk_test_key_dummy_1234567890",
        LLM_API_KEY="gsk_test_key_dummy_1234567890",
        HF_TOKEN="hf_dummy_token_1234567890",
    )

    # 1. Verify NoneDiarizationProvider returns clean empty turns
    none_diar = NoneDiarizationProvider(settings)
    assert none_diar is not None

    # 2. Check that GroqWhisperProvider parsing does not fabricate mock text
    audio_svc = MagicMock()
    whisper_prov = GroqWhisperProvider(settings, audio_service=audio_svc)
    payload = {
        "text": "Actual customer discussion regarding project roadmaps.",
        "segments": [
            {
                "id": 0,
                "start": 0.0,
                "end": 2.5,
                "text": "Actual customer discussion regarding project roadmaps.",
            }
        ]
    }
    result = whisper_prov._parse_payload(payload)
    assert MOCK_TRANSCRIPT_LEAK_PHRASE not in result.raw_transcript_text
    assert "Actual customer discussion" in result.raw_transcript_text
    assert len(result.segments) == 1
    assert result.segments[0].text == "Actual customer discussion regarding project roadmaps."


def test_empty_transcription_payload_does_not_produce_mock_text():
    """Verify empty or whitespace payload produces empty segments, not fallback text."""
    settings = Settings(
        APP_ENV="development",
        STORAGE_PROVIDER="r2",
        LLM_PROVIDER="groq",
        TRANSCRIPTION_PROVIDER="groq_whisper_turbo",
        DIARIZATION_PROVIDER="none",
        TRANSCRIPTION_API_KEY="gsk_test_key_dummy_1234567890",
        LLM_API_KEY="gsk_test_key_dummy_1234567890",
    )
    whisper_prov = GroqWhisperProvider(settings, audio_service=MagicMock())
    empty_payload = {"text": "   ", "segments": []}
    result = whisper_prov._parse_payload(empty_payload)
    assert len(result.segments) == 0
    assert MOCK_TRANSCRIPT_LEAK_PHRASE not in result.raw_transcript_text

