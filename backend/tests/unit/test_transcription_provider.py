import tempfile
from pathlib import Path
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


def test_groq_whisper_provider_missing_credentials_fails_clearly() -> None:
    settings = Settings(
        TRANSCRIPTION_API_KEY="gsk_placeholder_groq_api_key",
    )
    provider = GroqWhisperProvider(settings)

    with tempfile.NamedTemporaryFile() as tmp:
        with pytest.raises(TranscriptionProviderError) as exc_info:
            provider.transcribe(tmp.name)
        assert "Missing or invalid Groq transcription API key" in str(exc_info.value)
        assert exc_info.value.is_retryable is False


@patch("httpx.Client.post")
def test_groq_whisper_provider_413_is_non_retryable(mock_post: MagicMock) -> None:
    settings = Settings(
        TRANSCRIPTION_API_KEY="test_groq_key",
        TRANSCRIPTION_MODEL="whisper-large-v3-turbo",
    )
    provider = GroqWhisperProvider(settings)

    mock_response = MagicMock()
    mock_response.status_code = 413
    mock_response.text = (
        '{"error":{"message":"Request Entity Too Large",'
        '"type":"invalid_request_error","code":"request_too_large"}}'
    )
    mock_post.return_value = mock_response

    with tempfile.NamedTemporaryFile() as tmp:
        # Directly calling _call_groq_api raises non-retryable 413 error
        with pytest.raises(TranscriptionProviderError) as exc_info:
            provider._call_groq_api(Path(tmp.name), "audio/wav")
        assert exc_info.value.is_retryable is False
        assert "413" in exc_info.value.message or "Too Large" in exc_info.value.message


def test_groq_whisper_provider_compresses_and_chunks_oversized_audio() -> None:
    settings = Settings(
        TRANSCRIPTION_API_KEY="test_groq_key",
        TRANSCRIPTION_MODEL="whisper-large-v3-turbo",
    )
    mock_audio_service = MagicMock()
    mock_audio_service.temporary_scratch_dir.side_effect = tempfile.TemporaryDirectory

    def mock_compress(src, dest, bitrate="64k"):
        # Make compressed size greater than MAX_GROQ_PAYLOAD_BYTES to trigger chunking
        Path(dest).write_bytes(b"compressed_data" * 20)
        return str(dest)

    mock_audio_service.compress_to_mp3.side_effect = mock_compress
    mock_audio_service.validate_media_file.return_value = {"duration": 1500.0}

    def mock_extract(input_path, output_path, start_seconds, duration_seconds, bitrate="64k"):
        Path(output_path).write_bytes(b"chunk_data" * 5)
        return str(output_path)

    mock_audio_service.extract_audio_segment.side_effect = mock_extract

    provider = GroqWhisperProvider(settings, audio_service=mock_audio_service)
    # Simulate oversized file threshold
    provider.MAX_GROQ_PAYLOAD_BYTES = 100
    provider.CHUNK_DURATION_SECONDS = 600.0
    provider.CHUNK_OVERLAP_SECONDS = 0.0

    call_count = 0

    def mock_call(path, mime_type, language=None, prompt=None):
        nonlocal call_count
        call_count += 1
        return {
            "text": f"Chunk text {call_count}",
            "language": "en",
            "duration": 600.0 if call_count < 3 else 300.0,
            "segments": [
                {
                    "start": 10.0,
                    "end": 20.0,
                    "text": f"Segment in chunk {call_count}",
                    "speaker": "SPEAKER_00",
                    "avg_logprob": -0.2,
                }
            ],
        }

    provider._call_groq_api = mock_call  # type: ignore[assignment]

    with tempfile.NamedTemporaryFile() as tmp:
        tmp.write(b"0" * 200)
        tmp.flush()

        result = provider.transcribe(tmp.name)

        assert len(result.segments) == 3
        # First chunk offset is 0.0 -> segment start = 10.0, end = 20.0
        assert result.segments[0].start_time == 10.0
        assert result.segments[0].end_time == 20.0
        # Second chunk offset is 600.0 -> segment start = 610.0, end = 620.0
        assert result.segments[1].start_time == 610.0
        assert result.segments[1].end_time == 620.0
        # Third chunk offset is 1200.0 -> segment start = 1210.0, end = 1220.0
        assert result.segments[2].start_time == 1210.0
        assert result.segments[2].end_time == 1220.0
        # Total duration preserved
        assert result.total_duration_seconds == 1500.0


