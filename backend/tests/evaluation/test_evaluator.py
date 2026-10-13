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

