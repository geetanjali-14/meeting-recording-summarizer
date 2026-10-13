import tempfile
from unittest.mock import MagicMock

import pytest

from app.core.config import Settings
from app.providers.diarization import get_diarization_provider
from app.providers.diarization.base import (
    DiarizationProviderError,
)
from app.providers.diarization.mock_diarization_provider import MockDiarizationProvider
from app.providers.diarization.pyannote_provider import PyannoteDiarizationProvider


def test_mock_diarization_provider_success() -> None:
    provider = MockDiarizationProvider()
    with tempfile.NamedTemporaryFile() as tmp:
        result = provider.diarize(tmp.name)
        assert result.provider == "mock_diarization"
        assert len(result.turns) == 2
        assert result.turns[0].speaker_label == "SPEAKER_00"
        assert result.turns[1].speaker_label == "SPEAKER_01"


def test_mock_diarization_provider_missing_file_raises() -> None:
    provider = MockDiarizationProvider()
    with pytest.raises(DiarizationProviderError) as exc_info:
        provider.diarize("/nonexistent/audio.wav")
    assert "Audio file does not exist" in str(exc_info.value)
    assert exc_info.value.is_retryable is False


def test_get_diarization_provider_factory() -> None:
    settings_mock = Settings(DIARIZATION_PROVIDER="mock")
    provider_mock = get_diarization_provider(settings_mock)
    assert isinstance(provider_mock, MockDiarizationProvider)

    settings_pyannote = Settings(
        DIARIZATION_PROVIDER="pyannote_community_1",
        HF_TOKEN="hf_some_valid_token_string_here",
    )
    provider_pyannote = get_diarization_provider(settings_pyannote)
    assert isinstance(provider_pyannote, PyannoteDiarizationProvider)


def test_pyannote_provider_missing_token_fails() -> None:
    settings = Settings(HF_TOKEN="hf_placeholder_token")
    provider = PyannoteDiarizationProvider(settings)

    with tempfile.NamedTemporaryFile() as tmp:
        with pytest.raises(DiarizationProviderError) as exc_info:
            provider.diarize(tmp.name)
        assert "Missing or invalid Hugging Face token" in str(exc_info.value)
        assert exc_info.value.is_retryable is False


def test_pyannote_provider_parses_annotation_itertracks() -> None:
    settings = Settings(HF_TOKEN="hf_valid_test_token_1234567890")
    provider = PyannoteDiarizationProvider(settings)

    mock_pipeline = MagicMock()
    mock_annotation = MagicMock()

    class MockSegment:
        def __init__(self, start: float, end: float) -> None:
            self.start = start
            self.end = end

    mock_annotation.itertracks.return_value = [
        (MockSegment(0.0, 2.5), None, "SPEAKER_00"),
        (MockSegment(2.6, 5.0), None, "SPEAKER_01"),
    ]

    class MockDiarizeOutput:
        speaker_diarization = mock_annotation

    mock_pipeline.return_value = MockDiarizeOutput()
    provider._pipeline = mock_pipeline

    with tempfile.NamedTemporaryFile() as tmp:
        result = provider.diarize(tmp.name)

    assert result.provider == "pyannote_community_1"
    assert len(result.turns) == 2
    assert result.turns[0].speaker_label == "SPEAKER_00"
    assert result.turns[0].start_time == 0.0
    assert result.turns[0].end_time == 2.5
    assert result.turns[1].speaker_label == "SPEAKER_01"