def test_groq_whisper_provider_adaptive_chunking_on_413() -> None:
    settings = Settings(
        TRANSCRIPTION_API_KEY="test_groq_key",
        TRANSCRIPTION_MODEL="whisper-large-v3-turbo",
    )
    mock_audio_service = MagicMock()
    mock_audio_service.temporary_scratch_dir.side_effect = tempfile.TemporaryDirectory
    mock_audio_service.compress_to_mp3.side_effect = lambda src, dest, bitrate="64k": (
        Path(dest).write_bytes(b"compressed_data" * 20),
        str(dest),
    )[1]
    mock_audio_service.validate_media_file.return_value = {"duration": 100.0}

    def mock_extract(input_path, output_path, start_seconds, duration_seconds, bitrate="64k"):
        Path(output_path).write_bytes(b"chunk_data" * 5)
        return str(output_path)

    mock_audio_service.extract_audio_segment.side_effect = mock_extract

    provider = GroqWhisperProvider(settings, audio_service=mock_audio_service)
    provider.MAX_GROQ_PAYLOAD_BYTES = 100
    provider.CHUNK_DURATION_SECONDS = 100.0
    provider.MIN_CHUNK_DURATION_SECONDS = 10.0
    provider.CHUNK_OVERLAP_SECONDS = 0.0

    call_durations = []

    def mock_call(path, mime_type, language=None, prompt=None):
        # Fail first call with 413, then succeed on halved duration
        if len(call_durations) == 0:
            call_durations.append(100.0)
            raise TranscriptionProviderError("HTTP 413 Payload Too Large", is_retryable=False)
        call_durations.append(50.0)
        return {
            "text": "Adaptive chunk succeeded",
            "language": "en",
            "duration": 50.0,
            "segments": [
                {
                    "start": 0.0,
                    "end": 20.0,
                    "text": "Adaptive chunk succeeded",
                    "speaker": "SPEAKER_00",
                }
            ],
        }

    provider._call_groq_api = mock_call  # type: ignore[assignment]

    with tempfile.NamedTemporaryFile() as tmp:
        tmp.write(b"0" * 200)
        tmp.flush()

        result = provider.transcribe(tmp.name)
        assert len(result.segments) > 0
        assert "Adaptive chunk succeeded" in result.raw_transcript_text
        # Verified that 413 triggered backoff and retry with smaller chunk
        assert 100.0 in call_durations
        assert 50.0 in call_durations


