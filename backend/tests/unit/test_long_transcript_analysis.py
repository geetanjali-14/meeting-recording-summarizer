import uuid
from unittest.mock import MagicMock, patch

import pytest

from app.agents.meeting_analysis_agent import MeetingAnalysisAgent, MeetingAnalysisAgentError
from app.agents.verification_agent import VerificationAgent
from app.core.config import Settings
from app.providers.llm.base import LLMProvider, LLMProviderError, LLMResponse, LLMUsage
from app.schemas.analysis import (
    ActionItemOutput,
    DecisionConfidence,
    DecisionOutput,
    MeetingAnalysisOutput,
)
from app.services.transcript_chunker import (
    TranscriptChunker,
    estimate_segment_tokens,
)


def test_chunker_partitions_large_transcript_covering_all_segments() -> None:
    """Verify that a large transcript exceeding max_prompt_tokens is partitioned into
    multiple chunks and every segment is covered as a primary member in exactly one chunk.
    """
    chunker = TranscriptChunker(max_prompt_tokens=200, overlap_tokens=50)

    # Create 20 segments (~30 tokens each, total ~600 tokens -> should create 3-4 chunks)
    segments = [
        {
            "id": f"seg-{i:03d}",
            "start_time": float(i * 10),
            "end_time": float((i + 1) * 10),
            "speaker": f"Speaker_{i % 3}",
            "text": f"This is discussion segment number {i} with some meaningful project details.",
        }
        for i in range(20)
    ]

    chunks = chunker.chunk_segments(segments)
    assert len(chunks) > 1

    # Verify coverage: union of primary segment IDs must exactly equal input segment IDs
    all_primary_ids = []
    for c in chunks:
        all_primary_ids.extend(c.primary_segment_ids)

    expected_ids = [s["id"] for s in segments]
    assert all_primary_ids == expected_ids
    assert len(all_primary_ids) == len(set(all_primary_ids))  # No duplicate primary assignments


def test_chunker_boundary_overlap() -> None:
    """Verify that chunks after the first contain overlap context from previous chunks."""
    chunker = TranscriptChunker(max_prompt_tokens=150, overlap_tokens=60)
    segments = [
        {
            "id": f"seg-{i:02d}",
            "start_time": float(i * 5),
            "end_time": float((i + 1) * 5),
            "speaker": "Speaker_00",
            "text": f"Sentence number {i} talking about roadmap milestones.",
        }
        for i in range(12)
    ]

    chunks = chunker.chunk_segments(segments)
    assert len(chunks) >= 2

    # Chunk 1 should have more all_segment_ids than primary_segment_ids due to overlap
    for idx, c in enumerate(chunks[1:], start=1):
        assert len(c.all_segment_ids) > len(c.primary_segment_ids)
        # The first segment in all_segment_ids should come from chunk idx-1's primary segments
        prev_primary = chunks[idx - 1].primary_segment_ids
        assert c.all_segment_ids[0] in prev_primary


def test_chunker_edge_cases() -> None:
    """Verify empty transcripts, single-segment, long segments, and malformed timestamps."""
    chunker = TranscriptChunker(max_prompt_tokens=100, overlap_tokens=20)

    # 1. Empty transcript
    assert chunker.chunk_segments([]) == []

    # 2. Single segment
    single = [{"id": "s1", "start_time": 0.0, "end_time": 5.0, "text": "Hello world"}]
    chunks = chunker.chunk_segments(single)
    assert len(chunks) == 1
    assert chunks[0].primary_segment_ids == ["s1"]

    # 3. Oversized single segment
    long_text = "word " * 500  # ~500 tokens, exceeds 100 max_prompt_tokens
    long_segment = [{"id": "s_long", "start_time": 0.0, "end_time": 60.0, "text": long_text}]
    chunks_long = chunker.chunk_segments(long_segment)
    assert len(chunks_long) > 1
    # Primary IDs must still report s_long
    for cl in chunks_long:
        assert "s_long" in cl.primary_segment_ids

    # 4. Malformed timestamps
    malformed = [
        {"id": "m1", "start_time": "invalid", "end_time": None, "text": "Segment one"},
        {"id": "m2", "start_time": None, "end_time": "bad", "text": "Segment two"},
    ]
    chunks_mal = chunker.chunk_segments(malformed)
    assert len(chunks_mal) == 1
    assert chunks_mal[0].start_time == 0.0
    assert chunks_mal[0].end_time == 0.0


