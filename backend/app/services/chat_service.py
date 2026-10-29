import asyncio
import logging
import math
import random
import re
import uuid
from datetime import UTC, datetime
from typing import Any

from app.core.config import Settings
from app.models.chat import ChatRole
from app.models.transcript import TranscriptSegment
from app.providers.llm.base import LLMProvider, LLMProviderError, LLMResponse
from app.repositories.chat_repository import ChatRepository
from app.repositories.meeting_repository import MeetingRepository
from app.repositories.transcript_repository import TranscriptRepository
from app.schemas.chat import ChatCitation, ChatMessageResponse, ChatResponse

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """<SYSTEM_INSTRUCTIONS>
You are an objective, highly accurate Meeting Intelligence Q&A Assistant.
Answer the user's question accurately using the evidence presented in the transcript dialogue.

Adhere strictly to the following rules:

1. MEETING OVERVIEW & PURPOSE:
   - When asked what the meeting was about, what its goal, purpose, agenda, or motto was, provide a clear, concise summary of the primary topics, objectives, and discussions reasonably supported by the transcript.
   - Do NOT require participants to have explicitly used literal keywords like "purpose", "motto", "objective", or "agenda". Infer the meeting's general purpose from the context of what was introduced and discussed.

2. DECISIONS & ACTION ITEMS:
   - Accurately distinguish confirmed decisions and agreed actions from mere ideas, proposals, brainstorming suggestions, or open questions.
   - For action items, identify the task, the assigned owner (when established), and any deadlines mentioned.

3. REASONABLE SYNTHESIS & QUALIFICATIONS:
   - Synthesize evidence across multiple segments when relevant.
   - Accurately preserve names, numbers, dates, and qualifications.
   - When only part of a question can be answered from the transcript, answer that part clearly and state what details remain unaddressed.

4. MISSING INFORMATION & UNCERTAINTY:
   - If the transcript genuinely does not provide information to answer the question, state:
     "The meeting transcript does not contain information to answer this question."
   - Never fabricate facts, attendees, decisions, actions, dates, or quotations.

5. CITATIONS:
   - In `cited_segment_ids`, include the UUID strings of the specific transcript segments that directly support your answer.
   - If the question cannot be answered from the transcript, return an empty array for `cited_segment_ids`.

6. OUTPUT FORMAT:
   Return your output strictly as a JSON object matching this schema:
   {
     "answer": "string",
     "cited_segment_ids": ["uuid-string", ...]
   }
</SYSTEM_INSTRUCTIONS>"""

# Common stopwords to exclude when scoring segments for keyword relevance
STOP_WORDS = {
    "a", "about", "above", "after", "again", "against", "all", "am", "an", "and", "any", "are",
    "arent", "as", "at", "be", "because", "been", "before", "being", "below", "between", "both",
    "but", "by", "cant", "cannot", "could", "couldnt", "did", "didnt", "do", "does", "doesnt",
    "doing", "dont", "down", "during", "each", "few", "for", "from", "further", "had", "hadnt",
    "has", "hasnt", "have", "havent", "having", "he", "hed", "hell", "hes", "her", "here", "heres",
    "hers", "herself", "him", "himself", "his", "how", "hows", "i", "id", "ill", "im", "ive", "if",
    "in", "into", "is", "isnt", "it", "its", "itself", "lets", "me", "more", "most", "mustnt",
    "my", "myself", "no", "nor", "not", "of", "off", "on", "once", "only", "or", "other", "ought",
    "our", "ours", "ourselves", "out", "over", "own", "same", "shant", "she", "shed", "shell", "shes",
    "should", "shouldnt", "so", "some", "such", "than", "that", "thats", "the", "their", "theirs",
    "them", "themselves", "then", "there", "theres", "these", "they", "theyd", "theyll", "theyre",
    "theyve", "this", "those", "through", "to", "too", "under", "until", "up", "very", "was", "wasnt",
    "we", "wed", "well", "were", "weve", "werent", "what", "whats", "when", "whens", "where", "wheres",
    "which", "while", "who", "whos", "whom", "why", "whys", "with", "wont", "would", "wouldnt",
    "you", "youd", "youll", "youre", "youve", "your", "yours", "yourself", "yourselves"
}

OVERVIEW_KEYWORDS = {
    "about", "overview", "summary", "summarize", "purpose", "goal", "objective",
    "moto", "motto", "agenda", "topic", "discuss", "discussed", "discussion"
}


