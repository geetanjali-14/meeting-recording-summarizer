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

    MAX_GROQ_PAYLOAD_BYTES = 20 * 1024 * 1024  # 20MB threshold with headroom (Groq limit is 25MB)
    CHUNK_DURATION_SECONDS = 300.0  # 5 minute chunks default
    MIN_CHUNK_DURATION_SECONDS = 30.0  # Safe lower bound for adaptive splits
    CHUNK_OVERLAP_SECONDS = 2.0  # Overlap between consecutive chunks to avoid cutting words

    def __init__(self, settings: Settings, audio_service: Any = None) -> None:
        self.api_key = settings.TRANSCRIPTION_API_KEY
        self.model = settings.TRANSCRIPTION_MODEL
        self.timeout_seconds = settings.TRANSCRIPTION_TIMEOUT_SECONDS
        if audio_service is None:
            from app.services.audio_service import AudioService

            self.audio_service = AudioService()
        else:
            self.audio_service = audio_service

    def _call_groq_api(
        self,
        path: Path,
        mime_type: str,
        language: str | None = None,
        prompt: str | None = None,
    ) -> dict[str, Any]:
        """Performs a single HTTP POST to Groq Whisper API for an audio file."""
        file_size = path.stat().st_size
        if file_size > 25 * 1024 * 1024:
            logger.warning(
                "Audio file %s exceeds 25MB Groq Whisper limit (%d bytes)",
                path.name,
                file_size,
            )

        headers = {
            "Authorization": f"Bearer {self.api_key}",
        }
        data: dict[str, Any] = {
            "model": self.model,
            "response_format": "verbose_json",
            "temperature": "0.0",
        }
        if language:
            data["language"] = language
        if prompt:
            data["prompt"] = prompt

        try:
            with open(path, "rb") as f:
                files = {"file": (path.name, f, mime_type)}
                with httpx.Client(timeout=self.timeout_seconds) as client:
                    response = client.post(
                        self.GROQ_BASE_URL,
                        headers=headers,
                        data=data,
                        files=files,
                    )

            if response.status_code == 413:
                raise TranscriptionProviderError(
                    f"Groq Whisper permanent HTTP error 413: "
                    f"Payload Too Large ({file_size} bytes): {response.text}",
                    is_retryable=False,
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
            if isinstance(payload, dict):
                return payload
            return {"text": str(payload)}
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

    def transcribe(self, audio_file_path: str, language: str | None = None) -> TranscriptionResult:
        path = Path(audio_file_path)
        if not path.exists():
            raise TranscriptionProviderError(
                f"Audio file does not exist: {audio_file_path}", is_retryable=False
            )

        if not self.api_key or "placeholder" in self.api_key.lower():
            raise TranscriptionProviderError(
                "Missing or invalid Groq transcription API key. "
                "Configure TRANSCRIPTION_API_KEY in environment.",
                is_retryable=False,
            )

        file_size = path.stat().st_size
        mime_type = "audio/wav" if path.suffix.lower() == ".wav" else "audio/mpeg"

        # If input is already within payload limit, try direct transcription first
        if file_size <= self.MAX_GROQ_PAYLOAD_BYTES:
            try:
                payload = self._call_groq_api(path, mime_type, language)
                return self._parse_payload(payload, language)
            except TranscriptionProviderError as exc:
                if "413" not in str(exc.message):
                    raise
                logger.info(
                    "Direct transcription received 413 despite file size %d. "
                    "Attempting compression.",
                    file_size,
                )

        # File exceeds payload size or received 413: compress to MP3 and/or chunk
        with self.audio_service.temporary_scratch_dir(prefix="groq_whisper_prep_") as temp_dir:
            temp_path = Path(temp_dir)
            mp3_path = temp_path / "compressed_audio.mp3"
            try:
                self.audio_service.compress_to_mp3(path, mp3_path, bitrate="64k")
            except Exception as exc:
                raise TranscriptionProviderError(
                    f"Failed to compress audio for Groq Whisper: {exc}",
                    is_retryable=False,
                ) from exc

            mp3_size = mp3_path.stat().st_size
            if mp3_size <= self.MAX_GROQ_PAYLOAD_BYTES:
                try:
                    payload = self._call_groq_api(mp3_path, "audio/mpeg", language)
                    return self._parse_payload(payload, language)
                except TranscriptionProviderError as exc:
                    if "413" not in str(exc.message):
                        raise
                    logger.info("Compressed MP3 received 413 (%d bytes). Chunking.", mp3_size)

            # If compressed MP3 is still > 20MB or received 413, chunk the audio adaptively
            try:
                media_info = self.audio_service.validate_media_file(mp3_path)
                total_duration = media_info.get("duration") or 0.0
            except Exception as exc:
                raise TranscriptionProviderError(
                    f"Failed to inspect compressed audio duration: {exc}",
                    is_retryable=False,
                ) from exc

            if total_duration <= 0:
                raise TranscriptionProviderError(
                    "Cannot chunk audio file with unknown or zero duration",
                    is_retryable=False,
                )

            all_segments: list[TranscriptSegmentResult] = []
            all_texts: list[str] = []
            detected_language = language or "en"
            chunk_start = 0.0
            chunk_idx = 0
            current_duration_window = self.CHUNK_DURATION_SECONDS

            while chunk_start < total_duration:
                # Try chunk with current_duration_window, adapting down on HTTP 413
                success = False
                attempt = 0
                max_chunk_attempts = 4

                while not success and attempt < max_chunk_attempts:
                    attempt += 1
                    target_duration = min(current_duration_window, total_duration - chunk_start)
                    chunk_path = temp_path / f"chunk_{chunk_idx}_att{attempt}.mp3"

                    # If not first chunk and overlap is configured, include overlap
                    overlap = self.CHUNK_OVERLAP_SECONDS if chunk_start > 0 else 0.0
                    extraction_start = max(0.0, chunk_start - overlap)
                    extraction_duration = target_duration + (chunk_start - extraction_start)

                    self.audio_service.extract_audio_segment(
                        input_path=mp3_path,
                        output_path=chunk_path,
                        start_seconds=extraction_start,
                        duration_seconds=extraction_duration,
                        bitrate="64k",
                    )

                    chunk_size = chunk_path.stat().st_size
                    # Enforce safe payload size before calling provider
                    if chunk_size > self.MAX_GROQ_PAYLOAD_BYTES:
                        if current_duration_window > self.MIN_CHUNK_DURATION_SECONDS:
                            current_duration_window = max(
                                self.MIN_CHUNK_DURATION_SECONDS, current_duration_window / 2.0
                            )
                            logger.info(
                                "Chunk %d payload %d bytes exceeds limit. "
                                "Halving duration window to %.1fs",
                                chunk_idx,
                                chunk_size,
                                current_duration_window,
                            )
                            continue
                        else:
                            raise TranscriptionProviderError(
                                f"Audio chunk {chunk_idx} exceeds payload limit "
                                f"({chunk_size} bytes) even at minimum duration",
                                is_retryable=False,
                            )

                    try:
                        chunk_payload = self._call_groq_api(
                            chunk_path,
                            "audio/mpeg",
                            language=language,
                        )
                        chunk_result = self._parse_payload(
                            chunk_payload,
                            language=language,
                            time_offset_seconds=extraction_start,
                            sequence_offset=len(all_segments),
                        )

                        # Filter out segments before chunk_start to deduplicate overlap speech
                        filtered_segments: list[TranscriptSegmentResult] = []
                        last_end_time = all_segments[-1].end_time if all_segments else 0.0

                        for seg in chunk_result.segments:
                            # If segment finishes before chunk_start threshold, already transcribed
                            if seg.end_time <= chunk_start:
                                continue

                            # Check for overlap with trailing segment of previous chunks
                            seg_text = seg.text.strip().lower()
                            if all_segments and not filtered_segments:
                                prev_text = all_segments[-1].text.strip().lower()
                                # If exact duplicate sentence or significant suffix/prefix match
                                if seg_text == prev_text or (
                                    prev_text and prev_text.endswith(seg_text)
                                ):
                                    continue
                                # If segment text starts with previous text suffix due to split
                                words_prev = prev_text.split()
                                words_cur = seg_text.split()
                                if (
                                    words_prev
                                    and words_cur
                                    and words_prev[-1] == words_cur[0]
                                    and len(words_cur) == 1
                                ):
                                    continue

                            # Ensure segment start is monotonic and not backwards overlapping
                            adjusted_start = max(seg.start_time, last_end_time)
                            adjusted_end = max(seg.end_time, adjusted_start + 0.01)
                            seg.start_time = round(adjusted_start, 3)
                            seg.end_time = round(adjusted_end, 3)
                            seg.sequence_index = len(all_segments) + len(filtered_segments)
                            filtered_segments.append(seg)
                            last_end_time = seg.end_time

                        for s in filtered_segments:
                            if s.text.strip():
                                all_texts.append(s.text.strip())
                        all_segments.extend(filtered_segments)

                        if chunk_result.language:
                            detected_language = chunk_result.language

                        chunk_start += target_duration
                        chunk_idx += 1
                        success = True

                    except TranscriptionProviderError as exc:
                        can_shrink = (
                            "413" in str(exc.message)
                            and current_duration_window > self.MIN_CHUNK_DURATION_SECONDS
                        )
                        if can_shrink:
                            current_duration_window = max(
                                self.MIN_CHUNK_DURATION_SECONDS, current_duration_window / 2.0
                            )
                            logger.warning(
                                "HTTP 413 received for chunk %d. "
                                "Reduced duration window to %.1fs. Retrying.",
                                chunk_idx,
                                current_duration_window,
                            )
                        elif exc.is_retryable and attempt < max_chunk_attempts:
                            logger.warning(
                                "Transient error on chunk %d attempt %d: %s. Retrying.",
                                chunk_idx,
                                attempt,
                                exc.message,
                            )
                        else:
                            raise

                if not success:
                    raise TranscriptionProviderError(
                        f"Failed to transcribe chunk {chunk_idx} after "
                        f"{max_chunk_attempts} attempts",
                        is_retryable=False,
                    )

            # Re-index sequences deterministically
            for idx, s in enumerate(all_segments):
                s.sequence_index = idx

            return TranscriptionResult(
                provider="groq_whisper_turbo",
                model=self.model,
                language=detected_language,
                total_duration_seconds=total_duration,
                raw_transcript_text=" ".join(all_texts),
                segments=all_segments,
            )

    def _parse_payload(
        self,
        payload: dict[str, Any],
        language: str | None = None,
        time_offset_seconds: float = 0.0,
        sequence_offset: int = 0,
    ) -> TranscriptionResult:
        """Parses Groq verbose_json response with optional timestamp offsets."""
        raw_text = payload.get("text", "")
        detected_language = payload.get("language", language or "en")
        duration = payload.get("duration")

        segments: list[TranscriptSegmentResult] = []
        raw_segments = payload.get("segments", [])
        if not raw_segments and raw_text and raw_text.strip():
            segments.append(
                TranscriptSegmentResult(
                    sequence_index=sequence_offset,
                    start_time=time_offset_seconds,
                    end_time=time_offset_seconds + (float(duration) if duration else 0.0),
                    text=raw_text.strip(),
                    speaker_label="SPEAKER_00",
                )
            )
        elif raw_segments:
            for idx, seg in enumerate(raw_segments):
                seg_text = seg.get("text", "").strip()
                if not seg_text:
                    continue
                segments.append(
                    TranscriptSegmentResult(
                        sequence_index=sequence_offset + idx,
                        start_time=round(time_offset_seconds + float(seg.get("start", 0.0)), 3),
                        end_time=round(time_offset_seconds + float(seg.get("end", 0.0)), 3),
                        text=seg_text,
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
