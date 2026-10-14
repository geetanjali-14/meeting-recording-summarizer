import logging
from typing import Any

from app.core.config import Settings
from app.prompts.meeting_analysis_prompt import SYSTEM_VERIFICATION_INSTRUCTIONS
from app.providers.llm.base import LLMProvider, LLMProviderError
from app.schemas.analysis import ActionItemOutput, DecisionConfidence, DecisionOutput

logger = logging.getLogger(__name__)


class VerificationAgent:
    """Selective targeted verification agent validating ambiguous or ungrounded claims.

    Invoked only when deterministic checks flag:
    - An action item with an assigned owner whose name does not appear in cited segments
    - A decision marked as INFERRED without explicit lexical support
    """

    def __init__(self, llm_provider: LLMProvider, settings: Settings) -> None:
        self.llm_provider = llm_provider
        self.settings = settings
        self.model = settings.LLM_MODEL

    def verify_action_item_owner(
        self,
        action_item: ActionItemOutput,
        cited_segments: list[dict[str, Any]],
    ) -> bool:
        """Determines if the assigned owner is grounded in cited segments."""
        if not action_item.owner or not cited_segments:
            return True

        # Deterministic check first: check if owner name substring is in segment text
        owner_lower = action_item.owner.lower()
        has_lexical_match = any(
            owner_lower in s.get("text", "").lower()
            or owner_lower in (s.get("speaker") or "").lower()
            or owner_lower in (s.get("speaker_label") or "").lower()
            for s in cited_segments
        )
        if has_lexical_match:
            return True

        # Ambiguous claim flagged -> Targeted verification LLM call
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
