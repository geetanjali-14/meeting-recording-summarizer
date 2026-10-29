import logging
import random
import time
import uuid
from typing import Any

from pydantic import ValidationError

from app.core.config import Settings
from app.prompts.meeting_analysis_prompt import (
    SYSTEM_ANALYSIS_INSTRUCTIONS,
    SYSTEM_CHUNK_ANALYSIS_INSTRUCTIONS,
    SYSTEM_SYNTHESIS_INSTRUCTIONS,
    format_synthesis_prompt,
    format_transcript_prompt,
)
from app.providers.llm.base import LLMProvider, LLMProviderError, LLMResponse, LLMUsage
from app.schemas.analysis import (
    ActionItemOutput,
    ChunkAnalysisOutput,
    DecisionConfidence,
    DecisionOutput,
    MeetingAnalysisOutput,
    OpenQuestionOutput,
    RiskOutput,
    TopicOutput,
)
from app.services.transcript_chunker import TranscriptChunk, TranscriptChunker

logger = logging.getLogger(__name__)


class MeetingAnalysisAgentError(Exception):
    """Exception raised by MeetingAnalysisAgent during extraction."""

    def __init__(self, message: str, is_retryable: bool = False) -> None:
        super().__init__(message)
        self.message = message
        self.is_retryable = is_retryable


