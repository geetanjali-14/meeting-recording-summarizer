import logging

from app.providers.diarization.base import DiarizationTurn
from app.providers.transcription.base import TranscriptSegmentResult

logger = logging.getLogger(__name__)


class AlignmentService:
    """Service that deterministically aligns Whisper transcript segments
    with pyannote speaker turns.

    Uses maximum temporal overlap heuristic:
    For each transcript segment [seg.start_time, seg.end_time], calculates overlap duration
    with all diarization speaker turns [turn.start_time, turn.end_time].
    The speaker label with the maximum total overlap duration is assigned to the segment.
    If no overlap exists, retains the existing speaker label or defaults to 'SPEAKER_00'.
    """

    def align(
        self,
        segments: list[TranscriptSegmentResult],
        turns: list[DiarizationTurn],
        default_speaker_label: str = "SPEAKER_00",
    ) -> list[TranscriptSegmentResult]:
        """Aligns segments with speaker turns in-place or returning updated segments."""
        if not segments:
            return []

        if not turns:
            for seg in segments:
                if not seg.speaker_label:
                    seg.speaker_label = default_speaker_label
            return segments

        for seg in segments:
            seg_start = seg.start_time
            seg_end = seg.end_time

            overlap_by_speaker: dict[str, float] = {}

            for turn in turns:
                overlap_start = max(seg_start, turn.start_time)
                overlap_end = min(seg_end, turn.end_time)

                if overlap_end > overlap_start:
                    duration = overlap_end - overlap_start
                    overlap_by_speaker[turn.speaker_label] = (
                        overlap_by_speaker.get(turn.speaker_label, 0.0) + duration
                    )

            if overlap_by_speaker:
                best_speaker = max(overlap_by_speaker.items(), key=lambda item: item[1])[0]
                seg.speaker_label = best_speaker
            elif not seg.speaker_label:
                seg.speaker_label = default_speaker_label

        return segments