def test_hierarchical_synthesis_multi_chunk_flow() -> None:
    """Verify end-to-end multi-chunk analysis: chunks are extracted and then synthesized."""
    mock_provider = MagicMock(spec=LLMProvider)

    # Responses:
    # Call 1 (Chunk 1 extraction)
    chunk1_json = {
        "topics": [
            {
                "title": "Q3 Budget Review",
                "summary": "Reviewed marketing expenses.",
                "evidence_segment_ids": [str(uuid.uuid4())],
            }
        ],
        "decisions": [
            {
                "decision_text": "Allocate $50k to Q3 campaign",
                "confidence": "EXPLICIT",
                "evidence_segment_ids": [str(uuid.uuid4())],
            }
        ],
        "action_items": [
            {
                "action_text": "Finalize agency contract",
                "owner": "Sarah",
                "due_date": "Friday",
                "evidence_segment_ids": [str(uuid.uuid4())],
            }
        ],
        "risks": [{"risk_text": "Vendor delay", "evidence_segment_ids": []}],
        "open_questions": [],
    }
    # Call 2 (Chunk 2 extraction)
    chunk2_json = {
        "topics": [
            {
                "title": "Product Launch Timeline",
                "summary": "Discussed beta rollout date.",
                "evidence_segment_ids": [str(uuid.uuid4())],
            }
        ],
        "decisions": [
            {
                "decision_text": "Shift launch to November 15",
                "confidence": "EXPLICIT",
                "evidence_segment_ids": [str(uuid.uuid4())],
            }
        ],
        "action_items": [
            {
                "action_text": "Send release notes to beta testers",
                "owner": "Dave",
                "due_date": "Next Monday",
                "evidence_segment_ids": [str(uuid.uuid4())],
            }
        ],
        "risks": [{"risk_text": "Server capacity limit", "evidence_segment_ids": []}],
        "open_questions": [
            {"question_text": "Do we support SSO at launch?", "evidence_segment_ids": []}
        ],
    }
    # Call 3 (Hierarchical Synthesis)
    synth_json = {
        "title": "Q3 Planning & Launch Strategy",
        "executive_summary": (
            "The team approved a $50k Q3 marketing budget and finalized the launch date "
            "for November 15."
        ),
        "topics": [
            {
                "title": "Q3 Budget Review",
                "summary": "Reviewed marketing expenses and approved $50k.",
                "evidence_segment_ids": [],
            },
            {
                "title": "Product Launch Timeline",
                "summary": "Agreed to shift beta launch to November 15.",
                "evidence_segment_ids": [],
            },
        ],
        "decisions": [
            {
                "decision_text": "Allocate $50k to Q3 campaign",
                "confidence": "EXPLICIT",
                "evidence_segment_ids": [],
            },
            {
                "decision_text": "Shift launch to November 15",
                "confidence": "EXPLICIT",
                "evidence_segment_ids": [],
            },
        ],
        "action_items": [
            {
                "action_text": "Finalize agency contract",
                "owner": "Sarah",
                "due_date": "Friday",
                "evidence_segment_ids": [],
            },
            {
                "action_text": "Send release notes to beta testers",
                "owner": "Dave",
                "due_date": "Next Monday",
                "evidence_segment_ids": [],
            },
        ],
        "risks": [
            {"risk_text": "Vendor delay", "evidence_segment_ids": []},
            {"risk_text": "Server capacity limit", "evidence_segment_ids": []},
        ],
        "open_questions": [
            {"question_text": "Do we support SSO at launch?", "evidence_segment_ids": []}
        ],
    }

    mock_provider.generate_structured.side_effect = [
        LLMResponse(
            provider="groq",
            model="gpt-oss-120b",
            content="",
            parsed_json=chunk1_json,
            usage=LLMUsage(prompt_tokens=100, completion_tokens=50),
        ),
        LLMResponse(
            provider="groq",
            model="gpt-oss-120b",
            content="",
            parsed_json=chunk2_json,
            usage=LLMUsage(prompt_tokens=100, completion_tokens=50),
        ),
        LLMResponse(
            provider="groq",
            model="gpt-oss-120b",
            content="",
            parsed_json=synth_json,
            usage=LLMUsage(prompt_tokens=200, completion_tokens=100),
        ),
    ]

    settings = Settings(LLM_MODEL="gpt-oss-120b")
    chunker = TranscriptChunker(max_prompt_tokens=80, overlap_tokens=20)
    agent = MeetingAnalysisAgent(mock_provider, settings, chunker=chunker)

    segments = [
        {
            "id": f"seg-{i}",
            "start_time": float(i * 5),
            "end_time": float((i + 1) * 5),
            "speaker": "Alice",
            "text": f"Content item {i}.",
        }
        for i in range(4)
    ]

    result, resp = agent.analyze_transcript(segments)

    assert result.title == "Q3 Planning & Launch Strategy"
    assert result.chunk_count == 2
    assert result.coverage_percentage == 100.0
    assert len(result.topics) == 2
    assert len(result.decisions) == 2
    assert len(result.action_items) == 2
    assert result.action_items[0].owner == "Sarah"
    assert result.action_items[1].owner == "Dave"
    # Verify token accumulation across calls
    assert resp.usage.prompt_tokens == 400
    assert resp.usage.completion_tokens == 200


