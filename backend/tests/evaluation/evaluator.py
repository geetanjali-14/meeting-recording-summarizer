"""AI & Model Evaluation Suite Evaluator.

Provides deterministic metrics scoring:
- Transcription: WER, Technical Term Precision, Drift, RTF, Cost per Hour.
- Diarization: DER, Speaker Count Accuracy, Segment Alignment Overlap.
- Meeting Intelligence / LLM: Schema Adherence, Precision/Recall/F1,
  Zero-Hallucination Rate, Evidence Citation Accuracy, Cost and Latency.
"""

from __future__ import annotations

import difflib
import json
import logging
import re
import uuid
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from app.schemas.analysis import MeetingAnalysisOutput

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# DTOs and Result Containers
# ---------------------------------------------------------------------------


class STTPricingAssumptions(BaseModel):
    cost_per_hour_usd: float = 0.04
    pricing_source: str = "Groq published rates (October 2026)"


class LLMPricingAssumptions(BaseModel):
    prompt_rate_per_token: float
    completion_rate_per_token: float
    pricing_version: str = "2026-10-v1"


class WERMetrics(BaseModel):
    wer: float
    substitutions: int
    deletions: int
    insertions: int
    reference_words: int
    hypothesis_words: int


class STTBenchmarkResult(BaseModel):
    candidate: str
    wer: float
    technical_term_precision: float
    timestamp_drift_seconds: float
    latency_seconds: float
    audio_duration_seconds: float
    real_time_factor: float
    cost_per_hour_usd: float
    passed: bool
    is_live_measurement: bool = False
    cost_is_estimated: bool = True
    pricing_assumptions: str = "Groq published rates (October 2026)"


class DiarizationBenchmarkResult(BaseModel):
    candidate: str
    der: float
    missed_speech_rate: float
    false_alarm_rate: float
    speaker_confusion_rate: float
    reference_speakers: int
    hypothesis_speakers: int
    speaker_count_accuracy: float
    whisper_alignment_overlap: float
    passed: bool
    is_live_measurement: bool = False


class ExtractionMetrics(BaseModel):
    precision: float
    recall: float
    f1: float
    matched_count: int
    reference_count: int
    hypothesis_count: int


class HallucinationEvaluation(BaseModel):
    zero_hallucination_passed: bool
    phantom_owners_detected: list[str] = Field(default_factory=list)
    phantom_deadlines_detected: list[str] = Field(default_factory=list)
    phantom_topics_detected: list[str] = Field(default_factory=list)
    phantom_decisions_detected: list[str] = Field(default_factory=list)
    hallucination_rate: float  # 0.0 means 0 phantom claims (100% precision)


class EvidenceCitationMetrics(BaseModel):
    total_citations: int
    valid_citations: int
    accuracy: float
    invalid_segment_ids: list[str] = Field(default_factory=list)


class LLMBenchmarkResult(BaseModel):
    candidate: str
    schema_adherence: float  # 1.0 (100%) or 0.0
    action_items_metrics: ExtractionMetrics
    decisions_metrics: ExtractionMetrics
    evidence_citation_metrics: EvidenceCitationMetrics
    hallucination_metrics: HallucinationEvaluation
    latency_seconds: float
    prompt_tokens: int
    completion_tokens: int
    estimated_cost_usd: float
    passed: bool
    is_live_measurement: bool = False
    cost_is_estimated: bool = True
    pricing_assumptions: str = "PRICING_RATES 2026-10-v1"


# ---------------------------------------------------------------------------
# Evaluator Engine
# ---------------------------------------------------------------------------


