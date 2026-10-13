import uuid
from unittest.mock import MagicMock

import pytest

from app.agents.meeting_analysis_agent import (
    MeetingAnalysisAgent,
    MeetingAnalysisAgentError,
)
from app.core.config import Settings
from app.providers.llm.base import (
    LLMProvider,
    LLMProviderError,
    LLMResponse,
    LLMUsage,
)


def test_meeting_analysis_agent_empty_transcript() -> None:
    mock_provider = MagicMock(spec=LLMProvider)
    settings = Settings(LLM_MODEL="gpt-oss-120b")
    agent = MeetingAnalysisAgent(mock_provider, settings)

    output, _ = agent.analyze_transcript([])
    assert "No speech or discussion" in output.executive_summary
    assert output.topics == []
    assert output.decisions == []
    assert output.action_items == []


def test_meeting_analysis_agent_structured_extraction() -> None:
    mock_provider = MagicMock(spec=LLMProvider)
    settings = Settings(LLM_MODEL="gpt-oss-120b")
    agent = MeetingAnalysisAgent(mock_provider, settings)

    seg_id = uuid.uuid4()
    mock_provider.generate_structured.return_value = LLMResponse(
        provider="groq",
        model="openai/gpt-oss-120b",
        content="{}",
        parsed_json={
            "title": "Architecture Sync",
            "executive_summary": "Team aligned on PostgreSQL and background worker leases.",
            "topics": [
                {
                    "title": "Database Choice",
                    "summary": "Agreed on PostgreSQL from day one.",
                    "sequence_index": 0,
                    "evidence_segment_ids": [str(seg_id)],
                }
            ],
            "decisions": [
                {
                    "decision_text": "Adopt PostgreSQL from day one.",
                    "confidence": "EXPLICIT",
                    "sequence_index": 0,
                    "evidence_segment_ids": [str(seg_id)],
                }
            ],
            "action_items": [
                {
                    "action_text": "Write Alembic migration.",
                    "owner": "Alice",
                    "due_date": None,
                    "sequence_index": 0,
                    "evidence_segment_ids": [str(seg_id)],
                }
            ],
            "risks": [],
            "open_questions": [],
        },
        usage=LLMUsage(prompt_tokens=100, completion_tokens=50, total_tokens=150),
    )

    segments_input = [
        {
            "segment_id": str(seg_id),
            "sequence_index": 0,
            "start_time": 0.0,
            "end_time": 4.5,
            "speaker": "Alice",
            "text": "We will deploy PostgreSQL.",
        }
    ]

    output, response = agent.analyze_transcript(segments_input)

    assert output.title == "Architecture Sync"
    assert len(output.decisions) == 1
    assert output.decisions[0].evidence_segment_ids == [seg_id]
    assert output.action_items[0].owner == "Alice"
    assert output.action_items[0].due_date is None
    assert response.usage.total_tokens == 150


def test_meeting_analysis_agent_provider_failure_raises() -> None:
    mock_provider = MagicMock(spec=LLMProvider)
    mock_provider.generate_structured.side_effect = LLMProviderError(
        "Rate limit exceeded", is_retryable=True
    )
    settings = Settings(LLM_MODEL="gpt-oss-120b")
    agent = MeetingAnalysisAgent(mock_provider, settings)

    with pytest.raises(MeetingAnalysisAgentError) as exc_info:
        agent.analyze_transcript([{"segment_id": str(uuid.uuid4()), "text": "Hi"}])

    assert "Rate limit exceeded" in str(exc_info.value)
    assert exc_info.value.is_retryable is True