class MeetingAnalysisAgent:
    """Bounded AI agent supporting long-transcript chunking, structured extraction,
    hierarchical synthesis, and completeness tracking within provider rate limits.
    """

    def __init__(
        self,
        llm_provider: LLMProvider,
        settings: Settings,
        chunker: TranscriptChunker | None = None,
    ) -> None:
        self.llm_provider = llm_provider
        self.settings = settings
        self.model = settings.LLM_MODEL
        self.temperature = settings.LLM_TEMPERATURE
        self.max_tokens = settings.LLM_MAX_TOKENS
        # Conservative chunker: 2500 max prompt tokens for transcript text
        self.chunker = chunker or TranscriptChunker(
            max_prompt_tokens=2500,
            overlap_tokens=300,
            system_prompt_tokens=500,
        )
        self.last_chunk_findings: list[dict[str, Any]] = []

    def _call_with_backoff(
        self,
        messages: list[dict[str, str]],
        model: str,
        max_retries: int = 3,
        base_delay_seconds: float = 2.0,
    ) -> LLMResponse:
        """Executes LLM call with backoff on transient 429 rate limit or 5xx server errors."""
        attempt = 0
        last_exc: Exception | None = None

        while attempt < max_retries:
            attempt += 1
            try:
                return self.llm_provider.generate_structured(
                    messages=messages,
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                    model=model,
                )
            except LLMProviderError as exc:
                last_exc = exc
                if exc.is_retryable and attempt < max_retries:
                    # Respect retry_after from provider if present, else backoff + jitter
                    if exc.retry_after is not None and exc.retry_after > 0:
                        sleep_time = exc.retry_after + random.uniform(0.1, 0.5)
                    else:
                        jitter = random.uniform(0.1, 0.5)
                        sleep_time = (base_delay_seconds * (2 ** (attempt - 1))) + jitter

                    logger.warning(
                        "LLM transient error (attempt %d/%d): %s. Backing off for %.2fs",
                        attempt,
                        max_retries,
                        exc.message,
                        sleep_time,
                    )
                    time.sleep(sleep_time)
                else:
                    raise MeetingAnalysisAgentError(
                        f"LLM extraction call failed: {exc.message}",
                        is_retryable=exc.is_retryable,
                    ) from exc

        raise MeetingAnalysisAgentError(
            f"LLM call failed after {max_retries} attempts: {last_exc}",
            is_retryable=getattr(last_exc, "is_retryable", False),
        )

    def _extract_chunk(
        self,
        chunk: TranscriptChunk,
        model: str,
    ) -> tuple[ChunkAnalysisOutput, LLMResponse]:
        """Extracts structured intelligence for an individual transcript chunk."""
        chunk_info = (
            f"Chunk {chunk.chunk_index + 1} of {chunk.total_chunks} "
            f"[{chunk.start_time:.1f}s - {chunk.end_time:.1f}s]"
        )
        user_content = format_transcript_prompt(chunk.segments, chunk_info=chunk_info)
        messages = [
            {"role": "system", "content": SYSTEM_CHUNK_ANALYSIS_INSTRUCTIONS},
            {"role": "user", "content": user_content},
        ]

        llm_response = self._call_with_backoff(messages=messages, model=model)

        try:
            parsed = ChunkAnalysisOutput.model_validate(llm_response.parsed_json)
            return parsed, llm_response
        except ValidationError as val_err:
            logger.warning(
                "Chunk %d failed schema validation: %s. Attempting repair.",
                chunk.chunk_index,
                val_err,
            )
            repair_messages = list(messages)
            repair_messages.append({"role": "assistant", "content": llm_response.content})
            repair_messages.append(
                {
                    "role": "user",
                    "content": (
                        f"Your output had schema validation errors: {val_err}. "
                        "Please output strictly valid JSON matching the schema."
                    ),
                }
            )
            repaired_response = self._call_with_backoff(messages=repair_messages, model=model)
            parsed = ChunkAnalysisOutput.model_validate(repaired_response.parsed_json)
            return parsed, repaired_response

    def _synthesize_chunks(
        self,
        chunk_findings: list[dict[str, Any]],
        model: str,
    ) -> tuple[MeetingAnalysisOutput, LLMResponse]:
        """Synthesizes extracted chunk findings into a unified, coherent meeting record."""
        synthesis_prompt = format_synthesis_prompt(chunk_findings)
        messages = [
            {"role": "system", "content": SYSTEM_SYNTHESIS_INSTRUCTIONS},
            {"role": "user", "content": synthesis_prompt},
        ]

        llm_response = self._call_with_backoff(messages=messages, model=model)

        try:
            output = MeetingAnalysisOutput.model_validate(llm_response.parsed_json)
            return output, llm_response
        except ValidationError as val_err:
            logger.warning("Synthesis failed schema validation: %s. Attempting repair.", val_err)
            repair_messages = list(messages)
            repair_messages.append({"role": "assistant", "content": llm_response.content})
            repair_messages.append(
                {
                    "role": "user",
                    "content": (
                        f"Your synthesis had schema validation errors: {val_err}. "
                        "Please output strictly valid JSON matching the schema."
                    ),
                }
            )
            repaired_response = self._call_with_backoff(messages=repair_messages, model=model)
            output = MeetingAnalysisOutput.model_validate(repaired_response.parsed_json)
            return output, repaired_response

    def analyze_transcript(
        self,
        segments_data: list[dict[str, Any]],
        model: str | None = None,
    ) -> tuple[MeetingAnalysisOutput, LLMResponse]:
        """Analyzes transcript segments using context-aware chunking and hierarchical synthesis."""
        chosen_model = model or self.model
        self.last_chunk_findings = []
        if not segments_data:
            output = MeetingAnalysisOutput(
                title=None,
                executive_summary=(
                    "No speech or discussion content recorded in the meeting transcript."
                ),
                topics=[],
                decisions=[],
                action_items=[],
                risks=[],
                open_questions=[],
                speaker_contributions={},
                context_and_details=[],
                next_steps=[],
                chunk_count=0,
                analyzed_segment_count=0,
                coverage_percentage=100.0,
            )
            dummy_response = self.llm_provider.generate_structured(
                messages=[{"role": "user", "content": "empty transcript json: {}"}],
                model=chosen_model,
            )
            return output, dummy_response

        # Partition transcript into token-bounded chunks
        chunks = self.chunker.chunk_segments(segments_data)

        # Single chunk path: directly extract full meeting analysis
        if len(chunks) == 1:
            user_content = format_transcript_prompt(segments_data)
            messages = [
                {"role": "system", "content": SYSTEM_ANALYSIS_INSTRUCTIONS},
                {"role": "user", "content": user_content},
            ]
            try:
                llm_response = self._call_with_backoff(messages=messages, model=chosen_model)
                validated_output = MeetingAnalysisOutput.model_validate(llm_response.parsed_json)
                validated_output.chunk_count = 1
                validated_output.analyzed_segment_count = len(segments_data)
                validated_output.coverage_percentage = 100.0
                self.last_chunk_findings = [
                    {
                        "chunk_index": 0,
                        "start_time": chunks[0].start_time,
                        "end_time": chunks[0].end_time,
                        "topics": [t.model_dump() for t in validated_output.topics],
                        "decisions": [d.model_dump() for d in validated_output.decisions],
                        "action_items": [a.model_dump() for a in validated_output.action_items],
                        "risks": [r.model_dump() for r in validated_output.risks],
                        "open_questions": [q.model_dump() for q in validated_output.open_questions],
                        "speaker_contributions": validated_output.speaker_contributions,
                        "context_and_details": validated_output.context_and_details,
                        "next_steps": validated_output.next_steps,
                    }
                ]
                return validated_output, llm_response
            except ValidationError as val_err:
                logger.warning(
                    "First attempt failed schema validation: %s. Attempting repair retry.", val_err
                )
                repair_messages = list(messages)
                repair_messages.append({"role": "assistant", "content": llm_response.content})
                repair_messages.append(
                    {
                        "role": "user",
                        "content": (
                            f"Your output had schema validation errors: {val_err}. "
                            "Please output strictly valid JSON matching the schema."
                        ),
                    }
                )
                repaired_response = self._call_with_backoff(
                    messages=repair_messages, model=chosen_model
                )
                validated_output = MeetingAnalysisOutput.model_validate(
                    repaired_response.parsed_json
                )
                validated_output.chunk_count = 1
                validated_output.analyzed_segment_count = len(segments_data)
                validated_output.coverage_percentage = 100.0
                self.last_chunk_findings = [
                    {
                        "chunk_index": 0,
                        "start_time": chunks[0].start_time,
                        "end_time": chunks[0].end_time,
                        "topics": [t.model_dump() for t in validated_output.topics],
                        "decisions": [d.model_dump() for d in validated_output.decisions],
                        "action_items": [a.model_dump() for a in validated_output.action_items],
                        "risks": [r.model_dump() for r in validated_output.risks],
                        "open_questions": [q.model_dump() for q in validated_output.open_questions],
                        "speaker_contributions": validated_output.speaker_contributions,
                        "context_and_details": validated_output.context_and_details,
                        "next_steps": validated_output.next_steps,
                    }
                ]
                return validated_output, repaired_response

        # Multi-chunk hierarchical pipeline
        logger.info(
            "Analyzing long transcript across %d chunks using hierarchical synthesis",
            len(chunks),
        )

        total_prompt_tokens = 0
        total_completion_tokens = 0
        chunk_findings: list[dict[str, Any]] = []
        covered_segment_ids: set[str] = set()

        for idx, chunk in enumerate(chunks):
            chunk_out, resp = self._extract_chunk(chunk, chosen_model)
            total_prompt_tokens += resp.usage.prompt_tokens
            total_completion_tokens += resp.usage.completion_tokens

            covered_segment_ids.update(chunk.primary_segment_ids)
            chunk_findings.append(
                {
                    "chunk_index": idx,
                    "start_time": chunk.start_time,
                    "end_time": chunk.end_time,
                    "topics": [t.model_dump() for t in chunk_out.topics],
                    "decisions": [d.model_dump() for d in chunk_out.decisions],
                    "action_items": [a.model_dump() for a in chunk_out.action_items],
                    "risks": [r.model_dump() for r in chunk_out.risks],
                    "open_questions": [q.model_dump() for q in chunk_out.open_questions],
                    "speaker_contributions": chunk_out.speaker_contributions,
                    "context_and_details": chunk_out.context_and_details,
                    "next_steps": chunk_out.next_steps,
                }
            )

            # Small pause between chunks to respect Groq rate limits
            if idx < len(chunks) - 1:
                time.sleep(1.0)

        # Synthesize merged findings
        final_output, synth_resp = self._synthesize_chunks(chunk_findings, chosen_model)
        total_prompt_tokens += synth_resp.usage.prompt_tokens
        total_completion_tokens += synth_resp.usage.completion_tokens

        # If synthesis produced an empty list for any category that had chunk findings,
        # fallback to combining chunk findings so zero material intelligence is lost
        self._ensure_chunk_items_preserved(final_output, chunk_findings)

        total_segs = len(segments_data)
        cov_pct = (
            round((len(covered_segment_ids) / total_segs * 100.0), 1) if total_segs > 0 else 100.0
        )
        final_output.chunk_count = len(chunks)
        final_output.analyzed_segment_count = len(covered_segment_ids)
        final_output.coverage_percentage = cov_pct

        aggregated_usage = LLMUsage(
            prompt_tokens=total_prompt_tokens,
            completion_tokens=total_completion_tokens,
            total_tokens=total_prompt_tokens + total_completion_tokens,
        )
        combined_response = LLMResponse(
            provider=synth_resp.provider,
            model=chosen_model,
            content=synth_resp.content,
            parsed_json=final_output.model_dump(),
            usage=aggregated_usage,
        )

        self.last_chunk_findings = chunk_findings
        return final_output, combined_response

    def _ensure_chunk_items_preserved(
        self,
        final_output: MeetingAnalysisOutput,
        chunk_findings: list[dict[str, Any]],
    ) -> None:
        """Guarantees that material items extracted in chunks are not dropped during synthesis."""
        # 1. Decisions
        all_chunk_decisions = [d for cf in chunk_findings for d in cf.get("decisions", [])]
        if all_chunk_decisions and not final_output.decisions:
            for d in all_chunk_decisions:
                final_output.decisions.append(
                    DecisionOutput(
                        decision_text=d.get("decision_text", ""),
                        confidence=DecisionConfidence(d.get("confidence", "EXPLICIT")),
                        evidence_segment_ids=[
                            uuid.UUID(str(sid)) for sid in d.get("evidence_segment_ids", []) if sid
                        ],
                    )
                )

        # 2. Action Items
        all_chunk_actions = [a for cf in chunk_findings for a in cf.get("action_items", [])]
        if all_chunk_actions and not final_output.action_items:
            for a in all_chunk_actions:
                final_output.action_items.append(
                    ActionItemOutput(
                        action_text=a.get("action_text", ""),
                        owner=a.get("owner"),
                        due_date=a.get("due_date"),
                        evidence_segment_ids=[
                            uuid.UUID(str(sid)) for sid in a.get("evidence_segment_ids", []) if sid
                        ],
                    )
                )

        # 3. Topics
        all_chunk_topics = [t for cf in chunk_findings for t in cf.get("topics", [])]
        if all_chunk_topics and not final_output.topics:
            for t in all_chunk_topics:
                final_output.topics.append(
                    TopicOutput(
                        title=t.get("title", "Topic"),
                        summary=t.get("summary", ""),
                        discussion_progression=t.get("discussion_progression"),
                        evidence_segment_ids=[
                            uuid.UUID(str(sid)) for sid in t.get("evidence_segment_ids", []) if sid
                        ],
                    )
                )

        # 4. Risks
        all_chunk_risks = [r for cf in chunk_findings for r in cf.get("risks", [])]
        if all_chunk_risks and not final_output.risks:
            for r in all_chunk_risks:
                final_output.risks.append(
                    RiskOutput(
                        risk_text=r.get("risk_text", ""),
                        evidence_segment_ids=[
                            uuid.UUID(str(sid)) for sid in r.get("evidence_segment_ids", []) if sid
                        ],
                    )
                )

        # 5. Open Questions
        all_chunk_questions = [q for cf in chunk_findings for q in cf.get("open_questions", [])]
        if all_chunk_questions and not final_output.open_questions:
            for q in all_chunk_questions:
                final_output.open_questions.append(
                    OpenQuestionOutput(
                        question_text=q.get("question_text", ""),
                        evidence_segment_ids=[
                            uuid.UUID(str(sid)) for sid in q.get("evidence_segment_ids", []) if sid
                        ],
                    )
                )

        # 6. Speaker Contributions merge fallback
        if not final_output.speaker_contributions:
            merged_contribs: dict[str, dict[str, list[str]]] = {}
            for cf in chunk_findings:
                sc = cf.get("speaker_contributions", {})
                for spk, data in sc.items():
                    if spk not in merged_contribs:
                        merged_contribs[spk] = {"contributions": [], "proposals": [], "concerns": [], "commitments": []}
                    for k in ["contributions", "proposals", "concerns", "commitments"]:
                        for item in data.get(k, []):
                            if item not in merged_contribs[spk][k]:
                                merged_contribs[spk][k].append(item)
            final_output.speaker_contributions = merged_contribs

        # 7. Context & Details fallback
        if not final_output.context_and_details:
            all_details = [dt for cf in chunk_findings for dt in cf.get("context_and_details", [])]
            final_output.context_and_details = all_details

        # 8. Next Steps fallback
        if not final_output.next_steps:
            all_steps = [ns for cf in chunk_findings for ns in cf.get("next_steps", [])]
            final_output.next_steps = all_steps

        # 9. Re-index sequence indices deterministically
        for idx, t in enumerate(final_output.topics):
            t.sequence_index = idx
        for idx, d in enumerate(final_output.decisions):
            d.sequence_index = idx
        for idx, a in enumerate(final_output.action_items):
            a.sequence_index = idx
        for idx, r in enumerate(final_output.risks):
            r.sequence_index = idx
        for idx, q in enumerate(final_output.open_questions):
            q.sequence_index = idx
