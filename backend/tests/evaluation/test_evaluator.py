"""Tests for the Evaluator class itself, ensuring deterministic metric computations,
handling edge cases, malformed outputs, missing citations, and zero-hallucination detection.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from app.schemas.analysis import (
    ActionItemOutput,
    MeetingAnalysisOutput,
    TopicOutput,
)
from tests.evaluation.evaluator import Evaluator

DATASET_ROOT = Path(__file__).resolve().parent / "datasets"


def test_evaluator_wer_calculation() -> None:
    # Exact match
    wer_exact = Evaluator.calculate_wer("hello world test", "Hello, World! Test.")
    assert wer_exact.wer == 0.0
    assert wer_exact.substitutions == 0
    assert wer_exact.deletions == 0
    assert wer_exact.insertions == 0

    # Substitution
    wer_sub = Evaluator.calculate_wer("one two three", "one four three")
    assert wer_sub.wer == pytest.approx(1 / 3, rel=1e-3)
    assert wer_sub.substitutions == 1

    # Deletion
    wer_del = Evaluator.calculate_wer("one two three", "one three")
    assert wer_del.wer == pytest.approx(1 / 3, rel=1e-3)
    assert wer_del.deletions == 1

    # Insertion
    wer_ins = Evaluator.calculate_wer("one three", "one two three")
    assert wer_ins.wer == pytest.approx(1 / 2, rel=1e-3)
    assert wer_ins.insertions == 1

    # Empty inputs
    assert Evaluator.calculate_wer("", "").wer == 0.0
    assert Evaluator.calculate_wer("", "something").wer == 1.0


def test_evaluator_technical_term_precision() -> None:
    terms = ["PostgreSQL", "Docker", "Celery", "Redis"]
    text = "We configured PostgreSQL and Redis for background queuing."
    precision = Evaluator.calculate_technical_term_precision(terms, text)
    assert precision == 0.5  # 2 out of 4


def test_evaluator_timestamp_drift() -> None:
    ref = [{"start_time": 1.0, "end_time": 5.0}]
    hyp = [{"start_time": 1.1, "end_time": 5.3}]
    drift = Evaluator.calculate_timestamp_drift(ref, hyp)
    assert drift == pytest.approx(0.2, rel=1e-3)


def test_evaluator_schema_adherence_validation() -> None:
    valid_data = {
        "executive_summary": "Test summary",
        "topics": [],
        "decisions": [],
        "action_items": [],
        "risks": [],
        "open_questions": [],
    }
    is_valid, obj = Evaluator.evaluate_schema_adherence(valid_data)
    assert is_valid is True
    assert obj is not None

    invalid_data = {
        "executive_summary": None,  # Should be string
        "topics": "not-a-list",
    }
    is_valid, obj = Evaluator.evaluate_schema_adherence(invalid_data)
    assert is_valid is False
    assert obj is None


def test_evaluator_evidence_citation_validation() -> None:
    valid_seg_id = uuid.uuid4()
    invalid_seg_id = uuid.uuid4()

    transcript_segments = [{"id": str(valid_seg_id)}]

    hypothesis = MeetingAnalysisOutput(
        executive_summary="Summary",
        topics=[
            TopicOutput(
                title="Topic 1",
                summary="Sum 1",
                sequence_index=0,
                evidence_segment_ids=[valid_seg_id],
            )
        ],
        action_items=[
            ActionItemOutput(
                action_text="Action 1",
                sequence_index=0,
                evidence_segment_ids=[invalid_seg_id],  # Phantom citation
            )
        ],
    )

    result = Evaluator.evaluate_evidence_citations(hypothesis, transcript_segments)
    assert result.total_citations == 2
    assert result.valid_citations == 1
    assert result.accuracy == 0.5
    assert str(invalid_seg_id) in result.invalid_segment_ids


def test_dataset_loader_loads_all_fields() -> None:
    ds = Evaluator.load_dataset(DATASET_ROOT / "meeting_001_sprint_planning")
    assert ds["name"] == "meeting_001_sprint_planning"
    assert len(ds["transcript"]) > 0
    assert "expected_action_items" in ds["ground_truth"]
    assert len(ds["diarization_truth"]) > 0
    assert "phantom_owners" in ds["known_negatives"]


def test_evaluator_hand_calculated_der_scenarios() -> None:
    """Verifies DER calculation against hand-calculated ground-truth scenarios."""
    ref_turns = [
        {"start_time": 0.0, "end_time": 2.0, "speaker_label": "SPEAKER_00"},
        {"start_time": 2.0, "end_time": 4.0, "speaker_label": "SPEAKER_01"},
    ]

    # Scenario 1: Perfect match -> DER = 0.0
    hyp_perf = [
        {"start_time": 0.0, "end_time": 2.0, "speaker_label": "SPEAKER_00"},
        {"start_time": 2.0, "end_time": 4.0, "speaker_label": "SPEAKER_01"},
    ]
    res_perf = Evaluator.calculate_der(ref_turns, hyp_perf, step_seconds=0.1)
    assert res_perf.der == 0.0
    assert res_perf.missed_speech_rate == 0.0
    assert res_perf.false_alarm_rate == 0.0
    assert res_perf.speaker_confusion_rate == 0.0

    # Scenario 2: Complete missed speech on turn 2 (2.0s out of 4.0s missed) -> DER = 0.50
    hyp_miss = [{"start_time": 0.0, "end_time": 2.0, "speaker_label": "SPEAKER_00"}]
    res_miss = Evaluator.calculate_der(ref_turns, hyp_miss, step_seconds=0.1)
    assert res_miss.missed_speech_rate == pytest.approx(0.50, rel=1e-2)
    assert res_miss.der == pytest.approx(0.50, rel=1e-2)

    # Scenario 3: False alarm of 1.0s over a 4.0s reference session -> DER = 0.25
    hyp_fa = [
        {"start_time": 0.0, "end_time": 2.0, "speaker_label": "SPEAKER_00"},
        {"start_time": 2.0, "end_time": 4.0, "speaker_label": "SPEAKER_01"},
        {"start_time": 4.0, "end_time": 5.0, "speaker_label": "SPEAKER_01"},  # 1s false alarm
    ]
    res_fa = Evaluator.calculate_der(ref_turns, hyp_fa, step_seconds=0.1)
    assert res_fa.false_alarm_rate == pytest.approx(0.25, rel=1e-2)
    assert res_fa.der == pytest.approx(0.25, rel=1e-2)


def test_evaluator_hand_calculated_extraction_metrics() -> None:
    """Verifies extraction precision, recall, and F1 against hand-calculated values.

    Expected: 4 items (A, B, C, D)
    Extracted: 3 items (A, B, X) -> Matched: 2 (A, B)
    Precision = 2 / 3 = ~0.6667
    Recall = 2 / 4 = 0.5000
    F1 = 2 * (2/3 * 1/2) / (2/3 + 1/2) = (2/3) / (7/6) = 4/7 = ~0.5714
    """
    expected = [
        {"action_text": "Configure database pooling connection strings"},
        {"action_text": "Implement Celery Redis rate limiting decorator"},
        {"action_text": "Deploy staging cluster to Fly.io"},
        {"action_text": "Audit Cloudflare R2 bucket credentials"},
    ]
    extracted = [
        {"action_text": "Configure database pooling connection strings"},
        {"action_text": "Implement Celery Redis rate limiting decorator"},
        {"action_text": "Unrelated extraneous task entirely absent from meeting"},
    ]
    metrics = Evaluator.evaluate_extraction_match(expected, extracted, text_key="action_text")
    assert metrics.matched_count == 2
    assert metrics.reference_count == 4
    assert metrics.hypothesis_count == 3
    assert metrics.precision == pytest.approx(2 / 3, rel=1e-3)
    assert metrics.recall == pytest.approx(0.5, rel=1e-3)
    assert metrics.f1 == pytest.approx(4 / 7, rel=1e-3)


def test_evaluator_hand_calculated_cost_calculations() -> None:
    """Verifies STT and LLM cost calculations against hand-calculated values."""
    # STT: 1800s (0.5 hours) at $0.04/hr -> $0.020000
    stt_cost = Evaluator.calculate_stt_cost(audio_duration_seconds=1800.0, cost_per_hour_usd=0.04)
    assert stt_cost == 0.02

    # LLM: 10,000 prompt tokens @ $0.15/1M ($0.00000015/tok) = $0.0015
    #      2,000 completion tokens @ $0.60/1M ($0.00000060/tok) = $0.0012
    # Total = $0.0027
    llm_cost = Evaluator.calculate_llm_cost(
        prompt_tokens=10000,
        completion_tokens=2000,
        prompt_rate_per_token=0.00000015,
        completion_rate_per_token=0.00000060,
    )
    assert llm_cost == pytest.approx(0.0027, rel=1e-4)
