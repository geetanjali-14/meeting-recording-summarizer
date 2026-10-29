import logging
import re
import uuid
from typing import Any

from pydantic import BaseModel, Field

from app.core.config import Settings
from app.prompts.meeting_analysis_prompt import (
    SYSTEM_COMPLETENESS_VERIFICATION_INSTRUCTIONS,
    SYSTEM_VERIFICATION_INSTRUCTIONS,
)
from app.providers.llm.base import LLMProvider, LLMProviderError
from app.schemas.analysis import (
    ActionItemOutput,
    DecisionConfidence,
    DecisionOutput,
    MeetingAnalysisOutput,
    OpenQuestionOutput,
    RiskOutput,
    TopicOutput,
)

logger = logging.getLogger(__name__)


class MaterialInventoryItem(BaseModel):
    """An extracted material fact or outcome tracked during analysis."""

    category: str  # "topic", "decision", "action_item", "risk", "open_question", "detail", "next_step"
    text: str
    owner: str | None = None
    due_date: str | None = None
    evidence_segment_ids: list[uuid.UUID] = Field(default_factory=list)
    status: str = "INCLUDED"  # "INCLUDED", "MERGED", "EXCLUDED_FILLER", "REPAIRED", "MISSING"


class VerificationReport(BaseModel):
    """Structured report tracking transcript coverage, evidence grounding, and completeness inventory."""

    is_complete: bool = True
    total_segments: int = 0
    covered_segments: int = 0
    coverage_percentage: float = 100.0
    verified_decisions: int = 0
    flagged_decisions: int = 0
    verified_actions: int = 0
    modified_actions: int = 0
    repaired_items_count: int = 0
    material_inventory_count: int = 0
    inventory_items: list[MaterialInventoryItem] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def _normalize_text(text: str) -> str:
    """Lowercases, removes punctuation, and tokenizes text for fuzzy match checks."""
    cleaned = re.sub(r"[^\w\s]", " ", text.lower())
    return " ".join(cleaned.split())


