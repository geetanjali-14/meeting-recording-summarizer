import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.meeting_analysis import (
    ActionItem,
    Decision,
    MeetingAnalysis,
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
        )
        self.session.add(analysis)
        await self.session.flush()
        return analysis

    async def get_by_meeting_id(
        self,
        meeting_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> MeetingAnalysis | None:
        stmt = select(MeetingAnalysis).where(
            MeetingAnalysis.meeting_id == meeting_id,
            MeetingAnalysis.user_id == user_id,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def add_decision(
        self,
        analysis_id: uuid.UUID,
        meeting_id: uuid.UUID,
        decision_text: str,
        sequence_index: int,
        evidence_segment_ids: list[uuid.UUID],
    ) -> Decision:
        decision = Decision(
            analysis_id=analysis_id,
            meeting_id=meeting_id,
            decision_text=decision_text,
            sequence_index=sequence_index,
            evidence_segment_ids=evidence_segment_ids,
        )
        self.session.add(decision)
        await self.session.flush()
        return decision

    async def add_action_item(
        self,
        analysis_id: uuid.UUID,
        meeting_id: uuid.UUID,
        action_text: str,
        sequence_index: int,
        evidence_segment_ids: list[uuid.UUID],
        owner: str | None = None,
        due_date: str | None = None,
    ) -> ActionItem:
        item = ActionItem(
            analysis_id=analysis_id,
            meeting_id=meeting_id,
            action_text=action_text,
            owner=owner,
            due_date=due_date,
            sequence_index=sequence_index,
            evidence_segment_ids=evidence_segment_ids,
        )
        self.session.add(item)
        await self.session.flush()
        return item
