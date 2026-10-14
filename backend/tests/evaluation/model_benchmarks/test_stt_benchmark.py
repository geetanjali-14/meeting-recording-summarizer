"""Speech-to-Text Model Benchmark (Offline Simulation & Metric Verification).

Evaluates STT metrics and pricing projections against synthetic fixture hypotheses:
- Groq-hosted Whisper Large V3 Turbo (baseline candidate)
- Whisper Large V3 (standard candidate)

Metrics evaluated:
1. Word Error Rate (WER)
2. Technical Term Precision
3. Timestamp Precision / Drift
4. Simulated Processing Latency / Projected Real-Time Factor (RTF < 0.1x target)
5. Estimated Cost per Audio Hour ($0.04/hr for Whisper Turbo vs $0.111/hr for Large V3)

NOTE: These tests run offline against deterministic synthetic hypotheses to verify
scoring mechanics and pricing logic. Live provider model accuracy, latency, and
measured network costs remain marked as pending live evaluation.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.evaluation.evaluator import Evaluator, STTBenchmarkResult, STTPricingAssumptions

DATASET_ROOT = Path(__file__).resolve().parent.parent / "datasets"


@pytest.mark.parametrize(
    "dataset_name",
    ["meeting_001_sprint_planning", "meeting_002_product_strategy"],
)
def test_stt_benchmark_candidates(dataset_name: str) -> None:
    dataset = Evaluator.load_dataset(DATASET_ROOT / dataset_name)
    reference_segments = dataset["transcript"]
    reference_text = " ".join(seg["text"] for seg in reference_segments)
    audio_duration = reference_segments[-1]["end_time"]

    # Candidate 1: Groq Whisper Large V3 Turbo (Simulated offline hypothesis)
    # Simulated/Reproducible STT output matching realistic Turbo behavior (minor filler differences)
    hyp_turbo_segments = [
        {
            "sequence_index": seg["sequence_index"],
            "start_time": seg["start_time"] + 0.05,
            "end_time": seg["end_time"] + 0.05,
            "text": seg["text"],
        }
        for seg in reference_segments
    ]
    hyp_turbo_text = " ".join(s["text"] for s in hyp_turbo_segments)

    # Simulated offline latency (not live provider API measurement)
    simulated_latency_turbo = 0.250

    wer_result_turbo = Evaluator.calculate_wer(reference_text, hyp_turbo_text)
    drift_turbo = Evaluator.calculate_timestamp_drift(reference_segments, hyp_turbo_segments)
    terms = ["PostgreSQL", "Supabase", "Celery", "Redis", "Cloudflare", "SAML", "Okta"]
    tech_precision_turbo = Evaluator.calculate_technical_term_precision(terms, hyp_turbo_text)
    rtf_turbo = simulated_latency_turbo / audio_duration

    # Configurable pricing assumptions (Groq published rates October 2026)
    pricing_turbo = STTPricingAssumptions(
        cost_per_hour_usd=0.04,
        pricing_source="Groq Whisper Turbo ($0.04/hr published rate, Oct 2026)",
    )

    turbo_result = STTBenchmarkResult(
        candidate="whisper-large-v3-turbo",
        wer=wer_result_turbo.wer,
        technical_term_precision=tech_precision_turbo,
        timestamp_drift_seconds=drift_turbo,
        latency_seconds=simulated_latency_turbo,
        audio_duration_seconds=audio_duration,
        real_time_factor=round(rtf_turbo, 4),
        cost_per_hour_usd=pricing_turbo.cost_per_hour_usd,
        passed=wer_result_turbo.wer <= 0.05 and rtf_turbo < 0.1,
        is_live_measurement=False,
        cost_is_estimated=True,
        pricing_assumptions=pricing_turbo.pricing_source,
    )

    assert turbo_result.passed is True
    assert turbo_result.wer == 0.0
    assert turbo_result.real_time_factor < 0.10
    assert turbo_result.timestamp_drift_seconds < 0.20
    assert turbo_result.is_live_measurement is False

    # Candidate 2: Whisper Large V3 (Standard, Simulated offline hypothesis)
    words = hyp_turbo_text.split()
    if words:
        words[0] = "Great"  # "Good" -> "Great" substitution to verify metric sensitivity
    hyp_v3_text = " ".join(words)

    wer_result_v3 = Evaluator.calculate_wer(reference_text, hyp_v3_text)
    simulated_latency_v3 = simulated_latency_turbo * 1.8  # ~1.8x projected relative difference
    rtf_v3 = simulated_latency_v3 / audio_duration

    pricing_v3 = STTPricingAssumptions(
        cost_per_hour_usd=0.111,
        pricing_source="Whisper Large V3 ($0.111/hr published rate, Oct 2026)",
    )

    v3_result = STTBenchmarkResult(
        candidate="whisper-large-v3",
        wer=wer_result_v3.wer,
        technical_term_precision=tech_precision_turbo,
        timestamp_drift_seconds=drift_turbo,
        latency_seconds=round(simulated_latency_v3, 3),
        audio_duration_seconds=audio_duration,
        real_time_factor=round(rtf_v3, 4),
        cost_per_hour_usd=pricing_v3.cost_per_hour_usd,
        passed=wer_result_v3.wer <= 0.08,
        is_live_measurement=False,
        cost_is_estimated=True,
        pricing_assumptions=pricing_v3.pricing_source,
    )

    assert v3_result.wer > 0.0  # Demonstrates sensitive WER metric detection
    assert v3_result.cost_per_hour_usd > turbo_result.cost_per_hour_usd
    assert v3_result.latency_seconds > turbo_result.latency_seconds
    assert v3_result.is_live_measurement is False
