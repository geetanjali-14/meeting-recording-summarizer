import pytest
import subprocess
from pathlib import Path

from app.core.config import Settings
from app.providers.diarization.pyannote_provider import PyannoteDiarizationProvider
from app.providers.transcription.base import TranscriptSegmentResult
from app.services.alignment_service import AlignmentService
from app.services.audio_service import AudioService


@pytest.mark.asyncio
async def test_real_pyannote_multi_speaker_recording(tmp_path: Path) -> None:
    """Verifies that pyannote diarization on real audio detects multiple distinct speakers
    and aligns properly with transcript segments without collapsing to a single speaker.
    """
    settings = Settings(
        _env_file="backend/.env",
        DIARIZATION_PROVIDER="pyannote_community_1",
    )
    if not settings.HF_TOKEN or "placeholder" in settings.HF_TOKEN:
        pytest.skip("Valid HF_TOKEN required for real pyannote test.")

    audio_service = AudioService()
    provider = PyannoteDiarizationProvider(settings)

    # Use existing meeting mp3 if available
    real_mp3 = Path("/home/rails/Downloads/Weekly Meeting Example.mp3")
    if not real_mp3.exists():
        pytest.skip(f"Test fixture {real_mp3} not found")

    wav_path = tmp_path / "test_16k_mono.wav"
    audio_service.convert_to_wav_16k_mono(str(real_mp3), wav_path)

    # 1. Real Diarization
    result = provider.diarize(str(wav_path))
    assert result.provider == "pyannote_community_1"
    assert len(result.turns) > 0

    unique_speakers = set(t.speaker_label for t in result.turns)
    assert len(unique_speakers) >= 2, f"Expected multiple distinct speakers, got: {unique_speakers}"

    # 2. Alignment with synthetic transcript segments across the duration
    mock_segments = [
        TranscriptSegmentResult(
            sequence_index=0,
            start_time=0.0,
            end_time=15.0,
            text="Hello everyone welcome to the weekly team meeting.",
            speaker_label="SPEAKER_00",
        ),
        TranscriptSegmentResult(
            sequence_index=1,
            start_time=18.0,
            end_time=25.0,
            text="I agree, we should plan the upcoming sprint.",
            speaker_label="SPEAKER_00",
        ),
        TranscriptSegmentResult(
            sequence_index=2,
            start_time=32.0,
            end_time=42.0,
            text="From the backend perspective, everything is ready.",
            speaker_label="SPEAKER_00",
        ),
    ]

    alignment_service = AlignmentService()
    aligned = alignment_service.align(mock_segments, result.turns)

    aligned_speakers = set(s.speaker_label for s in aligned)
    assert len(aligned_speakers) >= 2, f"Alignment collapsed distinct speakers: {aligned_speakers}"
    assert "SPEAKER_00" not in aligned_speakers or len(aligned_speakers) > 1


def test_real_pyannote_single_speaker_or_tone(tmp_path: Path) -> None:
    """Verifies that single-speaker audio or uniform tone does NOT fabricate extra speakers."""
    settings = Settings(
        _env_file="backend/.env",
        DIARIZATION_PROVIDER="pyannote_community_1",
    )
    if not settings.HF_TOKEN or "placeholder" in settings.HF_TOKEN:
        pytest.skip("Valid HF_TOKEN required for real pyannote test.")

    tone_wav = tmp_path / "tone.wav"
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=4",
        "-ar", "16000", "-ac", "1", str(tone_wav)
    ], check=True, capture_output=True)

    provider = PyannoteDiarizationProvider(settings)
    result = provider.diarize(str(tone_wav))

    unique_speakers = set(t.speaker_label for t in result.turns)
    # A pure tone has 0 or at most 1 speaker; it must never invent multiple speakers
    assert len(unique_speakers) <= 1
