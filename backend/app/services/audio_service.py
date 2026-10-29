import shutil
import subprocess
import tempfile
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any


class AudioProcessingError(Exception):
    """Raised when media validation or FFmpeg extraction fails."""

    pass


class AudioService:
    """Service handling audio/video inspection and FFmpeg normalization to 16 kHz mono WAV."""

    def __init__(self, ffmpeg_bin: str = "ffmpeg", ffprobe_bin: str = "ffprobe") -> None:
        self.ffmpeg_bin = ffmpeg_bin
        self.ffprobe_bin = ffprobe_bin

    def validate_media_file(self, file_path: str | Path) -> dict[str, Any]:
        """Validates that the file exists, is non-empty, and has valid media streams via ffprobe."""
        path = Path(file_path)
        if not path.exists():
            raise AudioProcessingError(f"Media file does not exist: {file_path}")
        if path.stat().st_size == 0:
            raise AudioProcessingError(f"Media file is empty (0 bytes): {file_path}")

        cmd = [
            self.ffprobe_bin,
            "-v",
            "error",
            "-show_entries",
            "format=duration,format_name,size:stream=codec_type,codec_name",
            "-of",
            "default=noprint_wrappers=1",
            str(path),
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        except (subprocess.CalledProcessError, FileNotFoundError) as exc:
            raise AudioProcessingError(f"Media validation failed for {file_path}: {exc}") from exc

        lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        has_audio = any("codec_type=audio" in line for line in lines)
        if not has_audio:
            raise AudioProcessingError(f"No audio stream found in media file: {file_path}")

        duration = None
        for line in lines:
            if line.startswith("duration="):
                try:
                    duration = float(line.split("=")[1])
                except (ValueError, IndexError):
                    pass
        return {"path": str(path), "duration": duration, "has_audio": True}

    def convert_to_wav_16k_mono(self, input_path: str | Path, output_path: str | Path) -> str:
        """Extracts and normalizes media to 16 kHz, single-channel (mono), 16-bit PCM WAV."""
        input_p = Path(input_path)
        output_p = Path(output_path)

        cmd = [
            self.ffmpeg_bin,
            "-y",  # Overwrite output without asking
            "-i",
            str(input_p),
            "-vn",  # Discard video
            "-acodec",
            "pcm_s16le",  # Standard 16-bit PCM
            "-ar",
            "16000",  # 16 kHz sample rate
            "-ac",
            "1",  # Mono channel
            str(output_p),
        ]
        try:
            subprocess.run(cmd, capture_output=True, check=True)
        except subprocess.CalledProcessError as exc:
            stderr = (
                exc.stderr.decode("utf-8", errors="replace")
                if isinstance(exc.stderr, bytes)
                else str(exc.stderr)
            )
            raise AudioProcessingError(f"FFmpeg conversion failed: {stderr}") from exc

        if not output_p.exists() or output_p.stat().st_size == 0:
            raise AudioProcessingError(
                f"FFmpeg produced an empty or missing output file: {output_p}"
            )

        return str(output_p)

    def compress_to_mp3(
        self,
        input_path: str | Path,
        output_path: str | Path,
        bitrate: str = "64k",
    ) -> str:
        """Compresses audio to mono MP3 to drastically reduce payload size for Whisper API."""
        input_p = Path(input_path)
        output_p = Path(output_path)

        cmd = [
            self.ffmpeg_bin,
            "-y",
            "-i",
            str(input_p),
            "-vn",
            "-acodec",
            "libmp3lame",
            "-b:a",
            bitrate,
            "-ar",
            "16000",
            "-ac",
            "1",
            str(output_p),
        ]
        try:
            subprocess.run(cmd, capture_output=True, check=True)
        except subprocess.CalledProcessError as exc:
            stderr = (
                exc.stderr.decode("utf-8", errors="replace")
                if isinstance(exc.stderr, bytes)
                else str(exc.stderr)
            )
            raise AudioProcessingError(f"FFmpeg MP3 compression failed: {stderr}") from exc

        if not output_p.exists() or output_p.stat().st_size == 0:
            raise AudioProcessingError(
                f"FFmpeg produced an empty or missing MP3 output: {output_p}"
            )

        return str(output_p)

    def extract_audio_segment(
        self,
        input_path: str | Path,
        output_path: str | Path,
        start_seconds: float,
        duration_seconds: float,
        bitrate: str = "64k",
    ) -> str:
        """Extracts an audio chunk from start_seconds with given duration to MP3."""
        input_p = Path(input_path)
        output_p = Path(output_path)

        cmd = [
            self.ffmpeg_bin,
            "-y",
            "-ss",
            f"{start_seconds:.3f}",
            "-t",
            f"{duration_seconds:.3f}",
            "-i",
            str(input_p),
            "-vn",
            "-acodec",
            "libmp3lame",
            "-b:a",
            bitrate,
            "-ar",
            "16000",
            "-ac",
            "1",
            str(output_p),
        ]
        try:
            subprocess.run(cmd, capture_output=True, check=True)
        except subprocess.CalledProcessError as exc:
            stderr = (
                exc.stderr.decode("utf-8", errors="replace")
                if isinstance(exc.stderr, bytes)
                else str(exc.stderr)
            )
            raise AudioProcessingError(f"FFmpeg audio segment extraction failed: {stderr}") from exc

        if not output_p.exists() or output_p.stat().st_size == 0:
            raise AudioProcessingError(
                f"FFmpeg produced an empty or missing segment output: {output_p}"
            )

        return str(output_p)

    @contextmanager
    def temporary_scratch_dir(self, prefix: str = "meeting_audio_") -> Generator[Path, None, None]:
        """Provides an isolated temporary scratch directory that is reliably deleted on exit."""
        temp_dir = tempfile.mkdtemp(prefix=prefix)
        try:
            yield Path(temp_dir)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
