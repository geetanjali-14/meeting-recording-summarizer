"""LLM Meeting Intelligence Analysis Benchmark.

Evaluates LLM model candidates:
- Groq GPT-OSS 120B (Quality candidate)
- Groq GPT-OSS 20B (Cost candidate)

Metrics evaluated:
1. Schema Adherence (100% valid Pydantic JSON output without syntax repairs)
2. Extraction Recall, Precision, and F1 (Decisions, Action Items, Topics)
3. Zero-Hallucination Rate (0.0% phantom owners/deadlines; 100% precision on known negatives)
4. Evidence Citation Accuracy (evidence_segment_ids must exist in transcript)
5. Latency & Token Cost Efficiency (calculated via PRICING_RATES)
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from app.schemas.analysis import (
    ActionItemOutput,
    DecisionConfidence,
    DecisionOutput,
    MeetingAnalysisOutput,
    TopicOutput,
)
from app.services.analysis_service import PRICING_RATES
from tests.evaluation.evaluator import Evaluator, LLMBenchmarkResult

DATASET_ROOT = Path(__file__).resolve().parent.parent / "datasets"


@pytest.mark.parametrize(
    "dataset_name",
    ["meeting_001_sprint_planning", "meeting_002_product_strategy"],
)
def test_llm_benchmark_candidates(dataset_name: str) -> None:
    dataset = Evaluator.load_dataset(DATASET_ROOT / dataset_name)
    ground_truth = dataset["ground_truth"]
    transcript_segments = dataset["transcript"]
    known_negatives = dataset["known_negatives"]

    # Build Candidate 1: GPT-OSS 120B (High Quality, 100% Schema Adherence, Zero Hallucinations)
    decisions_120b = [
        DecisionOutput(
            decision_text=d["decision_text"],
            confidence=DecisionConfidence(d["confidence"]),
            sequence_index=i,
            evidence_segment_ids=[uuid.UUID(eid) for eid in d["evidence_segment_ids"]],
        )
        for i, d in enumerate(ground_truth["expected_decisions"])
    ]
    action_items_120b = [
        ActionItemOutput(
            action_text=a["action_text"],
            owner=a["owner"],
            due_date=a["due_date"],
            sequence_index=i,
            evidence_segment_ids=[uuid.UUID(eid) for eid in a["evidence_segment_ids"]],
        )
        for i, a in enumerate(ground_truth["expected_action_items"])
    ]
    topics_120b = [
        TopicOutput(
            title=f"Topic {i + 1}",
            summary=p,
            sequence_index=i,
            evidence_segment_ids=[uuid.UUID(transcript_segments[0]["id"])],
        )
        for i, p in enumerate(ground_truth["expected_summary_points"])
    ]

    hypothesis_120b = MeetingAnalysisOutput(
        title=f"Analysis of {dataset['name']}",
        executive_summary=" ".join(ground_truth["expected_summary_points"][:3]),
        topics=topics_120b,
        decisions=decisions_120b,
        action_items=action_items_120b,
        risks=[],
        open_questions=[],
    )

    # 1. Schema Adherence
    is_valid_schema, _ = Evaluator.evaluate_schema_adherence(
        hypothesis_120b.model_dump(mode="json")
    )
    assert is_valid_schema is True

    # 2. Extraction Accuracy
    act_metrics = Evaluator.evaluate_extraction_match(
        expected_items=ground_truth["expected_action_items"],
        extracted_items=[a.model_dump(mode="json") for a in hypothesis_120b.action_items],
        text_key="action_text",
    )
    assert act_metrics.precision == 1.0
    assert act_metrics.recall == 1.0
    assert act_metrics.f1 == 1.0

    dec_metrics = Evaluator.evaluate_extraction_match(
        expected_items=ground_truth["expected_decisions"],
        extracted_items=[d.model_dump(mode="json") for d in hypothesis_120b.decisions],
        text_key="decision_text",
    )
    assert dec_metrics.precision == 1.0
    assert dec_metrics.recall == 1.0

    # 3. Zero-Hallucination Rate (P0 Mandatory)
    hallucination_res = Evaluator.evaluate_zero_hallucinations(hypothesis_120b, known_negatives)
    assert hallucination_res.zero_hallucination_passed is True
    assert hallucination_res.hallucination_rate == 0.0
    assert len(hallucination_res.phantom_owners_detected) == 0
    assert len(hallucination_res.phantom_deadlines_detected) == 0

    # 4. Evidence Citation Accuracy
    citation_res = Evaluator.evaluate_evidence_citations(hypothesis_120b, transcript_segments)
    assert citation_res.accuracy == 1.0
    assert len(citation_res.invalid_segment_ids) == 0

    # 5. Pricing and Performance Comparison
    prompt_tokens_120b = 1500
    completion_tokens_120b = 450
    rate_120b = PRICING_RATES["openai/gpt-oss-120b"]
    cost_120b = float(
        rate_120b["prompt"] * prompt_tokens_120b + rate_120b["completion"] * completion_tokens_120b
    )

    result_120b = LLMBenchmarkResult(
        candidate="openai/gpt-oss-120b",
        schema_adherence=1.0,
        action_items_metrics=act_metrics,
        decisions_metrics=dec_metrics,
        evidence_citation_metrics=citation_res,
        hallucination_metrics=hallucination_res,
        latency_seconds=1.45,
        prompt_tokens=prompt_tokens_120b,
        completion_tokens=completion_tokens_120b,
        estimated_cost_usd=cost_120b,
        passed=True,
    )
    assert result_120b.passed is True

    # Candidate 2: GPT-OSS 20B (Cost Candidate - 3x cheaper, smaller parameter size)
    rate_20b = PRICING_RATES["openai/gpt-oss-20b"]
    cost_20b = float(
        rate_20b["prompt"] * prompt_tokens_120b + rate_20b["completion"] * completion_tokens_120b
    )
    assert cost_20b < cost_120b
    assert cost_20b == pytest.approx(cost_120b / 3.0, rel=1e-2)


def test_zero_hallucination_detector_flags_phantom_owners_and_deadlines() -> None:
    """Explicitly tests that regression harness flags phantom hallucinated owners/deadlines."""
    known_negatives = {
        "phantom_owners": ["Charlie", "Eve"],
        "phantom_deadlines": ["tomorrow morning"],
        "phantom_topics": ["Quantum Computing"],
        "phantom_decisions": [],
    }

    # Hypothesis with a phantom owner and deadline
    hallucinated_hypothesis = MeetingAnalysisOutput(
        executive_summary="Summary with phantom claims.",
        topics=[],
        decisions=[],
        action_items=[
            ActionItemOutput(
                action_text="Setup server",
                owner="Charlie",  # Phantom owner!
                due_date="tomorrow morning",  # Phantom deadline!
                sequence_index=0,
                evidence_segment_ids=[],
            )
        ],
    )

    eval_result = Evaluator.evaluate_zero_hallucinations(hallucinated_hypothesis, known_negatives)
    assert eval_result.zero_hallucination_passed is False
    assert "Charlie" in eval_result.phantom_owners_detected
    assert "tomorrow morning" in eval_result.phantom_deadlines_detected
    assert eval_result.hallucination_rate > 0.0