def estimate_segment_tokens(seg: TranscriptSegment) -> int:
    """Conservatively estimates token count for a formatted transcript segment line."""
    text = seg.text or ""
    metadata_chars = 36 + len(str(seg.speaker or seg.speaker_label or "")) + 24
    total_chars = len(text) + metadata_chars
    return max(5, math.ceil(total_chars / 3.2))


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

    def _select_relevant_segments(
        self,
        segments: list[TranscriptSegment],
        question: str,
        max_token_budget: int = 3500,
    ) -> list[TranscriptSegment]:
        """Selects segments fitting within token budget.

        If total segments fit in budget, returns all segments chronologically.
        Otherwise, intelligently prioritizes key segments (intro/conclusion + keyword matches)
        and preserves chronological order with surrounding context.
        """
        if not segments:
            return []

        token_costs = [estimate_segment_tokens(s) for s in segments]
        total_tokens = sum(token_costs)

        if total_tokens <= max_token_budget:
            return segments

        # High-capacity budget exceeded: perform relevance selection
        q_tokens = re.findall(r"\w+", question.lower())
        content_words = [w for w in q_tokens if w not in STOP_WORDS]
        is_overview = any(w in OVERVIEW_KEYWORDS for w in q_tokens)

        scored_indices: list[tuple[float, int]] = []
        n = len(segments)

        for idx, seg in enumerate(segments):
            score = 0.0
            seg_text = (seg.text or "").lower()

            # Boost opening (first 15%) and closing (last 10%) for overview / general context
            rel_pos = idx / max(1, n - 1)
            if rel_pos <= 0.15:
                score += 3.0 if is_overview else 1.0
            elif rel_pos >= 0.85:
                score += 2.0 if is_overview else 0.5

            # Word matching score
            for cw in content_words:
                if cw in seg_text:
                    score += 5.0

            # Boost action/decision phrases if requested
            if any(k in q_tokens for k in ("decision", "decide", "agreed", "action", "deadline", "todo")):
                if any(k in seg_text for k in ("action", "decide", "agreed", "next step", "deadline", "by next")):
                    score += 4.0

            scored_indices.append((score, idx))

        # Sort by score descending
        scored_indices.sort(key=lambda x: x[0], reverse=True)

        selected_indices: set[int] = set()
        accumulated_tokens = 0

        # Always include first 2 and last 2 segments for structural continuity if possible
        must_have = {0, 1, max(0, n - 2), max(0, n - 1)}
        for m_idx in sorted(must_have):
            if m_idx < n and m_idx not in selected_indices:
                cost = token_costs[m_idx]
                if accumulated_tokens + cost <= max_token_budget:
                    selected_indices.add(m_idx)
                    accumulated_tokens += cost

        # Add top scoring segments and immediate neighbors for context
        for score, idx in scored_indices:
            if idx in selected_indices:
                continue

            cost = token_costs[idx]
            if accumulated_tokens + cost <= max_token_budget:
                selected_indices.add(idx)
                accumulated_tokens += cost

                # Include predecessor/successor for conversational flow if budget permits
                for neighbor in (idx - 1, idx + 1):
                    if 0 <= neighbor < n and neighbor not in selected_indices:
                        n_cost = token_costs[neighbor]
                        if accumulated_tokens + n_cost <= max_token_budget:
                            selected_indices.add(neighbor)
                            accumulated_tokens += n_cost

            if accumulated_tokens >= max_token_budget:
                break

        sorted_indices = sorted(selected_indices)
        return [segments[i] for i in sorted_indices]

    async def _call_llm_with_retry(
        self,
        messages: list[dict[str, str]],
        json_schema: dict[str, Any],
        max_retries: int | None = None,
        base_delay_seconds: float = 1.0,
        max_total_budget_seconds: float = 20.0,
    ) -> LLMResponse:
        """Executes LLM call with bounded exponential backoff on transient errors (429/5xx)."""
        retries_limit = max_retries if max_retries is not None else getattr(self.settings, "LLM_MAX_RETRIES", 2)
        attempt = 0
        elapsed_time = 0.0
        start_time = datetime.now(UTC).timestamp()

        while True:
            attempt += 1
            try:
                # LLMProvider.generate_structured is synchronous; run in executor to keep event loop free
                return await asyncio.to_thread(
                    self.llm_provider.generate_structured,
                    messages=messages,
                    json_schema=json_schema,
                    temperature=0.0,
                    model=self.settings.LLM_MODEL,
                )
            except LLMProviderError as exc:
                now = datetime.now(UTC).timestamp()
                elapsed_time = now - start_time

                # Check if retryable and within attempt limit and elapsed budget
                if exc.is_retryable and attempt <= retries_limit:
                    sleep_time = exc.retry_after if (exc.retry_after is not None and exc.retry_after > 0) else None
                    if sleep_time is None:
                        jitter = random.uniform(0.1, 0.4)
                        sleep_time = (base_delay_seconds * (2 ** (attempt - 1))) + jitter
                    else:
                        sleep_time = min(sleep_time + random.uniform(0.1, 0.3), 15.0)

                    if elapsed_time + sleep_time > max_total_budget_seconds:
                        logger.warning(
                            "LLM retry budget exceeded (elapsed: %.2fs + wait: %.2fs > budget: %.2fs)",
                            elapsed_time,
                            sleep_time,
                            max_total_budget_seconds,
                        )
                        raise

                    logger.warning(
                        "LLM transient error on chat (attempt %d/%d, status=%s): %s. Backing off for %.2fs",
                        attempt,
                        retries_limit + 1,
                        exc.status_code,
                        exc.message,
                        sleep_time,
                    )
                    await asyncio.sleep(sleep_time)
                else:
                    raise

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

        # 5. Format dialogue with budget-aware segment selection
        selected_segments = self._select_relevant_segments(
            segments=segments,
            question=question,
            max_token_budget=3500,
        )

        formatted_segments = []
        for seg in selected_segments:
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
            llm_response = await self._call_llm_with_retry(
                messages=messages,
                json_schema=schema,
            )
            data = llm_response.parsed_json or {}
            answer_text = data.get("answer", "")
            raw_citations = data.get("cited_segment_ids", [])
            if not answer_text:
                answer_text = "The meeting transcript does not contain information to answer this question."
        except LLMProviderError as exc:
            logger.error(
                "LLM provider error in chat service: status=%s retryable=%s msg=%s",
                exc.status_code,
                exc.is_retryable,
                exc.message,
            )
            if exc.status_code == 429:
                answer_text = (
                    "The AI service is currently experiencing high demand. Please try asking again in a moment."
                )
            else:
                answer_text = "I am unable to answer this question at this time due to an error."
            raw_citations = []
        except Exception:
            logger.error("Unexpected failure during chat answering", exc_info=True)
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
