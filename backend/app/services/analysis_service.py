import logging
import uuid
from decimal import Decimal
from typing import Any

from app.agents.meeting_analysis_agent import (
    MeetingAnalysisAgent,
    MeetingAnalysisAgentError,
)
from app.agents.verification_agent import VerificationAgent
from app.core.config import Settings
from app.models.meeting_analysis import MeetingAnalysis
from app.models.transcript import TranscriptSegment
from app.repositories.analysis_repository import AnalysisRepository

logger = logging.getLogger(__name__)


# Standard pricing calculation based on COST_CONTROL.md (2026-10-v1)
# gpt-oss-120b: $0.15 / 1M prompt tokens, $0.60 / 1M completion tokens
# gpt-oss-20b:  $0.05 / 1M prompt tokens, $0.20 / 1M completion tokens
PRICING_RATES: dict[str, dict[str, Decimal]] = {
    "openai/gpt-oss-120b": {
        "prompt": Decimal("0.00000015"),
        "completion": Decimal("0.00000060"),
    },
    "openai/gpt-oss-20b": {
        "prompt": Decimal("0.00000005"),
        "completion": Decimal("0.00000020"),
    },
}
DEFAULT_PRICING = {
    "prompt": Decimal("0.00000015"),
    "completion": Decimal("0.00000060"),
}
PRICING_VERSION = "2026-10-v1"


