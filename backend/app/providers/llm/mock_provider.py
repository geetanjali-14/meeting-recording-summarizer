import json
from typing import Any

from app.core.config import Settings
from app.providers.llm.base import (
    LLMProvider,
    LLMResponse,
    LLMUsage,
)


class MockLLMProvider(LLMProvider):
    """Deterministic mock LLM provider for unit and integration testing."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings
        self.custom_response: dict[str, Any] | None = None

    def set_mock_response(self, response: dict[str, Any]) -> None:
        self.custom_response = response

    def generate_structured(
        self,
        messages: list[dict[str, str]],
        json_schema: dict[str, Any] | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        model: str | None = None,
    ) -> LLMResponse:
        resolved_model = model or "gpt-oss-120b"
        if self.custom_response is not None:
            parsed = self.custom_response
            content = json.dumps(parsed)
        else:
            parsed = {
                "title": "Database Architecture Review",
                "executive_summary": (
                    "The team reviewed database migration architecture. "
                    "They decided to deploy PostgreSQL from day one with renewable worker leases. "
                    "Action items were assigned for schema creation."
                ),
                "topics": [
                    {
                        "title": "Database Architecture",
                        "summary": "Mandatory PostgreSQL adoption from Phase 1.",
                        "sequence_index": 0,
                        "evidence_segment_ids": [],
                    }
                ],
                "decisions": [
                    {
                        "decision_text": "Adopt PostgreSQL with renewable worker leases.",
                        "confidence": "EXPLICIT",
                        "sequence_index": 0,
                        "evidence_segment_ids": [],
                    }
                ],
                "action_items": [
                    {
                        "action_text": "Create Alembic migration for transcript segments.",
                        "owner": "Alice",
                        "due_date": "Friday",
                        "sequence_index": 0,
                        "evidence_segment_ids": [],
                    }
                ],
                "risks": [
                    {
                        "risk_text": "Worker crash could orphan leases without heartbeat renewal.",
                        "sequence_index": 0,
                        "evidence_segment_ids": [],
                    }
                ],
                "open_questions": [
                    {
                        "question_text": "Should we benchmark faster-whisper locally?",
                        "sequence_index": 0,
                        "evidence_segment_ids": [],
                    }
                ],
            }
            content = json.dumps(parsed)

        return LLMResponse(
            provider="mock",
            model=resolved_model,
            content=content,
            parsed_json=parsed,
            usage=LLMUsage(prompt_tokens=150, completion_tokens=80, total_tokens=230),
        )
