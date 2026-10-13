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
        model: str | None = None,
        diarization_provider: str | None = None,
        total_duration_seconds: float | None = None,
        segment_count: int | None = None,
        raw_transcript_text: str | None = None,
    ) -> Transcript:
        transcript = Transcript(
            meeting_id=meeting_id,
            user_id=user_id,
            provider=provider,
            language=language,
            model=model,
            diarization_provider=diarization_provider,
            total_duration_seconds=total_duration_seconds,
            segment_count=segment_count,
            raw_transcript_text=raw_transcript_text,
        )
        self.session.add(transcript)
        await self.session.flush()
        return transcript

    async def update_transcript(
        self,
        transcript: Transcript,
        provider: str,
        language: str | None = None,
        model: str | None = None,
        diarization_provider: str | None = None,
        total_duration_seconds: float | None = None,
        segment_count: int | None = None,
        raw_transcript_text: str | None = None,
    ) -> Transcript:
        """Updates top-level transcript metadata upon rerun/reprocessing."""
        transcript.provider = provider
        if language is not None:
            transcript.language = language
        if model is not None:
            transcript.model = model
        if diarization_provider is not None:
            transcript.diarization_provider = diarization_provider
        if total_duration_seconds is not None:
            transcript.total_duration_seconds = total_duration_seconds
        if segment_count is not None:
            transcript.segment_count = segment_count
        if raw_transcript_text is not None:
            transcript.raw_transcript_text = raw_transcript_text
        await self.session.flush()
        return transcript

    async def delete_segments(self, transcript_id: uuid.UUID) -> None:
        """Deletes existing segments for idempotency on rerun."""
        from sqlalchemy import delete

        stmt = delete(TranscriptSegment).where(TranscriptSegment.transcript_id == transcript_id)
        await self.session.execute(stmt)
        await self.session.flush()

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
