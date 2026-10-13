import logging
from pathlib import Path
from typing import Any

import httpx

from app.core.config import Settings
from app.providers.transcription.base import (
    TranscriptionProvider,
    TranscriptionProviderError,
    TranscriptionResult,
    TranscriptSegmentResult,
)

logger = logging.getLogger(__name__)


class GroqWhisperProvider(TranscriptionProvider):
    """Groq-hosted Whisper Large V3 Turbo transcription provider via OpenAI-compatible REST API."""

    GROQ_BASE_URL = "https://api.groq.com/openai/v1/audio/transcriptions"

    def __init__(self, settings: Settings) -> None:
        self.api_key = settings.TRANSCRIPTION_API_KEY
        self.model = settings.TRANSCRIPTION_MODEL
        self.timeout_seconds = settings.TRANSCRIPTION_TIMEOUT_SECONDS

    def transcribe(self, audio_file_path: str, language: str | None = None) -> TranscriptionResult:
        path = Path(audio_file_path)
        if not path.exists():
            raise TranscriptionProviderError(
                f"Audio file does not exist: {audio_file_path}", is_retryable=False
            )

        headers = {
            "Authorization": f"Bearer {self.api_key}",
        }

        # Request verbose_json to obtain timestamped segments
        data: dict[str, Any] = {
            "model": self.model,
            "response_format": "verbose_json",
            "temperature": "0.0",
        }
        if language:
            data["language"] = language

        try:
            with open(path, "rb") as f:
                files = {"file": (path.name, f, "audio/wav")}
                with httpx.Client(timeout=self.timeout_seconds) as client:
                    response = client.post(
                        self.GROQ_BASE_URL,
                        headers=headers,
                        data=data,
                        files=files,
                    )

            if response.status_code == 429 or response.status_code >= 500:
                raise TranscriptionProviderError(
                    f"Groq Whisper transient HTTP error {response.status_code}: {response.text}",
                    is_retryable=True,
                )
            if response.status_code != 200:
                raise TranscriptionProviderError(
                    f"Groq Whisper permanent HTTP error {response.status_code}: {response.text}",
                    is_retryable=False,
                )

            payload = response.json()
        except httpx.TimeoutException as exc:
            raise TranscriptionProviderError(
                f"Groq Whisper request timed out: {exc}", is_retryable=True
            ) from exc
        except httpx.NetworkError as exc:
            raise TranscriptionProviderError(
                f"Groq Whisper network error: {exc}", is_retryable=True
            ) from exc
        except TranscriptionProviderError:
            raise
        except Exception as exc:
            raise TranscriptionProviderError(
                f"Groq Whisper unexpected error: {exc}", is_retryable=False
            ) from exc

        # Parse segments
        raw_text = payload.get("text", "")
        detected_language = payload.get("language", language or "en")
        duration = payload.get("duration")

        segments: list[TranscriptSegmentResult] = []
        raw_segments = payload.get("segments", [])
        if not raw_segments and raw_text:
            # Fallback if no segments returned
            segments.append(
                TranscriptSegmentResult(
                    sequence_index=0,
                    start_time=0.0,
                    end_time=float(duration) if duration else 0.0,
                    text=raw_text.strip(),
                    speaker_label="SPEAKER_00",
                )
            )
        else:
            for idx, seg in enumerate(raw_segments):
                segments.append(
                    TranscriptSegmentResult(
                        sequence_index=idx,
                        start_time=float(seg.get("start", 0.0)),
                        end_time=float(seg.get("end", 0.0)),
                        text=seg.get("text", "").strip(),
                        speaker_label=seg.get("speaker", "SPEAKER_00"),
                        confidence=seg.get("avg_logprob"),
                    )
                )

        return TranscriptionResult(
            provider="groq_whisper_turbo",
            model=self.model,
            language=detected_language,
            total_duration_seconds=duration,
            raw_transcript_text=raw_text,
            segments=segments,
        )