def test_deterministic_multi_chunk_with_boundary_evolution() -> None:
    """Deterministic 3-chunk test with findings across early, middle, and final chunks,
    including a boundary-spanning discussion that changes an earlier tentative decision.
    """
    mock_provider = MagicMock(spec=LLMProvider)
    seg1_id = uuid.uuid4()
    seg2_id = uuid.uuid4()
    seg3_id = uuid.uuid4()

    # Chunk 1: Early proposal
    chunk1_json = {
        "topics": [
            {
                "title": "Cloud Provider",
                "summary": "Discussed AWS.",
                "evidence_segment_ids": [str(seg1_id)],
            }
        ],
        "decisions": [
            {
                "decision_text": "Propose deploying on AWS",
                "confidence": "INFERRED",
                "evidence_segment_ids": [str(seg1_id)],
            }
        ],
        "action_items": [
            {
                "action_text": "Create AWS test VPC",
                "owner": "Alice",
                "due_date": None,
                "evidence_segment_ids": [str(seg1_id)],
            }
        ],
        "risks": [{"risk_text": "AWS cost spikes", "evidence_segment_ids": [str(seg1_id)]}],
        "open_questions": [],
    }

    # Chunk 2: Boundary-spanning debate / disagreement
    chunk2_json = {
        "topics": [
            {
                "title": "Cloud Architecture",
                "summary": "Debated GCP vs AWS.",
                "evidence_segment_ids": [str(seg2_id)],
            }
        ],
        "decisions": [],
        "action_items": [],
        "risks": [
            {"risk_text": "Team lacks GCP familiarity", "evidence_segment_ids": [str(seg2_id)]}
        ],
        "open_questions": [
            {
                "question_text": "Which cloud provider offers better credits?",
                "evidence_segment_ids": [str(seg2_id)],
            }
        ],
    }

    # Chunk 3: Final resolution / revised decision
    chunk3_json = {
        "topics": [
            {
                "title": "Final Platform Decision",
                "summary": "Agreed on GCP due to startup credits.",
                "evidence_segment_ids": [str(seg3_id)],
            }
        ],
        "decisions": [
            {
                "decision_text": "Deploy production infrastructure on GCP",
                "confidence": "EXPLICIT",
                "evidence_segment_ids": [str(seg3_id)],
            }
        ],
        "action_items": [
            {
                "action_text": "Set up GCP project org",
                "owner": "Bob",
                "due_date": "Next Wednesday",
                "evidence_segment_ids": [str(seg3_id)],
            }
        ],
        "risks": [],
        "open_questions": [],
    }

    # Synthesis merges progression
    synth_json = {
        "title": "Infrastructure Platform Architecture",
        "executive_summary": (
            "Initial AWS proposal was reconsidered during debate; team unanimously decided on GCP."
        ),
        "topics": [
            {
                "title": "Cloud Infrastructure Selection",
                "summary": "Evaluated AWS and finalized GCP.",
                "evidence_segment_ids": [str(seg1_id), str(seg3_id)],
            }
        ],
        "decisions": [
            {
                "decision_text": "Deploy production infrastructure on GCP",
                "confidence": "EXPLICIT",
                "evidence_segment_ids": [str(seg3_id)],
            }
        ],
        "action_items": [
            {
                "action_text": "Set up GCP project org",
                "owner": "Bob",
                "due_date": "Next Wednesday",
                "evidence_segment_ids": [str(seg3_id)],
            }
        ],
        "risks": [
            {"risk_text": "Team lacks GCP familiarity", "evidence_segment_ids": [str(seg2_id)]}
        ],
        "open_questions": [],
    }

    mock_provider.generate_structured.side_effect = [
        LLMResponse(
            provider="groq",
            model="gpt-oss-120b",
            content="",
            parsed_json=chunk1_json,
            usage=LLMUsage(prompt_tokens=50, completion_tokens=30),
        ),
        LLMResponse(
            provider="groq",
            model="gpt-oss-120b",
            content="",
            parsed_json=chunk2_json,
            usage=LLMUsage(prompt_tokens=50, completion_tokens=30),
        ),
        LLMResponse(
            provider="groq",
            model="gpt-oss-120b",
            content="",
            parsed_json=chunk3_json,
            usage=LLMUsage(prompt_tokens=50, completion_tokens=30),
        ),
        LLMResponse(
            provider="groq",
            model="gpt-oss-120b",
            content="",
            parsed_json=synth_json,
            usage=LLMUsage(prompt_tokens=100, completion_tokens=60),
        ),
    ]

    settings = Settings(LLM_MODEL="gpt-oss-120b")
    chunker = TranscriptChunker(max_prompt_tokens=60, overlap_tokens=15)
    agent = MeetingAnalysisAgent(mock_provider, settings, chunker=chunker)

    segments = [
        {
            "id": str(seg1_id),
            "start_time": 0.0,
            "end_time": 10.0,
            "speaker": "Alice",
            "text": "Let us consider AWS initially.",
        },
        {
            "id": str(seg2_id),
            "start_time": 10.0,
            "end_time": 20.0,
            "speaker": "Bob",
            "text": "I disagree with AWS because GCP has $100k startup credits.",
        },
        {
            "id": str(seg3_id),
            "start_time": 20.0,
            "end_time": 30.0,
            "speaker": "Alice",
            "text": "Good point. We decide on GCP. Bob, please set up the project.",
        },
    ]

    result, resp = agent.analyze_transcript(segments)
    assert result.chunk_count == 3
    assert result.coverage_percentage == 100.0
    assert result.decisions[0].decision_text == "Deploy production infrastructure on GCP"
    assert result.action_items[0].owner == "Bob"
    assert len(result.risks) == 1


