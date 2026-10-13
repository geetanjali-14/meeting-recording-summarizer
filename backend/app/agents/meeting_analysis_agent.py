import logging
from typing import Any

from pydantic import ValidationError

from app.core.config import Settings
from app.prompts.meeting_analysis_prompt import (
    SYSTEM_ANALYSIS_INSTRUCTIONS,
    format_transcript_prompt,
)
from app.providers.llm.base import LLMProvider, LLMProviderError, LLMResponse
from app.schemas.analysis import MeetingAnalysisOutput

logger = logging.getLogger(__name__)


class MeetingAnalysisAgentError(Exception):
    """Exception raised by MeetingAnalysisAgent during extraction."""

    def __init__(self, message: str, is_retryable: bool = False) -> None:
        super().__init__(message)
        self.message = message
        self.is_retryable = is_retryable


class MeetingAnalysisAgent:
    """Bounded AI agent transforming timestamped transcript segments into structured intelligence.

    Performs bounded extraction with:
    - Single structured generation call
    - Strict Pydantic schema validation
    - Untrusted transcript encapsulation
    - Automatic JSON repair attempt on validation error
    """

    def __init__(
        self,
        llm_provider: LLMProvider,
        settings: Settings,
    ) -> None:
        self.llm_provider = llm_provider
        self.settings = settings
        self.model = settings.LLM_MODEL
        self.temperature = settings.LLM_TEMPERATURE
        self.max_tokens = settings.LLM_MAX_TOKENS

    def analyze_transcript(
        self,
        segments_data: list[dict[str, Any]],
        model: str | None = None,
    ) -> tuple[MeetingAnalysisOutput, LLMResponse]:
        """Analyzes transcript segments and returns validated MeetingAnalysisOutput
        together with the raw LLM response metadata.
        """
        chosen_model = model or self.model
        if not segments_data:
            # Empty transcript edge case
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
            )
            dummy_response = self.llm_provider.generate_structured(
                messages=[{"role": "user", "content": "empty"}],
                model=chosen_model,
            )
            return output, dummy_response

        user_content = format_transcript_prompt(segments_data)
        messages = [
            {"role": "system", "content": SYSTEM_ANALYSIS_INSTRUCTIONS},
            {"role": "user", "content": user_content},
        ]

        try:
            llm_response = self.llm_provider.generate_structured(
                messages=messages,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                model=chosen_model,
            )
        except LLMProviderError as exc:
            raise MeetingAnalysisAgentError(
                f"LLM extraction call failed: {exc.message}",
                is_retryable=exc.is_retryable,
            ) from exc

        # Validate against schema
        try:
            validated_output = MeetingAnalysisOutput.model_validate(llm_response.parsed_json)
            return validated_output, llm_response
        except ValidationError as val_err:
            logger.warning(
                "First attempt failed schema validation: %s. Attempting repair retry.",
                val_err,
            )
            # Attempt a single repair retry
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
            try:
                repaired_response = self.llm_provider.generate_structured(
                    messages=repair_messages,
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                    model=chosen_model,
                )
                repaired_json = repaired_response.parsed_json
                validated_output = MeetingAnalysisOutput.model_validate(repaired_json)
                return validated_output, repaired_response
            except Exception as repair_exc:
                raise MeetingAnalysisAgentError(
                    f"Structured schema validation failed after repair: {repair_exc}",
                    is_retryable=False,
                ) from repair_exc