class AnalysisService:
    """Service orchestrating prompt formatting, LLM extraction, grounding verification,
    deterministic timestamp derivation, and persistence of MeetingAnalysis records.
    """

    def __init__(
        self,
        analysis_repo: AnalysisRepository,
        analysis_agent: MeetingAnalysisAgent,
        verification_agent: VerificationAgent | None,
        settings: Settings,
    ) -> None:
        self.analysis_repo = analysis_repo
        self.analysis_agent = analysis_agent
        self.verification_agent = verification_agent
        self.settings = settings

    def _calculate_estimated_cost(
        self,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
    ) -> Decimal:
        rates = PRICING_RATES.get(model, DEFAULT_PRICING)
        cost = (Decimal(prompt_tokens) * rates["prompt"]) + (
            Decimal(completion_tokens) * rates["completion"]
        )
        return cost.quantize(Decimal("0.000001"))

    def _derive_timestamps(
        self,
        evidence_ids: list[uuid.UUID],
        segment_map: dict[uuid.UUID, TranscriptSegment],
    ) -> tuple[float | None, float | None]:
        """Derives start_time = MIN(start_time) and end_time = MAX(end_time) from cited segments."""
        valid_segments = [segment_map[sid] for sid in evidence_ids if sid in segment_map]
        if not valid_segments:
            return None, None
        min_start = min(s.start_time for s in valid_segments)
        max_end = max(s.end_time for s in valid_segments)
        return min_start, max_end

    async def execute_analysis(
        self,
        meeting_id: uuid.UUID,
        user_id: uuid.UUID,
        segments: list[TranscriptSegment],
        on_stage_change: Any = None,
    ) -> MeetingAnalysis:
        """Executes full analysis workflow, verifying evidence and saving entities."""
        segment_map: dict[uuid.UUID, TranscriptSegment] = {s.id: s for s in segments}
        segments_payload: list[dict[str, Any]] = [
            {
                "segment_id": str(s.id),
                "sequence_index": s.sequence_index,
                "start_time": s.start_time,
                "end_time": s.end_time,
                "speaker_label": s.speaker_label,
                "speaker": s.speaker,
                "text": s.text,
            }
            for s in segments
        ]

        # 1. Run LLM extraction with context-aware chunking and synthesis
        try:
            output, llm_response = self.analysis_agent.analyze_transcript(segments_payload)
            chunk_findings = getattr(self.analysis_agent, "last_chunk_findings", [])
        except MeetingAnalysisAgentError as exc:
            raise exc

        # 2. Evidence verification and completeness audit with targeted repair
        verification_performed = False
        verification_model: str | None = None

        if self.verification_agent:
            if on_stage_change:
                await on_stage_change()
            report = self.verification_agent.verify_analysis(
                output=output,
                all_segments=segments_payload,
                chunk_findings=chunk_findings,
            )
            verification_performed = True
            verification_model = self.settings.LLM_MODEL
            if not report.is_complete:
                logger.warning(
                    "Meeting %s analysis incomplete: %s",
                    meeting_id,
                    "; ".join(report.warnings),
                )

        # 3. Filter evidence segment IDs to only valid database segment IDs
        valid_uuids = set(segment_map.keys())

        # 4. Filter evidence segment IDs to only valid database segment IDs
        for topic in output.topics:
            topic.evidence_segment_ids = [
                sid for sid in topic.evidence_segment_ids if sid in valid_uuids
            ]
        for dec in output.decisions:
            dec.evidence_segment_ids = [
                sid for sid in dec.evidence_segment_ids if sid in valid_uuids
            ]
        for act in output.action_items:
            act.evidence_segment_ids = [
                sid for sid in act.evidence_segment_ids if sid in valid_uuids
            ]
        for rsk in output.risks:
            rsk.evidence_segment_ids = [
                sid for sid in rsk.evidence_segment_ids if sid in valid_uuids
            ]
        for qst in output.open_questions:
            qst.evidence_segment_ids = [
                sid for sid in qst.evidence_segment_ids if sid in valid_uuids
            ]

        # 5. Calculate cost & usage
        usage = llm_response.usage
        estimated_cost = self._calculate_estimated_cost(
            model=llm_response.model,
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
        )

        # 6. Idempotent persistence in PostgreSQL
        existing = await self.analysis_repo.get_by_meeting_id(
            meeting_id=meeting_id,
            user_id=user_id,
        )
        if existing:
            analysis = await self.analysis_repo.update_analysis(
                analysis=existing,
                provider=llm_response.provider,
                model=llm_response.model,
                title=output.title,
                executive_summary=output.executive_summary,
                prompt_tokens=usage.prompt_tokens,
                completion_tokens=usage.completion_tokens,
                total_tokens=usage.total_tokens,
                estimated_cost_usd=estimated_cost,
                pricing_version=PRICING_VERSION,
                verification_performed=verification_performed,
                verification_model=verification_model,
                speaker_contributions=output.speaker_contributions,
                context_and_details=output.context_and_details,
                next_steps=output.next_steps,
            )
            await self.analysis_repo.delete_child_entities(analysis.id)
        else:
            analysis = await self.analysis_repo.create_analysis(
                meeting_id=meeting_id,
                user_id=user_id,
                provider=llm_response.provider,
                model=llm_response.model,
                title=output.title,
                executive_summary=output.executive_summary,
                prompt_tokens=usage.prompt_tokens,
                completion_tokens=usage.completion_tokens,
                total_tokens=usage.total_tokens,
                estimated_cost_usd=estimated_cost,
                pricing_version=PRICING_VERSION,
                verification_performed=verification_performed,
                verification_model=verification_model,
                speaker_contributions=output.speaker_contributions,
                context_and_details=output.context_and_details,
                next_steps=output.next_steps,
            )

        # 7. Persist child entities with deterministically derived timestamps
        topics_payload = [
            {
                "title": t.title,
                "summary": t.summary,
                "discussion_progression": t.discussion_progression,
                "sequence_index": idx,
                "start_time": self._derive_timestamps(t.evidence_segment_ids, segment_map)[0],
                "end_time": self._derive_timestamps(t.evidence_segment_ids, segment_map)[1],
            }
            for idx, t in enumerate(output.topics)
        ]
        await self.analysis_repo.add_topics(analysis.id, meeting_id, topics_payload)

        decisions_payload = [
            {
                "decision_text": d.decision_text,
                "confidence": d.confidence.value,
                "sequence_index": idx,
                "evidence_segment_ids": d.evidence_segment_ids,
                "start_time": self._derive_timestamps(d.evidence_segment_ids, segment_map)[0],
                "end_time": self._derive_timestamps(d.evidence_segment_ids, segment_map)[1],
            }
            for idx, d in enumerate(output.decisions)
        ]
        await self.analysis_repo.add_decisions(analysis.id, meeting_id, decisions_payload)

        actions_payload = [
            {
                "action_text": a.action_text,
                "owner": a.owner,
                "due_date": a.due_date,
                "sequence_index": idx,
                "evidence_segment_ids": a.evidence_segment_ids,
                "start_time": self._derive_timestamps(a.evidence_segment_ids, segment_map)[0],
                "end_time": self._derive_timestamps(a.evidence_segment_ids, segment_map)[1],
            }
            for idx, a in enumerate(output.action_items)
        ]
        await self.analysis_repo.add_action_items(analysis.id, meeting_id, actions_payload)

        risks_payload = [
            {
                "risk_text": r.risk_text,
                "sequence_index": idx,
                "evidence_segment_ids": r.evidence_segment_ids,
                "start_time": self._derive_timestamps(r.evidence_segment_ids, segment_map)[0],
                "end_time": self._derive_timestamps(r.evidence_segment_ids, segment_map)[1],
            }
            for idx, r in enumerate(output.risks)
        ]
        await self.analysis_repo.add_risks(analysis.id, meeting_id, risks_payload)

        questions_payload = [
            {
                "question_text": q.question_text,
                "sequence_index": idx,
                "evidence_segment_ids": q.evidence_segment_ids,
                "start_time": self._derive_timestamps(q.evidence_segment_ids, segment_map)[0],
                "end_time": self._derive_timestamps(q.evidence_segment_ids, segment_map)[1],
            }
            for idx, q in enumerate(output.open_questions)
        ]
        await self.analysis_repo.add_open_questions(analysis.id, meeting_id, questions_payload)

        logger.info(
            "Analysis completed for meeting %s (prompt_tokens=%d, completion_tokens=%d, cost=$%s)",
            meeting_id,
            usage.prompt_tokens,
            usage.completion_tokens,
            estimated_cost,
        )
        return analysis