def test_retry_with_backoff_and_retry_after_header() -> None:
    """Verify MeetingAnalysisAgent respects retry_after header on 429 and succeeds."""
    mock_provider = MagicMock(spec=LLMProvider)
    transient_err = LLMProviderError(
        "Rate limit exceeded",
        is_retryable=True,
        retry_after=0.05,
        status_code=429,
    )
    valid_resp = LLMResponse(
        provider="groq",
        model="gpt-oss-120b",
        content="",
        parsed_json={
            "title": "Meeting Title",
            "executive_summary": "Executive summary of the short discussion.",
            "topics": [],
            "decisions": [],
            "action_items": [],
            "risks": [],
            "open_questions": [],
        },
        usage=LLMUsage(prompt_tokens=50, completion_tokens=20),
    )

    mock_provider.generate_structured.side_effect = [transient_err, valid_resp]
    settings = Settings(LLM_MODEL="gpt-oss-120b")
    agent = MeetingAnalysisAgent(mock_provider, settings)

    with patch("time.sleep") as mock_sleep:
        res, resp = agent.analyze_transcript(
            [{"id": "s1", "start_time": 0.0, "end_time": 2.0, "text": "Brief checkin."}]
        )
        assert mock_sleep.called
        # Verify sleep time was based on retry_after (0.05 + jitter)
        assert mock_sleep.call_args[0][0] >= 0.05
        assert res.title == "Meeting Title"