class VerificationAgent:
    """Production-grade completeness, evidence grounding, and targeted repair agent.

    Verifies:
    1. Coverage completeness across all transcript segments.
    2. Grounding of action item owners and deadlines against cited segment text.
    3. Grounding of inferred decisions against cited segment text.
    4. Detection and elimination of hallucinated UUIDs not present in the transcript.
    5. Inventory audit of chunk-extracted findings against synthesized output with targeted repair.
    """

    def __init__(self, llm_provider: LLMProvider, settings: Settings) -> None:
        self.llm_provider = llm_provider
        self.settings = settings
        self.model = settings.LLM_MODEL

    def verify_analysis(
        self,
        output: MeetingAnalysisOutput,
        all_segments: list[dict[str, Any]],
        chunk_findings: list[dict[str, Any]] | None = None,
    ) -> VerificationReport:
        """Audits the full meeting intelligence output for completeness and factual grounding."""
        segment_map = {str(s.get("segment_id") or s.get("id")): s for s in all_segments}
        valid_ids = set(segment_map.keys())
        report = VerificationReport(
            total_segments=len(all_segments),
            covered_segments=output.analyzed_segment_count or len(all_segments),
            coverage_percentage=output.coverage_percentage,
        )

        # 1. Segment coverage completeness verification
        if report.coverage_percentage < 95.0:
            report.is_complete = False
            report.warnings.append(
                f"Transcript coverage incomplete: "
                f"{report.coverage_percentage}% of segments analyzed"
            )

        # 2. Evidence citations audit: sanitize all category IDs to valid database segments
        for topic in output.topics:
            topic.evidence_segment_ids = [
                sid for sid in topic.evidence_segment_ids if str(sid) in valid_ids
            ]

        for act in output.action_items:
            act.evidence_segment_ids = [
                sid for sid in act.evidence_segment_ids if str(sid) in valid_ids
            ]
            cited = [
                segment_map[str(sid)] for sid in act.evidence_segment_ids if str(sid) in segment_map
            ]
            if act.owner:
                owner_verified = self.verify_action_item_owner(act, cited)
                if not owner_verified or act.owner is None:
                    report.modified_actions += 1
                else:
                    report.verified_actions += 1

        for dec in output.decisions:
            dec.evidence_segment_ids = [
                sid for sid in dec.evidence_segment_ids if str(sid) in valid_ids
            ]
            cited = [
                segment_map[str(sid)] for sid in dec.evidence_segment_ids if str(sid) in segment_map
            ]
            if dec.confidence == DecisionConfidence.INFERRED:
                valid = self.verify_decision(dec, cited)
                if not valid:
                    report.flagged_decisions += 1
                else:
                    report.verified_decisions += 1
            else:
                report.verified_decisions += 1

        for rsk in output.risks:
            rsk.evidence_segment_ids = [
                sid for sid in rsk.evidence_segment_ids if str(sid) in valid_ids
            ]
        for qst in output.open_questions:
            qst.evidence_segment_ids = [
                sid for sid in qst.evidence_segment_ids if str(sid) in valid_ids
            ]

        # Sanitize details and next steps evidence
        if output.context_and_details:
            for item in output.context_and_details:
                raw_e = item.get("evidence_segment_ids", [])
                item["evidence_segment_ids"] = [
                    str(sid) for sid in raw_e if str(sid) in valid_ids
                ]
        if output.next_steps:
            for item in output.next_steps:
                raw_e = item.get("evidence_segment_ids", [])
                item["evidence_segment_ids"] = [
                    str(sid) for sid in raw_e if str(sid) in valid_ids
                ]

        # 3. Completeness inventory verification & targeted repair
        if chunk_findings:
            self._audit_and_repair_completeness(output, chunk_findings, report, valid_ids)

        return report

    def _audit_and_repair_completeness(
        self,
        output: MeetingAnalysisOutput,
        chunk_findings: list[dict[str, Any]],
        report: VerificationReport,
        valid_ids: set[str],
    ) -> None:
        """Builds an inventory of chunk-level extractions, tracks coverage against output,
        and triggers targeted repair for any materially missing items.
        """
        existing_decisions_norm = [_normalize_text(d.decision_text) for d in output.decisions]
        existing_actions_norm = [_normalize_text(a.action_text) for a in output.action_items]
        existing_risks_norm = [_normalize_text(r.risk_text) for r in output.risks]
        existing_questions_norm = [_normalize_text(q.question_text) for q in output.open_questions]
        existing_topics_norm = [_normalize_text(t.title) + " " + _normalize_text(t.summary) for t in output.topics]

        missing_items: list[MaterialInventoryItem] = []

        # Iterate all findings from chunks
        for cf in chunk_findings:
            # 1. Decisions
            for d in cf.get("decisions", []):
                text = d.get("decision_text", "")
                norm = _normalize_text(text)
                is_present = any(
                    norm in ex or ex in norm or (len(set(norm.split()) & set(ex.split())) >= 4)
                    for ex in existing_decisions_norm
                )
                e_ids = [uuid.UUID(str(sid)) for sid in d.get("evidence_segment_ids", []) if str(sid) in valid_ids]
                item = MaterialInventoryItem(
                    category="decision",
                    text=text,
                    evidence_segment_ids=e_ids,
                    status="INCLUDED" if is_present else "MISSING",
                )
                report.inventory_items.append(item)
                if not is_present:
                    missing_items.append(item)

            # 2. Action items
            for a in cf.get("action_items", []):
                text = a.get("action_text", "")
                norm = _normalize_text(text)
                is_present = any(
                    norm in ex or ex in norm or (len(set(norm.split()) & set(ex.split())) >= 3)
                    for ex in existing_actions_norm
                )
                e_ids = [uuid.UUID(str(sid)) for sid in a.get("evidence_segment_ids", []) if str(sid) in valid_ids]
                item = MaterialInventoryItem(
                    category="action_item",
                    text=text,
                    owner=a.get("owner"),
                    due_date=a.get("due_date"),
                    evidence_segment_ids=e_ids,
                    status="INCLUDED" if is_present else "MISSING",
                )
                report.inventory_items.append(item)
                if not is_present:
                    missing_items.append(item)

            # 3. Risks
            for r in cf.get("risks", []):
                text = r.get("risk_text", "")
                norm = _normalize_text(text)
                is_present = any(
                    norm in ex or ex in norm or (len(set(norm.split()) & set(ex.split())) >= 3)
                    for ex in existing_risks_norm
                )
                e_ids = [uuid.UUID(str(sid)) for sid in r.get("evidence_segment_ids", []) if str(sid) in valid_ids]
                item = MaterialInventoryItem(
                    category="risk",
                    text=text,
                    evidence_segment_ids=e_ids,
                    status="INCLUDED" if is_present else "MISSING",
                )
                report.inventory_items.append(item)
                if not is_present:
                    missing_items.append(item)

            # 4. Open Questions
            for q in cf.get("open_questions", []):
                text = q.get("question_text", "")
                norm = _normalize_text(text)
                is_present = any(
                    norm in ex or ex in norm or (len(set(norm.split()) & set(ex.split())) >= 3)
                    for ex in existing_questions_norm
                )
                e_ids = [uuid.UUID(str(sid)) for sid in q.get("evidence_segment_ids", []) if str(sid) in valid_ids]
                item = MaterialInventoryItem(
                    category="open_question",
                    text=text,
                    evidence_segment_ids=e_ids,
                    status="INCLUDED" if is_present else "MISSING",
                )
                report.inventory_items.append(item)
                if not is_present:
                    missing_items.append(item)

        report.material_inventory_count = len(report.inventory_items)

        # Targeted Repair: insert missing material items into final output
        if missing_items:
            logger.info("Completeness audit identified %d missing items. Executing targeted repair.", len(missing_items))
            for m in missing_items:
                if m.category == "decision":
                    output.decisions.append(
                        DecisionOutput(
                            decision_text=m.text,
                            confidence=DecisionConfidence.EXPLICIT,
                            sequence_index=len(output.decisions),
                            evidence_segment_ids=m.evidence_segment_ids,
                        )
                    )
                    m.status = "REPAIRED"
                    report.repaired_items_count += 1
                elif m.category == "action_item":
                    output.action_items.append(
                        ActionItemOutput(
                            action_text=m.text,
                            owner=m.owner,
                            due_date=m.due_date,
                            sequence_index=len(output.action_items),
                            evidence_segment_ids=m.evidence_segment_ids,
                        )
                    )
                    m.status = "REPAIRED"
                    report.repaired_items_count += 1
                elif m.category == "risk":
                    output.risks.append(
                        RiskOutput(
                            risk_text=m.text,
                            sequence_index=len(output.risks),
                            evidence_segment_ids=m.evidence_segment_ids,
                        )
                    )
                    m.status = "REPAIRED"
                    report.repaired_items_count += 1
                elif m.category == "open_question":
                    output.open_questions.append(
                        OpenQuestionOutput(
                            question_text=m.text,
                            sequence_index=len(output.open_questions),
                            evidence_segment_ids=m.evidence_segment_ids,
                        )
                    )
                    m.status = "REPAIRED"
                    report.repaired_items_count += 1

            # Deterministically re-index
            for idx, d in enumerate(output.decisions):
                d.sequence_index = idx
            for idx, a in enumerate(output.action_items):
                a.sequence_index = idx
            for idx, r in enumerate(output.risks):
                r.sequence_index = idx
            for idx, q in enumerate(output.open_questions):
                q.sequence_index = idx

            # Ensure repaired items are also woven into the unified narrative executive_summary if missing
            repaired_narrative_additions = []
            exec_norm = _normalize_text(output.executive_summary)
            for m in missing_items:
                norm_m = _normalize_text(m.text)
                if norm_m not in exec_norm:
                    if m.category == "decision":
                        repaired_narrative_additions.append(f"Regarding key agreements: The team decided: {m.text}.")
                    elif m.category == "action_item":
                        owner_str = f"assigned to {m.owner}" if m.owner else "unassigned"
                        due_str = f" with deadline {m.due_date}" if m.due_date else ""
                        repaired_narrative_additions.append(f"For follow-up actions: {m.text} ({owner_str}{due_str}).")
                    elif m.category == "risk":
                        repaired_narrative_additions.append(f"Concerning risks: {m.text}.")
                    elif m.category == "open_question":
                        repaired_narrative_additions.append(f"Pending open matters: {m.text}.")
            if repaired_narrative_additions:
                output.executive_summary = (
                    output.executive_summary.rstrip() + "\n\n" + " ".join(repaired_narrative_additions)
                )

    def verify_action_item_owner(
        self,
        action_item: ActionItemOutput,
        cited_segments: list[dict[str, Any]],
    ) -> bool:
        """Determines if the assigned owner is grounded in cited segments."""
        if not action_item.owner or not cited_segments:
            return True

        # Deterministic check: owner name token match
        owner_clean = action_item.owner.strip().lower()
        if len(owner_clean) >= 2:
            pattern = re.compile(rf"\b{re.escape(owner_clean)}\b", re.IGNORECASE)
            has_lexical_match = any(
                bool(pattern.search(s.get("text", "")))
                or bool(pattern.search(str(s.get("speaker") or "")))
                or bool(pattern.search(str(s.get("speaker_label") or "")))
                for s in cited_segments
            )
        else:
            has_lexical_match = any(
                owner_clean in s.get("text", "").lower()
                or owner_clean in (s.get("speaker") or "").lower()
                or owner_clean in (s.get("speaker_label") or "").lower()
                for s in cited_segments
            )

        if has_lexical_match:
            return True

        # Targeted verification LLM call
        prompt = (
            f'Action Item: "{action_item.action_text}"\n'
            f'Assigned Owner: "{action_item.owner}"\n\n'
            "Cited Segments:\n" + "\n".join(f"- {s.get('text', '')}" for s in cited_segments)
        )
        messages = [
            {"role": "system", "content": SYSTEM_VERIFICATION_INSTRUCTIONS},
            {"role": "user", "content": prompt},
        ]
        try:
            res = self.llm_provider.generate_structured(messages=messages, model=self.model)
            verdict = res.parsed_json.get("verdict", "accept")
            if verdict == "drop_owner":
                action_item.owner = None
                return True
            if verdict == "reject":
                return False
            return True
        except LLMProviderError as exc:
            logger.warning("Targeted verification call failed (%s); keeping existing claim.", exc)
            return True

    def verify_decision(
        self,
        decision: DecisionOutput,
        cited_segments: list[dict[str, Any]],
    ) -> bool:
        """Verifies if an inferred decision has valid basis in cited segments."""
        if decision.confidence == DecisionConfidence.EXPLICIT or not cited_segments:
            return True

        prompt = f'Inferred Decision: "{decision.decision_text}"\n\nCited Segments:\n' + "\n".join(
            f"- {s.get('text', '')}" for s in cited_segments
        )
        messages = [
            {"role": "system", "content": SYSTEM_VERIFICATION_INSTRUCTIONS},
            {"role": "user", "content": prompt},
        ]
        try:
            res = self.llm_provider.generate_structured(messages=messages, model=self.model)
            verdict = res.parsed_json.get("verdict", "accept")
            return bool(verdict != "reject")
        except LLMProviderError as exc:
            logger.warning(
                "Targeted verification call failed (%s); keeping existing decision.",
                exc,
            )
            return True