class Evaluator:
    """Evaluates transcription, diarization, and LLM analysis against ground truth."""

    # -----------------------------------------------------------------------
    # 1. STT / Transcription Metrics
    # -----------------------------------------------------------------------

    @staticmethod
    def normalize_text(text: str) -> str:
        """Lowercases text, strips punctuation, and normalizes whitespaces."""
        if not text:
            return ""
        text = text.lower()
        text = re.sub(r"[^\w\s]", "", text)
        return " ".join(text.split())

    @classmethod
    def calculate_wer(cls, reference: str, hypothesis: str) -> WERMetrics:
        """Calculates standard Word Error Rate (WER) using Levenshtein distance on words.

        WER = (Substitutions + Deletions + Insertions) / Total Reference Words.
        """
        ref_words = cls.normalize_text(reference).split()
        hyp_words = cls.normalize_text(hypothesis).split()

        r_len = len(ref_words)
        h_len = len(hyp_words)

        if r_len == 0:
            if h_len == 0:
                return WERMetrics(
                    wer=0.0,
                    substitutions=0,
                    deletions=0,
                    insertions=0,
                    reference_words=0,
                    hypothesis_words=0,
                )
            return WERMetrics(
                wer=1.0,
                substitutions=0,
                deletions=0,
                insertions=h_len,
                reference_words=0,
                hypothesis_words=h_len,
            )

        # Dynamic programming matrix
        dp = [[0] * (h_len + 1) for _ in range(r_len + 1)]
        for i in range(r_len + 1):
            dp[i][0] = i
        for j in range(h_len + 1):
            dp[0][j] = j

        for i in range(1, r_len + 1):
            for j in range(1, h_len + 1):
                if ref_words[i - 1] == hyp_words[j - 1]:
                    dp[i][j] = dp[i - 1][j - 1]
                else:
                    dp[i][j] = min(
                        dp[i - 1][j] + 1,  # deletion
                        dp[i][j - 1] + 1,  # insertion
                        dp[i - 1][j - 1] + 1,  # substitution
                    )

        # Traceback to count individual error types
        i, j = r_len, h_len
        subs = dels = inss = 0
        while i > 0 or j > 0:
            if i > 0 and j > 0 and ref_words[i - 1] == hyp_words[j - 1]:
                i -= 1
                j -= 1
            elif i > 0 and j > 0 and dp[i][j] == dp[i - 1][j - 1] + 1:
                subs += 1
                i -= 1
                j -= 1
            elif i > 0 and dp[i][j] == dp[i - 1][j] + 1:
                dels += 1
                i -= 1
            elif j > 0 and dp[i][j] == dp[i][j - 1] + 1:
                inss += 1
                j -= 1
            else:
                break

        wer = (subs + dels + inss) / float(r_len)
        return WERMetrics(
            wer=round(wer, 4),
            substitutions=subs,
            deletions=dels,
            insertions=inss,
            reference_words=r_len,
            hypothesis_words=h_len,
        )

    @classmethod
    def calculate_technical_term_precision(
        cls, expected_terms: list[str], hypothesis_text: str
    ) -> float:
        """Measures whether required technical terminology is present in hypothesis."""
        if not expected_terms:
            return 1.0
        norm_text = cls.normalize_text(hypothesis_text)
        found = 0
        for term in expected_terms:
            norm_term = cls.normalize_text(term)
            if norm_term in norm_text:
                found += 1
        return round(found / len(expected_terms), 4)

    @classmethod
    def calculate_timestamp_drift(
        cls,
        reference_segments: list[dict[str, Any]],
        hypothesis_segments: list[dict[str, Any]],
    ) -> float:
        """Calculates mean absolute drift (in seconds) between
        reference and hypothesis boundaries.
        """
        if not reference_segments or not hypothesis_segments:
            return 0.0
        pair_count = min(len(reference_segments), len(hypothesis_segments))
        drifts: list[float] = []
        for i in range(pair_count):
            ref = reference_segments[i]
            hyp = hypothesis_segments[i]
            drift_start = abs(ref["start_time"] - hyp["start_time"])
            drift_end = abs(ref["end_time"] - hyp["end_time"])
            drifts.append((drift_start + drift_end) / 2.0)
        return round(sum(drifts) / len(drifts), 4)

    # -----------------------------------------------------------------------
    # 2. Diarization Metrics
    # -----------------------------------------------------------------------

    @classmethod
    def calculate_der(
        cls,
        reference_turns: list[dict[str, Any]],
        hypothesis_turns: list[dict[str, Any]],
        step_seconds: float = 0.1,
    ) -> DiarizationBenchmarkResult:
        """Calculates Diarization Error Rate (DER) via time-grid discretization.

        DER = (Missed Speech + False Alarm + Speaker Confusion) / Total Reference Speech Time.
        """
        if not reference_turns:
            return DiarizationBenchmarkResult(
                candidate="diarization",
                der=0.0,
                missed_speech_rate=0.0,
                false_alarm_rate=0.0,
                speaker_confusion_rate=0.0,
                reference_speakers=0,
                hypothesis_speakers=0,
                speaker_count_accuracy=1.0,
                whisper_alignment_overlap=1.0,
                passed=True,
            )

        ref_speakers = {t["speaker_label"] for t in reference_turns}
        hyp_speakers = {t["speaker_label"] for t in hypothesis_turns}

        max_time = max(
            max((t["end_time"] for t in reference_turns), default=0.0),
            max((t["end_time"] for t in hypothesis_turns), default=0.0),
        )

        steps = int(max_time / step_seconds) + 1
        ref_grid: list[set[str]] = [set() for _ in range(steps)]
        hyp_grid: list[set[str]] = [set() for _ in range(steps)]

        for turn in reference_turns:
            start_idx = int(turn["start_time"] / step_seconds)
            end_idx = min(int(turn["end_time"] / step_seconds), steps)
            for s in range(start_idx, end_idx):
                ref_grid[s].add(turn["speaker_label"])

        for turn in hypothesis_turns:
            start_idx = int(turn["start_time"] / step_seconds)
            end_idx = min(int(turn["end_time"] / step_seconds), steps)
            for s in range(start_idx, end_idx):
                hyp_grid[s].add(turn["speaker_label"])

        # Optimal mapping between hypothesis labels and reference labels
        co_occurrence: dict[tuple[str, str], int] = {}
        for r_set, h_set in zip(ref_grid, hyp_grid, strict=False):
            for r in r_set:
                for h in h_set:
                    co_occurrence[(h, r)] = co_occurrence.get((h, r), 0) + 1

        label_map: dict[str, str] = {}
        sorted_pairs = sorted(co_occurrence.items(), key=lambda kv: kv[1], reverse=True)
        assigned_hyp = set()
        assigned_ref = set()
        for (h, r), _ in sorted_pairs:
            if h not in assigned_hyp and r not in assigned_ref:
                label_map[h] = r
                assigned_hyp.add(h)
                assigned_ref.add(r)

        total_ref_time = 0.0
        missed_speech_time = 0.0
        false_alarm_time = 0.0
        speaker_confusion_time = 0.0
        overlap_matches = 0
        total_eval_points = 0

        for r_set, h_set in zip(ref_grid, hyp_grid, strict=False):
            r_active = len(r_set) > 0
            h_active = len(h_set) > 0

            if r_active:
                total_ref_time += step_seconds

            if r_active and not h_active:
                missed_speech_time += step_seconds
            elif not r_active and h_active:
                false_alarm_time += step_seconds
            elif r_active and h_active:
                mapped_h_set = {label_map.get(h, h) for h in h_set}
                if mapped_h_set == r_set:
                    overlap_matches += 1
                else:
                    speaker_confusion_time += step_seconds
                total_eval_points += 1

        if total_ref_time == 0.0:
            der = 0.0
            missed_rate = false_alarm_rate = confusion_rate = 0.0
        else:
            missed_rate = missed_speech_time / total_ref_time
            false_alarm_rate = false_alarm_time / total_ref_time
            confusion_rate = speaker_confusion_time / total_ref_time
            der = (missed_speech_time + false_alarm_time + speaker_confusion_time) / total_ref_time

        ref_count = len(ref_speakers)
        hyp_count = len(hyp_speakers)
        speaker_count_acc = 1.0 - (abs(ref_count - hyp_count) / max(ref_count, 1))

        alignment_overlap = (
            overlap_matches / float(total_eval_points) if total_eval_points > 0 else 1.0
        )

        return DiarizationBenchmarkResult(
            candidate="diarization_eval",
            der=round(der, 4),
            missed_speech_rate=round(missed_rate, 4),
            false_alarm_rate=round(false_alarm_rate, 4),
            speaker_confusion_rate=round(confusion_rate, 4),
            reference_speakers=ref_count,
            hypothesis_speakers=hyp_count,
            speaker_count_accuracy=round(speaker_count_acc, 4),
            whisper_alignment_overlap=round(alignment_overlap, 4),
            passed=der <= 0.20,
        )

    # -----------------------------------------------------------------------
    # 3. Meeting Intelligence / LLM Metrics
    # -----------------------------------------------------------------------

    @classmethod
    def evaluate_schema_adherence(
        cls, raw_json_payload: dict[str, Any]
    ) -> tuple[bool, MeetingAnalysisOutput | None]:
        """Validates adherence to Pydantic MeetingAnalysisOutput schema without syntax repairs."""
        try:
            validated = MeetingAnalysisOutput.model_validate(raw_json_payload)
            return True, validated
        except (ValidationError, Exception) as exc:
            logger.info("Schema adherence validation failed: %s", exc)
            return False, None

    @classmethod
    def evaluate_extraction_match(
        cls,
        expected_items: list[dict[str, Any]],
        extracted_items: list[dict[str, Any]],
        text_key: str = "action_text",
        threshold: float = 0.55,
    ) -> ExtractionMetrics:
        """Calculates Precision, Recall, and F1 between ground truth and extracted lists."""
        ref_count = len(expected_items)
        hyp_count = len(extracted_items)

        if ref_count == 0 and hyp_count == 0:
            return ExtractionMetrics(
                precision=1.0,
                recall=1.0,
                f1=1.0,
                matched_count=0,
                reference_count=0,
                hypothesis_count=0,
            )

        if ref_count == 0 or hyp_count == 0:
            return ExtractionMetrics(
                precision=0.0,
                recall=0.0,
                f1=0.0,
                matched_count=0,
                reference_count=ref_count,
                hypothesis_count=hyp_count,
            )

        matched_hyp = set()
        matched_ref = set()

        for r_idx, ref in enumerate(expected_items):
            ref_text = cls.normalize_text(str(ref.get(text_key, "")))
            for h_idx, hyp in enumerate(extracted_items):
                if h_idx in matched_hyp:
                    continue
                hyp_text = cls.normalize_text(str(hyp.get(text_key, "")))
                similarity = difflib.SequenceMatcher(None, ref_text, hyp_text).ratio()
                if similarity >= threshold:
                    matched_ref.add(r_idx)
                    matched_hyp.add(h_idx)
                    break

        matched_count = len(matched_hyp)
        precision = matched_count / float(hyp_count) if hyp_count > 0 else 0.0
        recall = matched_count / float(ref_count) if ref_count > 0 else 0.0
        f1 = (2 * precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0

        return ExtractionMetrics(
            precision=round(precision, 4),
            recall=round(recall, 4),
            f1=round(f1, 4),
            matched_count=matched_count,
            reference_count=ref_count,
            hypothesis_count=hyp_count,
        )

    @classmethod
    def evaluate_zero_hallucinations(
        cls,
        hypothesis: MeetingAnalysisOutput,
        known_negatives: dict[str, list[str]],
    ) -> HallucinationEvaluation:
        """Enforces 100% precision on zero-hallucination tests
        (zero phantom owners, deadlines, or topics).
        """
        phantom_owners = known_negatives.get("phantom_owners", [])
        phantom_deadlines = known_negatives.get("phantom_deadlines", [])
        phantom_topics = known_negatives.get("phantom_topics", [])
        phantom_decisions = known_negatives.get("phantom_decisions", [])

        detected_owners: list[str] = []
        detected_deadlines: list[str] = []
        detected_topics: list[str] = []
        detected_decisions: list[str] = []

        # Check action item owners and due dates
        for item in hypothesis.action_items:
            if item.owner:
                owner_norm = cls.normalize_text(item.owner)
                for po in phantom_owners:
                    if cls.normalize_text(po) in owner_norm:
                        detected_owners.append(item.owner)
            if item.due_date:
                due_norm = cls.normalize_text(item.due_date)
                for pd in phantom_deadlines:
                    if cls.normalize_text(pd) in due_norm:
                        detected_deadlines.append(item.due_date)

        # Check topics
        for topic in hypothesis.topics:
            t_norm = cls.normalize_text(topic.title + " " + topic.summary)
            for pt in phantom_topics:
                if cls.normalize_text(pt) in t_norm:
                    detected_topics.append(pt)

        # Check decisions
        for dec in hypothesis.decisions:
            d_norm = cls.normalize_text(dec.decision_text)
            for pd in phantom_decisions:
                if cls.normalize_text(pd) in d_norm:
                    detected_decisions.append(pd)

        total_violations = (
            len(detected_owners)
            + len(detected_deadlines)
            + len(detected_topics)
            + len(detected_decisions)
        )
        passed = total_violations == 0
        hallucination_rate = (
            0.0
            if passed
            else round(
                total_violations
                / float(
                    max(
                        len(hypothesis.action_items)
                        + len(hypothesis.decisions)
                        + len(hypothesis.topics),
                        1,
                    )
                ),
                4,
            )
        )

        return HallucinationEvaluation(
            zero_hallucination_passed=passed,
            phantom_owners_detected=detected_owners,
            phantom_deadlines_detected=detected_deadlines,
            phantom_topics_detected=detected_topics,
            phantom_decisions_detected=detected_decisions,
            hallucination_rate=hallucination_rate,
        )

    @classmethod
    def evaluate_evidence_citations(
        cls,
        hypothesis: MeetingAnalysisOutput,
        transcript_segments: list[dict[str, Any]],
    ) -> EvidenceCitationMetrics:
        """Verifies cited evidence_segment_ids actually exist in the transcript."""
        valid_ids = {str(seg["id"]) for seg in transcript_segments}
        total_citations = 0
        valid_citations = 0
        invalid_ids: list[str] = []

        # Gather citations across topics, decisions, action_items, risks, questions
        all_cited: list[uuid.UUID] = []
        for t in hypothesis.topics:
            all_cited.extend(t.evidence_segment_ids)
        for d in hypothesis.decisions:
            all_cited.extend(d.evidence_segment_ids)
        for a in hypothesis.action_items:
            all_cited.extend(a.evidence_segment_ids)
        for r in hypothesis.risks:
            all_cited.extend(r.evidence_segment_ids)
        for q in hypothesis.open_questions:
            all_cited.extend(q.evidence_segment_ids)

        total_citations = len(all_cited)
        for cid in all_cited:
            str_id = str(cid)
            if str_id in valid_ids:
                valid_citations += 1
            else:
                invalid_ids.append(str_id)

        accuracy = valid_citations / float(total_citations) if total_citations > 0 else 1.0

        return EvidenceCitationMetrics(
            total_citations=total_citations,
            valid_citations=valid_citations,
            accuracy=round(accuracy, 4),
            invalid_segment_ids=invalid_ids,
        )

    # -----------------------------------------------------------------------
    # 4. Cost Calculations (Configurable assumptions, distinguishing estimates)
    # -----------------------------------------------------------------------

    @staticmethod
    def calculate_llm_cost(
        prompt_tokens: int,
        completion_tokens: int,
        prompt_rate_per_token: float,
        completion_rate_per_token: float,
    ) -> float:
        """Calculates estimated LLM inference cost based on explicit pricing assumptions."""
        cost = (prompt_tokens * prompt_rate_per_token) + (
            completion_tokens * completion_rate_per_token
        )
        return round(float(cost), 6)

    @staticmethod
    def calculate_stt_cost(
        audio_duration_seconds: float,
        cost_per_hour_usd: float,
    ) -> float:
        """Calculates estimated STT transcription cost based on duration and hourly rate."""
        hours = audio_duration_seconds / 3600.0
        return round(hours * cost_per_hour_usd, 6)

    # -----------------------------------------------------------------------
    # 5. Dataset Loader
    # -----------------------------------------------------------------------

    @staticmethod
    def load_dataset(dataset_dir: Path | str) -> dict[str, Any]:
        """Loads transcript, ground_truth, diarization_truth, and known_negatives."""
        base_path = Path(dataset_dir)
        transcript = json.loads((base_path / "transcript.json").read_text(encoding="utf-8"))
        ground_truth = json.loads((base_path / "ground_truth.json").read_text(encoding="utf-8"))
        diarization_truth = json.loads(
            (base_path / "diarization_truth.json").read_text(encoding="utf-8")
        )
        known_negatives = json.loads(
            (base_path / "known_negatives.json").read_text(encoding="utf-8")
        )

        return {
            "name": base_path.name,
            "path": str(base_path),
            "audio_path": str(base_path / "audio.wav"),
            "transcript": transcript,
            "ground_truth": ground_truth,
            "diarization_truth": diarization_truth,
            "known_negatives": known_negatives,
        }
