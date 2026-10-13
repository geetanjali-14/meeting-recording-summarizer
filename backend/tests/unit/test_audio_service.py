import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.services.audio_service import AudioProcessingError, AudioService


def test_validate_media_file_non_existent() -> None:
    service = AudioService()
    with pytest.raises(AudioProcessingError, match="does not exist"):
        service.validate_media_file("/path/that/does/not/exist.mp4")


def test_validate_media_file_empty_file() -> None:
    service = AudioService()
    with tempfile.NamedTemporaryFile() as tmp:
        with pytest.raises(AudioProcessingError, match="empty"):
            service.validate_media_file(tmp.name)


@patch("subprocess.run")
def test_validate_media_file_success(mock_run: MagicMock) -> None:
    service = AudioService()
    with tempfile.NamedTemporaryFile() as tmp:
        tmp.write(b"non-empty")
        tmp.flush()

        mock_run.return_value = MagicMock(
            stdout="codec_type=audio\ncodec_name=aac\nduration=120.5\n",
            returncode=0,
        )

        res = service.validate_media_file(tmp.name)
        assert res["has_audio"] is True
        assert res["duration"] == 120.5


@patch("subprocess.run")
def test_validate_media_file_no_audio_stream(mock_run: MagicMock) -> None:
    service = AudioService()
    with tempfile.NamedTemporaryFile() as tmp:
        tmp.write(b"non-empty")
        tmp.flush()

        mock_run.return_value = MagicMock(
            stdout="codec_type=video\ncodec_name=h264\n",
            returncode=0,
        )

        with pytest.raises(AudioProcessingError, match="No audio stream found"):
            service.validate_media_file(tmp.name)


@patch("subprocess.run")
def test_convert_to_wav_16k_mono_success(mock_run: MagicMock) -> None:
    service = AudioService()
    with tempfile.TemporaryDirectory() as tmpdir:
        input_file = Path(tmpdir) / "input.mp4"
        input_file.write_bytes(b"dummy")
        output_file = Path(tmpdir) / "output.wav"

        # Mock subprocess.run to touch the output file
        def fake_run(*args, **kwargs):
            output_file.write_bytes(b"RIFFwavdata")
            return MagicMock(returncode=0)

        mock_run.side_effect = fake_run

        out = service.convert_to_wav_16k_mono(input_file, output_file)
        assert out == str(output_file)
        assert output_file.exists()


def test_temporary_scratch_dir_cleanup() -> None:
    service = AudioService()
    temp_path: Path | None = None
    with service.temporary_scratch_dir(prefix="test_clean_") as sdir:
        temp_path = sdir
        assert temp_path.exists()
        (temp_path / "scratch_file.wav").write_bytes(b"temporary")

    assert temp_path is not None
    assert not temp_path.exists()