def test_groq_whisper_provider_overlap_boundary_deduplication() -> None:
    settings = Settings(
        TRANSCRIPTION_API_KEY="test_groq_key",
        TRANSCRIPTION_MODEL="whisper-large-v3-turbo",
    )
    mock_audio_service = MagicMock()
    mock_audio_service.temporary_scratch_dir.side_effect = tempfile.TemporaryDirectory
    mock_audio_service.compress_to_mp3.side_effect = lambda src, dest, bitrate="64k": (
        Path(dest).write_bytes(b"compressed_data" * 20),
        str(dest),
    )[1]
    mock_audio_service.validate_media_file.return_value = {"duration": 100.0}

    def mock_extract(input_path, output_path, start_seconds, duration_seconds, bitrate="64k"):
        Path(output_path).write_bytes(b"chunk_data" * 5)
        return str(output_path)

    mock_audio_service.extract_audio_segment.side_effect = mock_extract

    provider = GroqWhisperProvider(settings, audio_service=mock_audio_service)
    provider.MAX_GROQ_PAYLOAD_BYTES = 100
    provider.CHUNK_DURATION_SECONDS = 50.0
    provider.CHUNK_OVERLAP_SECONDS = 5.0

    call_index = 0

    def mock_call(path, mime_type, language=None, prompt=None):
        nonlocal call_index
        call_index += 1
        if call_index == 1:
            # Chunk 1 (0 to 50s): returns segments from 0 to 49s
            return {
                "text": "Hello world from chunk 1.",
                "duration": 50.0,
                "segments": [
                    {"start": 0.0, "end": 25.0, "text": "Hello world", "speaker": "SPEAKER_00"},
                    {"start": 25.0, "end": 49.0, "text": "from chunk 1.", "speaker": "SPEAKER_00"},
                ],
            }
        else:
            # Chunk 2 (extraction start 45s due to 5s overlap):
            # Groq returns segment in overlap [45-48s] and subsequent segment [52-60s]
            return {
                "text": "from chunk 1. Moving to chunk 2.",
                "duration": 55.0,
                "segments": [
                    {
                        "start": 0.0,
                        "end": 3.0,
                        "text": "from chunk 1.",
                        "speaker": "SPEAKER_00",
                    },  # in overlap (45+0=45s to 45+3=48s <= 50s chunk_start)
                    {
                        "start": 7.0,
                        "end": 15.0,
                        "text": "Moving to chunk 2.",
                        "speaker": "SPEAKER_01",
                    },  # (45+7=52s to 45+15=60s)
                ],
            }

    provider._call_groq_api = mock_call  # type: ignore[assignment]

    with tempfile.NamedTemporaryFile() as tmp:
        tmp.write(b"0" * 200)
        tmp.flush()

        result = provider.transcribe(tmp.name)
        # Should deduplicate the overlapping "from chunk 1."
        texts = [s.text for s in result.segments]
        assert texts == ["Hello world", "from chunk 1.", "Moving to chunk 2."]
        assert len(result.segments) == 3
        # Timestamps are ordered and monotonic
        assert (
            result.segments[0].start_time
            < result.segments[1].start_time
            < result.segments[2].start_time
        )


def test_groq_whisper_provider_413_exhaustion_raises_non_retryable() -> None:
    settings = Settings(
        TRANSCRIPTION_API_KEY="test_groq_key",
        TRANSCRIPTION_MODEL="whisper-large-v3-turbo",
    )
    mock_audio_service = MagicMock()
    mock_audio_service.temporary_scratch_dir.side_effect = tempfile.TemporaryDirectory
    mock_audio_service.compress_to_mp3.side_effect = lambda src, dest, bitrate="64k": (
        Path(dest).write_bytes(b"compressed_data" * 20),
        str(dest),
    )[1]
    mock_audio_service.validate_media_file.return_value = {"duration": 100.0}

    def mock_extract(input_path, output_path, start_seconds, duration_seconds, bitrate="64k"):
        Path(output_path).write_bytes(b"chunk_data" * 5)
        return str(output_path)

    mock_audio_service.extract_audio_segment.side_effect = mock_extract

    provider = GroqWhisperProvider(settings, audio_service=mock_audio_service)
    provider.MAX_GROQ_PAYLOAD_BYTES = 100
    provider.CHUNK_DURATION_SECONDS = 100.0
    provider.MIN_CHUNK_DURATION_SECONDS = 50.0  # Window cannot reduce beyond 50s

    call_count = 0

    def mock_call(path, mime_type, language=None, prompt=None):
        nonlocal call_count
        call_count += 1
        raise TranscriptionProviderError("HTTP 413 Payload Too Large", is_retryable=False)

    provider._call_groq_api = mock_call  # type: ignore[assignment]

    with tempfile.NamedTemporaryFile() as tmp:
        tmp.write(b"0" * 200)
        tmp.flush()

        with pytest.raises(TranscriptionProviderError) as exc_info:
            provider.transcribe(tmp.name)
        assert exc_info.value.is_retryable is False
        assert (
            "413" in exc_info.value.message
            or "Failed to transcribe chunk" in exc_info.value.message
        )