def test_retry_exhaustion_raises_analysis_agent_error() -> None:
    """Verify that exhausting retries raises MeetingAnalysisAgentError with is_retryable."""
    mock_provider = MagicMock(spec=LLMProvider)
    transient_err = LLMProviderError("503 Service Unavailable", is_retryable=True, status_code=503)
    mock_provider.generate_structured.side_effect = transient_err

    settings = Settings(LLM_MODEL="gpt-oss-120b")
    agent = MeetingAnalysisAgent(mock_provider, settings)

    with patch("time.sleep"), pytest.raises(MeetingAnalysisAgentError) as exc_info:
        agent.analyze_transcript(
            [{"id": "s1", "start_time": 0.0, "end_time": 2.0, "text": "Hello world"}]
        )

    assert exc_info.value.is_retryable is True


def test_verification_agent_audits_coverage_and_grounding() -> None:
    """Verify VerificationAgent identifies incomplete coverage and drops ungrounded owners."""
    mock_provider = MagicMock(spec=LLMProvider)
    settings = Settings(LLM_MODEL="gpt-oss-120b")
    verifier = VerificationAgent(mock_provider, settings)

    seg_uuid1 = uuid.uuid4()
    seg_uuid2 = uuid.uuid4()
    all_segments = [
        {
            "id": str(seg_uuid1),
            "text": "Bob agreed to set up the database by Friday.",
            "speaker": "Bob",
        },
        {
            "id": str(seg_uuid2),
            "text": "We need someone to write the documentation.",
            "speaker": "Alice",
        },
    ]

    analysis = MeetingAnalysisOutput(
        title="Test Meeting",
        executive_summary="Team met to discuss tasks.",
        topics=[],
        decisions=[],
        action_items=[
            ActionItemOutput(
                action_text="Set up database",
                owner="Bob",
                due_date="Friday",
                evidence_segment_ids=[seg_uuid1],
            ),
            ActionItemOutput(
                action_text="Write documentation",
                owner="Charlie",  # Charlie is NOT in the transcript!
                due_date=None,
                evidence_segment_ids=[seg_uuid2],
            ),
        ],
        chunk_count=1,
        analyzed_segment_count=2,
        coverage_percentage=100.0,
    )

    # Charlie is not mentioned in segment 2 -> LLM verification returns drop_owner
    mock_provider.generate_structured.return_value = LLMResponse(
        provider="groq",
        model="gpt-oss-120b",
        content="",
        parsed_json={
            "verdict": "drop_owner",
            "reasoning": "Charlie is not mentioned in the transcript.",
        },
    )

    report = verifier.verify_analysis(analysis, all_segments)

    assert report.is_complete is True
    assert report.total_segments == 2
    assert report.coverage_percentage == 100.0
    # Bob should remain owner, Charlie should be dropped to None
    assert analysis.action_items[0].owner == "Bob"
    assert analysis.action_items[1].owner is None
    assert report.modified_actions == 1


