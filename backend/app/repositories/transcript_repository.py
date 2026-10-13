import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.transcript import Transcript, TranscriptSegment


class TranscriptRepository:
    """Repository for Transcript and TranscriptSegment operations, strictly scoped by user_id."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_transcript(
        self,
        meeting_id: uuid.UUID,
        user_id: uuid.UUID,
        provider: str,
        language: str | None = None,
    ) -> Transcript:
        transcript = Transcript(
            meeting_id=meeting_id,
            user_id=user_id,
            provider=provider,
            language=language,
        )
        self.session.add(transcript)
        await self.session.flush()
        return transcript

    async def get_by_meeting_id(
        self,
        meeting_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> Transcript | None:
        stmt = select(Transcript).where(
            Transcript.meeting_id == meeting_id,
            Transcript.user_id == user_id,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def add_segments(
        self,
        transcript_id: uuid.UUID,
        meeting_id: uuid.UUID,
        segments_data: list[dict[str, Any]],
    ) -> list[TranscriptSegment]:
        segments: list[TranscriptSegment] = []
        for data in segments_data:
            seg = TranscriptSegment(
                transcript_id=transcript_id,
                meeting_id=meeting_id,
                sequence_index=data["sequence_index"],
                start_time=data["start_time"],
                end_time=data["end_time"],
                speaker_label=data.get("speaker_label"),
                speaker=data.get("speaker"),
                text=data["text"],
                segment_metadata=data.get("metadata"),
            )
            self.session.add(seg)
            segments.append(seg)
        await self.session.flush()
        return segments

    async def get_segments_by_transcript(
        self,
        transcript_id: uuid.UUID,
    ) -> Sequence[TranscriptSegment]:
        stmt = (
            select(TranscriptSegment)
            .where(TranscriptSegment.transcript_id == transcript_id)
            .order_by(TranscriptSegment.sequence_index.asc())
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()