def test_groq_whisper_provider_payload_limit_enforced_strictly() -> None:
    settings = Settings(
        TRANSCRIPTION_API_KEY="test_groq_key",
        TRANSCRIPTION_MODEL="whisper-large-v3-turbo",
    )
    mock_audio_service = MagicMock()
    mock_audio_service.temporary_scratch_dir.side_effect = tempfile.TemporaryDirectory
    mock_audio_service.compress_to_mp3.side_effect = lambda src, dest, bitrate="64k": (
        Path(dest).write_bytes(b"compressed_data" * 20),
        str(dest),
    )[1]
    mock_audio_service.validate_media_file.return_value = {"duration": 100.0}

    # Extract generates oversized file (larger than MAX_GROQ_PAYLOAD_BYTES)
    def mock_extract(input_path, output_path, start_seconds, duration_seconds, bitrate="64k"):
        Path(output_path).write_bytes(b"very_large_chunk_data" * 50)
        return str(output_path)

    mock_audio_service.extract_audio_segment.side_effect = mock_extract

    provider = GroqWhisperProvider(settings, audio_service=mock_audio_service)
    provider.MAX_GROQ_PAYLOAD_BYTES = 50
    provider.CHUNK_DURATION_SECONDS = 60.0
    provider.MIN_CHUNK_DURATION_SECONDS = 60.0  # Cannot reduce

    provider._call_groq_api = MagicMock()

    with tempfile.NamedTemporaryFile() as tmp:
        tmp.write(b"0" * 200)
        tmp.flush()

        with pytest.raises(TranscriptionProviderError) as exc_info:
            provider.transcribe(tmp.name)
        # Asserts that oversized chunk is caught before calling provider API
        assert "exceeds payload limit" in exc_info.value.message
        provider._call_groq_api.assert_not_called()


def test_groq_whisper_provider_speech_boundary_text_matching_deduplication() -> None:
    settings = Settings(
        TRANSCRIPTION_API_KEY="test_groq_key",
        TRANSCRIPTION_MODEL="whisper-large-v3-turbo",
    )
    mock_audio_service = MagicMock()
    mock_audio_service.temporary_scratch_dir.side_effect = tempfile.TemporaryDirectory
    mock_audio_service.compress_to_mp3.side_effect = lambda src, dest, bitrate="64k": (
        Path(dest).write_bytes(b"compressed_data" * 20),
        str(dest),
    )[1]
    mock_audio_service.validate_media_file.return_value = {"duration": 60.0}

    def mock_extract(input_path, output_path, start_seconds, duration_seconds, bitrate="64k"):
        Path(output_path).write_bytes(b"chunk_data" * 5)
        return str(output_path)

    mock_audio_service.extract_audio_segment.side_effect = mock_extract

    provider = GroqWhisperProvider(settings, audio_service=mock_audio_service)
    provider.MAX_GROQ_PAYLOAD_BYTES = 100
    provider.CHUNK_DURATION_SECONDS = 30.0
    provider.CHUNK_OVERLAP_SECONDS = 2.0

    call_index = 0

    def mock_call(path, mime_type, language=None, prompt=None):
        nonlocal call_index
        call_index += 1
        if call_index == 1:
            # Chunk 1 ends with "we discussed the migration plan"
            return {
                "text": "In the meeting we discussed the migration plan",
                "duration": 30.0,
                "segments": [
                    {
                        "start": 0.0,
                        "end": 15.0,
                        "text": "In the meeting",
                        "speaker": "SPEAKER_00",
                    },
                    {
                        "start": 15.0,
                        "end": 29.8,
                        "text": "we discussed the migration plan",
                        "speaker": "SPEAKER_00",
                    },
                ],
            }
        else:
            # Chunk 2 overlaps by 2s (starts at 28s). Groq produces a segment with start=2.5s
            # but its text is identical to end of chunk 1 due to acoustic model overlap.
            return {
                "text": "we discussed the migration plan and approved it",
                "duration": 32.0,
                "segments": [
                    {
                        "start": 2.5,
                        "end": 5.0,
                        "text": "we discussed the migration plan",
                        "speaker": "SPEAKER_00",
                    },
                    {
                        "start": 5.2,
                        "end": 10.0,
                        "text": "and approved it.",
                        "speaker": "SPEAKER_00",
                    },
                ],
            }

    provider._call_groq_api = mock_call  # type: ignore[assignment]

    with tempfile.NamedTemporaryFile() as tmp:
        tmp.write(b"0" * 200)
        tmp.flush()

        result = provider.transcribe(tmp.name)
        texts = [s.text for s in result.segments]
        # Text matching deduplication eliminates the duplicated "we discussed the migration plan"
        assert texts == ["In the meeting", "we discussed the migration plan", "and approved it."]
        assert len(result.segments) == 3
