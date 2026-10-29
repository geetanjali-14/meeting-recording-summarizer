import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.meeting_analysis import (
    ActionItem,
    ConfidenceLevel,
    Decision,
    MeetingAnalysis,
    OpenQuestion,
    Risk,
    Topic,
)


class AnalysisRepository:
    """Repository for MeetingAnalysis and extraction entities, strictly scoped by user_id."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_analysis(
        self,
        meeting_id: uuid.UUID,
        user_id: uuid.UUID,
        provider: str,
        model: str,
        title: str | None = None,
        executive_summary: str | None = None,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
        total_tokens: int | None = None,
        estimated_cost_usd: Decimal | None = None,
        pricing_version: str | None = None,
        verification_performed: bool = False,
        verification_model: str | None = None,
        speaker_contributions: dict[str, Any] | None = None,
        context_and_details: list[dict[str, Any]] | None = None,
        next_steps: list[dict[str, Any]] | None = None,
        structured_data: dict[str, Any] | None = None,
    ) -> MeetingAnalysis:
        analysis = MeetingAnalysis(
            meeting_id=meeting_id,
            user_id=user_id,
            provider=provider,
            model=model,
            title=title,
            executive_summary=executive_summary,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            estimated_cost_usd=estimated_cost_usd,
            pricing_version=pricing_version,
            verification_performed=verification_performed,
            verification_model=verification_model,
            speaker_contributions=speaker_contributions if speaker_contributions is not None else {},
            context_and_details=context_and_details if context_and_details is not None else [],
            next_steps=next_steps if next_steps is not None else [],
            structured_data=structured_data if structured_data is not None else {},
        )
        self.session.add(analysis)
        await self.session.flush()
        return analysis

    async def update_analysis(
        self,
        analysis: MeetingAnalysis,
        provider: str,
        model: str,
        title: str | None = None,
        executive_summary: str | None = None,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
        total_tokens: int | None = None,
        estimated_cost_usd: Decimal | None = None,
        pricing_version: str | None = None,
        verification_performed: bool = False,
        verification_model: str | None = None,
        speaker_contributions: dict[str, Any] | None = None,
        context_and_details: list[dict[str, Any]] | None = None,
        next_steps: list[dict[str, Any]] | None = None,
        structured_data: dict[str, Any] | None = None,
    ) -> MeetingAnalysis:
        """Updates top-level analysis record upon rerun."""
        analysis.provider = provider
        analysis.model = model
        analysis.title = title
        analysis.executive_summary = executive_summary
        analysis.prompt_tokens = prompt_tokens
        analysis.completion_tokens = completion_tokens
        analysis.total_tokens = total_tokens
        analysis.estimated_cost_usd = estimated_cost_usd
        analysis.pricing_version = pricing_version
        analysis.verification_performed = verification_performed
        analysis.verification_model = verification_model
        if speaker_contributions is not None:
            analysis.speaker_contributions = speaker_contributions
        if context_and_details is not None:
            analysis.context_and_details = context_and_details
        if next_steps is not None:
            analysis.next_steps = next_steps
        if structured_data is not None:
            analysis.structured_data = structured_data
        await self.session.flush()
        return analysis

    async def get_by_meeting_id(
        self,
        meeting_id: uuid.UUID,
        user_id: uuid.UUID,
        include_children: bool = False,
    ) -> MeetingAnalysis | None:
        stmt = select(MeetingAnalysis).where(
            MeetingAnalysis.meeting_id == meeting_id,
            MeetingAnalysis.user_id == user_id,
        )
        if include_children:
            stmt = stmt.options(
                selectinload(MeetingAnalysis.topics),
                selectinload(MeetingAnalysis.decisions),
                selectinload(MeetingAnalysis.action_items),
                selectinload(MeetingAnalysis.risks),
                selectinload(MeetingAnalysis.open_questions),
            )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def delete_child_entities(self, analysis_id: uuid.UUID) -> None:
        """Deletes all child extraction entities for an analysis to ensure idempotency on rerun."""
        await self.session.execute(delete(Topic).where(Topic.analysis_id == analysis_id))
        await self.session.execute(delete(Decision).where(Decision.analysis_id == analysis_id))
        await self.session.execute(delete(ActionItem).where(ActionItem.analysis_id == analysis_id))
        await self.session.execute(delete(Risk).where(Risk.analysis_id == analysis_id))
        await self.session.execute(
            delete(OpenQuestion).where(OpenQuestion.analysis_id == analysis_id)
        )
        await self.session.flush()

    async def add_topics(
        self,
        analysis_id: uuid.UUID,
        meeting_id: uuid.UUID,
        topics_data: list[dict[str, Any]],
    ) -> list[Topic]:
        topics = [
            Topic(
                analysis_id=analysis_id,
                meeting_id=meeting_id,
                title=t["title"],
                summary=t.get("summary"),
                discussion_progression=t.get("discussion_progression"),
                sequence_index=t.get("sequence_index", idx),
                start_time=t.get("start_time"),
                end_time=t.get("end_time"),
            )
            for idx, t in enumerate(topics_data)
        ]
        self.session.add_all(topics)
        await self.session.flush()
        return topics

    async def add_decisions(
        self,
        analysis_id: uuid.UUID,
        meeting_id: uuid.UUID,
        decisions_data: list[dict[str, Any]],
    ) -> list[Decision]:
        decisions = [
            Decision(
                analysis_id=analysis_id,
                meeting_id=meeting_id,
                decision_text=d["decision_text"],
                sequence_index=d.get("sequence_index", idx),
                confidence=ConfidenceLevel(d.get("confidence", "EXPLICIT")),
                start_time=d.get("start_time"),
                end_time=d.get("end_time"),
                evidence_segment_ids=d.get("evidence_segment_ids", []),
            )
            for idx, d in enumerate(decisions_data)
        ]
        self.session.add_all(decisions)
        await self.session.flush()
        return decisions

    async def add_action_items(
        self,
        analysis_id: uuid.UUID,
        meeting_id: uuid.UUID,
        items_data: list[dict[str, Any]],
    ) -> list[ActionItem]:
        items = [
            ActionItem(
                analysis_id=analysis_id,
                meeting_id=meeting_id,
                action_text=a["action_text"],
                owner=a.get("owner"),
                due_date=a.get("due_date"),
                sequence_index=a.get("sequence_index", idx),
                start_time=a.get("start_time"),
                end_time=a.get("end_time"),
                evidence_segment_ids=a.get("evidence_segment_ids", []),
            )
            for idx, a in enumerate(items_data)
        ]
        self.session.add_all(items)
        await self.session.flush()
        return items

    async def add_risks(
        self,
        analysis_id: uuid.UUID,
        meeting_id: uuid.UUID,
        risks_data: list[dict[str, Any]],
    ) -> list[Risk]:
        risks = [
            Risk(
                analysis_id=analysis_id,
                meeting_id=meeting_id,
                risk_text=r["risk_text"],
                sequence_index=r.get("sequence_index", idx),
                start_time=r.get("start_time"),
                end_time=r.get("end_time"),
                evidence_segment_ids=r.get("evidence_segment_ids", []),
            )
            for idx, r in enumerate(risks_data)
        ]
        self.session.add_all(risks)
        await self.session.flush()
        return risks

    async def add_open_questions(
        self,
        analysis_id: uuid.UUID,
        meeting_id: uuid.UUID,
        questions_data: list[dict[str, Any]],
    ) -> list[OpenQuestion]:
        questions = [
            OpenQuestion(
                analysis_id=analysis_id,
                meeting_id=meeting_id,
                question_text=q["question_text"],
                sequence_index=q.get("sequence_index", idx),
                start_time=q.get("start_time"),
                end_time=q.get("end_time"),
                evidence_segment_ids=q.get("evidence_segment_ids", []),
            )
            for idx, q in enumerate(questions_data)
        ]
        self.session.add_all(questions)
        await self.session.flush()
        return questions
