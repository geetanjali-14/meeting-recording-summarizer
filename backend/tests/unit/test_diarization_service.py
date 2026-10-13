from unittest.mock import MagicMock

import pytest

from app.providers.diarization.base import (
    DiarizationProvider,
    DiarizationProviderError,
    DiarizationResult,
    DiarizationTurn,
)
from app.services.diarization_service import (
    DiarizationProcessingError,
    DiarizationService,
)


def test_diarization_service_delegates_to_provider() -> None:
    mock_provider = MagicMock(spec=DiarizationProvider)
    mock_provider.diarize.return_value = DiarizationResult(
        provider="mock_pyannote",
        turns=[
            DiarizationTurn(start_time=0.0, end_time=5.0, speaker_label="SPEAKER_00"),
            DiarizationTurn(start_time=5.0, end_time=10.0, speaker_label="SPEAKER_01"),
        ],
    )

    service = DiarizationService(provider=mock_provider)
    result = service.diarize_audio("/tmp/audio.wav")

    mock_provider.diarize.assert_called_once_with("/tmp/audio.wav")
    assert result.provider == "mock_pyannote"
    assert len(result.turns) == 2
    assert result.turns[0].speaker_label == "SPEAKER_00"
    assert result.turns[1].speaker_label == "SPEAKER_01"


def test_diarization_service_wraps_provider_error() -> None:
    mock_provider = MagicMock(spec=DiarizationProvider)
    mock_provider.diarize.side_effect = DiarizationProviderError(
        "Corrupted audio", is_retryable=False
    )

    service = DiarizationService(provider=mock_provider)
    with pytest.raises(DiarizationProcessingError) as exc_info:
        service.diarize_audio("/tmp/corrupted.wav")

    assert "Corrupted audio" in str(exc_info.value)
    assert exc_info.value.is_retryable is False


def test_diarization_service_preserves_retryable_flag() -> None:
    mock_provider = MagicMock(spec=DiarizationProvider)
    mock_provider.diarize.side_effect = DiarizationProviderError(
        "Network timeout downloading weights", is_retryable=True
    )

    service = DiarizationService(provider=mock_provider)
    with pytest.raises(DiarizationProcessingError) as exc_info:
        service.diarize_audio("/tmp/audio.wav")

    assert exc_info.value.is_retryable is True
