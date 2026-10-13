from app.core.config import Settings
from app.providers.diarization.base import DiarizationProvider
from app.providers.diarization.mock_diarization_provider import MockDiarizationProvider
from app.providers.diarization.pyannote_provider import PyannoteDiarizationProvider


def get_diarization_provider(settings: Settings) -> DiarizationProvider:
    """Factory creating the appropriate DiarizationProvider based on application settings."""
    if settings.DIARIZATION_PROVIDER == "mock":
        return MockDiarizationProvider(settings)
    return PyannoteDiarizationProvider(settings)
