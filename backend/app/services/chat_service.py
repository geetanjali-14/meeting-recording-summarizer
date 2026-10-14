import logging
import uuid
from datetime import UTC, datetime

from app.core.config import Settings
from app.models.chat import ChatRole
from app.models.transcript import TranscriptSegment
from app.providers.llm.base import LLMProvider
from app.repositories.chat_repository import ChatRepository
from app.repositories.meeting_repository import MeetingRepository
from app.repositories.transcript_repository import TranscriptRepository
from app.schemas.chat import ChatCitation, ChatMessageResponse, ChatResponse

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """<SYSTEM_INSTRUCTIONS>
You are an objective Meeting Intelligence Q&A Assistant.
Answer the user's question accurately using ONLY the evidence presented in the transcript.
Adhere strictly to these rules:
1. Ground your answers strictly in the transcript dialogue.
2. If the transcript does not provide sufficient evidence, state clearly:
"The meeting transcript does not contain information to answer this question."
Do not fabricate facts, owners, dates, or decisions.
3. Cite all relevant `segment_id` values supporting your answer in `cited_segment_ids`.
4. Return your output strictly as a JSON object matching this schema:
{
  "answer": "string",
  "cited_segment_ids": ["uuid-string", ...]
}
</SYSTEM_INSTRUCTIONS>"""


class ChatService:
    """Service orchestrating conversational Q&A over transcripts with grounded citations."""

    def __init__(
        self,
        meeting_repo: MeetingRepository,
        transcript_repo: TranscriptRepository,
        chat_repo: ChatRepository,
        llm_provider: LLMProvider,
        settings: Settings,
    ) -> None:
        self.meeting_repo = meeting_repo
        self.transcript_repo = transcript_repo
        self.chat_repo = chat_repo
        self.llm_provider = llm_provider
        self.settings = settings

    async def answer_question(
        self,
        meeting_id: uuid.UUID,
        user_id: uuid.UUID,
        question: str,
        session_id: uuid.UUID | None = None,
    ) -> ChatResponse:
        # 1. Enforce tenant isolation & meeting existence
        meeting = await self.meeting_repo.get_by_id(meeting_id=meeting_id, user_id=user_id)
        if meeting is None:
            raise ValueError("Meeting not found")

        # 2. Get transcript and segments
        transcript = await self.transcript_repo.get_by_meeting_id(
            meeting_id=meeting_id, user_id=user_id
        )
        if transcript is None:
            raise ValueError("Transcript not found for this meeting")

        segments = await self.transcript_repo.get_segments_by_transcript(transcript.id)
        if not segments:
            raise ValueError("Transcript contains no segments")

        segment_map: dict[uuid.UUID, TranscriptSegment] = {seg.id: seg for seg in segments}

        # 3. Retrieve or create session
        session = await self.chat_repo.get_or_create_session(
            meeting_id=meeting_id,
            user_id=user_id,
            session_id=session_id,
            title=question[:50],
        )

        # 4. Save user question
        await self.chat_repo.add_message(
            session_id=session.id,
            meeting_id=meeting_id,
            user_id=user_id,
            role=ChatRole.USER,
            content=question,
        )

        # 5. Format dialogue with prompt injection defense delimiter boundaries
        formatted_segments = []
        for seg in segments:
            speaker = seg.speaker or seg.speaker_label or "Speaker"
            formatted_segments.append(
                f'[{seg.id}] ({seg.start_time:.1f}s - {seg.end_time:.1f}s) {speaker}: "{seg.text}"'
            )

        transcript_text = "\n".join(formatted_segments)
        user_prompt = f"""<UNTRUSTED_TRANSCRIPT>
{transcript_text}
</UNTRUSTED_TRANSCRIPT>

User Question: {question}"""

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        schema = {
            "type": "object",
            "properties": {
                "answer": {"type": "string"},
                "cited_segment_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": ["answer", "cited_segment_ids"],
        }

        try:
            llm_response = self.llm_provider.generate_structured(
                messages=messages,
                json_schema=schema,
                temperature=0.0,
                model=self.settings.LLM_MODEL,
            )
            data = llm_response.parsed_json
            answer_text = data.get("answer", "")
            raw_citations = data.get("cited_segment_ids", [])
        except Exception:
            logger.error("LLM generation failed in chat service", exc_info=True)
            answer_text = "I am unable to answer this question at this time due to an error."
            raw_citations = []

        valid_citations: list[ChatCitation] = []
        valid_citation_ids: list[uuid.UUID] = []

        for cid in raw_citations:
            try:
                parsed_id = uuid.UUID(str(cid))
                if parsed_id in segment_map:
                    seg = segment_map[parsed_id]
                    valid_citations.append(
                        ChatCitation(
                            segment_id=seg.id,
                            start_time=seg.start_time,
                            end_time=seg.end_time,
                            speaker=seg.speaker or seg.speaker_label,
                            text_snippet=seg.text[:120] if seg.text else None,
                        )
                    )
                    valid_citation_ids.append(seg.id)
            except (ValueError, TypeError):
                continue

        valid_citations.sort(key=lambda c: c.start_time)

        # 8. Persist assistant response
        assistant_msg = await self.chat_repo.add_message(
            session_id=session.id,
            meeting_id=meeting_id,
            user_id=user_id,
            role=ChatRole.ASSISTANT,
            content=answer_text,
            citation_segment_ids=valid_citation_ids,
        )

        created_time = (
            assistant_msg.created_at.isoformat()
            if assistant_msg.created_at is not None
            else datetime.now(UTC).isoformat()
        )

        return ChatResponse(
            session_id=session.id,
            message=ChatMessageResponse(
                message_id=assistant_msg.id,
                session_id=session.id,
                meeting_id=meeting_id,
                role=assistant_msg.role.value,
                content=assistant_msg.content,
                citations=valid_citations,
                created_at=created_time,
            ),
        )

    async def get_messages(
        self,
        meeting_id: uuid.UUID,
        user_id: uuid.UUID,
        session_id: uuid.UUID | None = None,
    ) -> list[ChatMessageResponse]:
        meeting = await self.meeting_repo.get_by_id(meeting_id=meeting_id, user_id=user_id)
        if meeting is None:
            raise ValueError("Meeting not found")

        transcript = await self.transcript_repo.get_by_meeting_id(
            meeting_id=meeting_id, user_id=user_id
        )
        segment_map: dict[uuid.UUID, TranscriptSegment] = {}
        if transcript:
            segs = await self.transcript_repo.get_segments_by_transcript(transcript.id)
            segment_map = {s.id: s for s in segs}

        messages = await self.chat_repo.get_messages_by_meeting(
            meeting_id=meeting_id,
            user_id=user_id,
            session_id=session_id,
        )

        results: list[ChatMessageResponse] = []
        for m in messages:
            citations: list[ChatCitation] = []
            for cid in m.citation_segment_ids or []:
                if cid in segment_map:
                    seg = segment_map[cid]
                    citations.append(
                        ChatCitation(
                            segment_id=seg.id,
                            start_time=seg.start_time,
                            end_time=seg.end_time,
                            speaker=seg.speaker or seg.speaker_label,
                            text_snippet=seg.text[:120] if seg.text else None,
                        )
                    )
            citations.sort(key=lambda c: c.start_time)
            results.append(
                ChatMessageResponse(
                    message_id=m.id,
                    session_id=m.session_id,
                    meeting_id=m.meeting_id,
                    role=m.role.value,
                    content=m.content,
                    citations=citations,
                    created_at=m.created_at.isoformat(),
                )
            )
        return results
