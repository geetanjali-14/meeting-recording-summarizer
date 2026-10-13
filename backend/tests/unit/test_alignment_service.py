from app.providers.diarization.base import DiarizationTurn
from app.providers.transcription.base import TranscriptSegmentResult
from app.services.alignment_service import AlignmentService


def test_alignment_service_empty_inputs() -> None:
    aligner = AlignmentService()
    assert aligner.align([], []) == []


def test_alignment_service_no_turns_uses_default() -> None:
    aligner = AlignmentService()
    segments = [
        TranscriptSegmentResult(
            sequence_index=0,
            start_time=0.0,
            end_time=5.0,
            text="Hello world",
            speaker_label=None,
        )
    ]
    aligned = aligner.align(segments, [])
    assert aligned[0].speaker_label == "SPEAKER_00"


def test_alignment_service_exact_and_partial_overlaps() -> None:
    aligner = AlignmentService()
    segments = [
        # Segment 0: 0.0s - 4.0s (0-3s SPEAKER_00, 3-4s SPEAKER_01 -> SPEAKER_00 wins)
        TranscriptSegmentResult(
            sequence_index=0,
            start_time=0.0,
            end_time=4.0,
            text="First speaker introduction.",
        ),
        # Segment 1: 4.0s - 10.0s (Overlaps 4-10s with SPEAKER_01 -> SPEAKER_01 wins)
        TranscriptSegmentResult(
            sequence_index=1,
            start_time=4.0,
            end_time=10.0,
            text="Second speaker response.",
        ),
        # Segment 2: 12.0s - 15.0s (No turns cover this interval -> defaults to SPEAKER_00)
        TranscriptSegmentResult(
            sequence_index=2,
            start_time=12.0,
            end_time=15.0,
            text="Out of bounds comment.",
        ),
    ]

    turns = [
        DiarizationTurn(start_time=0.0, end_time=3.0, speaker_label="SPEAKER_00"),
        DiarizationTurn(start_time=3.0, end_time=11.0, speaker_label="SPEAKER_01"),
    ]

    aligned = aligner.align(segments, turns)
    assert aligned[0].speaker_label == "SPEAKER_00"
    assert aligned[1].speaker_label == "SPEAKER_01"
    assert aligned[2].speaker_label == "SPEAKER_00"


def test_alignment_service_multi_turn_majority_overlap() -> None:
    aligner = AlignmentService()
    # Segment spans 10.0 to 20.0
    # Overlap with SPEAKER_02: 10.0 to 12.0 (2 seconds)
    # Overlap with SPEAKER_03: 12.0 to 18.0 (6 seconds)
    # Overlap with SPEAKER_02: 18.0 to 20.0 (2 seconds)
    # Total SPEAKER_02 = 4s, Total SPEAKER_03 = 6s -> SPEAKER_03 wins
    segment = TranscriptSegmentResult(
        sequence_index=0,
        start_time=10.0,
        end_time=20.0,
        text="Long conversation utterance.",
    )
    turns = [
        DiarizationTurn(start_time=10.0, end_time=12.0, speaker_label="SPEAKER_02"),
        DiarizationTurn(start_time=12.0, end_time=18.0, speaker_label="SPEAKER_03"),
        DiarizationTurn(start_time=18.0, end_time=20.0, speaker_label="SPEAKER_02"),
    ]

    aligned = aligner.align([segment], turns)
    assert aligned[0].speaker_label == "SPEAKER_03"