def test_verification_filters_cross_meeting_and_fabricated_evidence_ids() -> None:
    """Verify fabricated UUIDs not present in the current meeting transcript are stripped."""
    mock_provider = MagicMock(spec=LLMProvider)
    settings = Settings(LLM_MODEL="gpt-oss-120b")
    verifier = VerificationAgent(mock_provider, settings)

    valid_id = uuid.uuid4()
    fabricated_id = uuid.uuid4()
    all_segments = [{"id": str(valid_id), "text": "Valid discussion point.", "speaker": "Alice"}]

    analysis = MeetingAnalysisOutput(
        title="Security Test",
        executive_summary="Executive summary.",
        topics=[],
        decisions=[
            DecisionOutput(
                decision_text="Proceed with plan",
                confidence=DecisionConfidence.EXPLICIT,
                evidence_segment_ids=[valid_id, fabricated_id],
            )
        ],
        action_items=[
            ActionItemOutput(
                action_text="Follow up task",
                owner=None,
                due_date=None,
                evidence_segment_ids=[fabricated_id],
            )
        ],
        chunk_count=1,
        analyzed_segment_count=1,
        coverage_percentage=100.0,
    )

    verifier.verify_analysis(analysis, all_segments)

    # Decision should only retain valid_id
    assert analysis.decisions[0].evidence_segment_ids == [valid_id]
    # Action item should have empty evidence list
    assert analysis.action_items[0].evidence_segment_ids == []


def test_pathological_unbroken_text_splitting() -> None:
    """Verify oversized segments with unbroken characters split cleanly within token budget."""
    chunker = TranscriptChunker(max_prompt_tokens=150, overlap_tokens=30)
    # 2000 unbroken characters
    unbroken_text = "A" * 2000
    seg = {
        "id": "unbroken-seg-1",
        "start_time": 0.0,
        "end_time": 100.0,
        "speaker": "Speaker_Test",
        "text": unbroken_text,
    }

    chunks = chunker.chunk_segments([seg])
    assert len(chunks) > 1
    # Verify no chunk or segment exceeds max_prompt_tokens
    for c in chunks:
        for s in c.segments:
            cost = estimate_segment_tokens(s)
            assert cost <= chunker.max_prompt_tokens
        assert c.primary_segment_ids == ["unbroken-seg-1"]


def test_rate_limit_header_parsing_variants() -> None:
    """Verify missing, malformed, standard integer, HTTP-date, and Groq reset headers."""
    import httpx

    from app.providers.llm.groq_provider import (
        parse_groq_reset_duration,
        parse_retry_after_header,
    )

    # 1. Missing header
    h_empty = httpx.Headers({})
    assert parse_retry_after_header(h_empty) is None

    # 2. Malformed numeric header
    h_mal = httpx.Headers({"retry-after": "not-a-number"})
    assert parse_retry_after_header(h_mal) is None

    # 3. Valid numeric integer and float
    h_int = httpx.Headers({"retry-after": "5"})
    assert parse_retry_after_header(h_int) == 5.0
    h_float = httpx.Headers({"retry-after": "2.5"})
    assert parse_retry_after_header(h_float) == 2.5

    # 4. Groq duration strings (seconds, minutes + seconds, hours)
    assert parse_groq_reset_duration("7.66s") == 7.66
    assert parse_groq_reset_duration("2m59.56s") == (2 * 60 + 59.56)
    assert parse_groq_reset_duration("1h2m3s") == (3600 + 120 + 3)
    assert parse_groq_reset_duration("invalid-string") is None

    # 5. Groq headers fallback when retry-after is absent
    h_groq_tpm = httpx.Headers({"x-ratelimit-reset-tokens": "8.5s"})
    assert parse_retry_after_header(h_groq_tpm) == 8.5

    h_groq_rpm = httpx.Headers({"x-ratelimit-reset-requests": "1m30s"})
    assert parse_retry_after_header(h_groq_rpm) == 90.0
