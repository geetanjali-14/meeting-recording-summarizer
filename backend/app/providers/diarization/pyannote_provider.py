import logging
from pathlib import Path
from typing import Any

from app.core.config import Settings
from app.providers.diarization.base import (
    DiarizationProvider,
    DiarizationProviderError,
    DiarizationResult,
    DiarizationTurn,
)

logger = logging.getLogger(__name__)


class PyannoteDiarizationProvider(DiarizationProvider):
    """pyannote Community-1 speaker turn diarization provider using HuggingFace model hub."""

    MODEL_ID = "pyannote/speaker-diarization-community-1"

    def __init__(self, settings: Settings) -> None:
        self.hf_token = settings.HF_TOKEN
        self._pipeline: Any = None

    def _get_pipeline(self) -> Any:
        if self._pipeline is not None:
            return self._pipeline

        if not self.hf_token or "placeholder" in self.hf_token.lower():
            raise DiarizationProviderError(
                "Missing or invalid Hugging Face token. "
                "Configure HF_TOKEN in environment to load pyannote model.",
                is_retryable=False,
            )

        try:
            from pyannote.audio import Pipeline  # type: ignore[import-not-found]

            self._pipeline = Pipeline.from_pretrained(
                self.MODEL_ID,
                token=self.hf_token,
            )
            if self._pipeline is None:
                raise DiarizationProviderError(
                    f"Failed to load pipeline for {self.MODEL_ID}. "
                    "Verify model access permissions.",
                    is_retryable=False,
                )
            return self._pipeline
        except DiarizationProviderError:
            raise
        except Exception as exc:
            raise DiarizationProviderError(
                f"Error initializing pyannote pipeline: {exc}",
                is_retryable=False,
            ) from exc

    def diarize(self, audio_file_path: str) -> DiarizationResult:
        path = Path(audio_file_path)
        if not path.exists():
            raise DiarizationProviderError(
                f"Audio file does not exist: {audio_file_path}", is_retryable=False
            )

        pipeline = self._get_pipeline()
        # Load and resample audio via torchaudio/soundfile or Pyannote audio IO
        try:
            import torch
            import torchaudio
            # Pre-load audio to ensure 16kHz mono tensor or pass valid AudioFile dict
            waveform, sample_rate = torchaudio.load(str(path))
            if sample_rate != 16000:
                resampler = torchaudio.transforms.Resample(orig_freq=sample_rate, new_freq=16000)
                waveform = resampler(waveform)
                sample_rate = 16000
            if waveform.shape[0] > 1:
                waveform = torch.mean(waveform, dim=0, keepdim=True)
            audio_input: Any = {"waveform": waveform, "sample_rate": sample_rate}
        except Exception as load_exc:
            logger.debug("Falling back to direct path input for pyannote pipeline: %s", load_exc)
            audio_input = str(path)

        try:
            diarize_output = pipeline(audio_input)
        except Exception as exc:
            raise DiarizationProviderError(
                f"pyannote diarization failed on audio file: {exc}",
                is_retryable=False,
            ) from exc

        annotation = getattr(diarize_output, "speaker_diarization", diarize_output)

        turns: list[DiarizationTurn] = []
        if hasattr(annotation, "itertracks"):
            for segment, _track, speaker_label in annotation.itertracks(yield_label=True):
                turns.append(
                    DiarizationTurn(
                        start_time=float(segment.start),
                        end_time=float(segment.end),
                        speaker_label=str(speaker_label),
                    )
                )

        return DiarizationResult(
            provider="pyannote_community_1",
            turns=turns,
        )
