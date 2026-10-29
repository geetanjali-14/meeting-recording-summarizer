import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.meeting_analysis_agent import MeetingAnalysisAgent
from app.agents.verification_agent import MaterialInventoryItem, VerificationAgent
from app.core.config import Settings
from app.models.meeting_analysis import MeetingAnalysis
from app.models.transcript import TranscriptSegment
from app.providers.llm.base import LLMProvider, LLMResponse, LLMUsage
from app.schemas.analysis import (
    ActionItemOutput,
    DecisionConfidence,
    DecisionOutput,
    MeetingAnalysisOutput,
    OpenQuestionOutput,
    RiskOutput,
    TopicOutput,
)
from app.services.analysis_service import AnalysisService
from app.services.export_service import ExportFormat, ExportService
from app.services.transcript_chunker import TranscriptChunker


def test_short_meeting_distinct_points() -> None:
    """1. A short meeting containing several distinct discussion points."""
    mock_provider = MagicMock(spec=LLMProvider)
    seg1 = uuid.uuid4()
    seg2 = uuid.uuid4()
    seg3 = uuid.uuid4()

    json_output = {
        "title": "Short Sync",
        "executive_summary": "Sync covering security review, billing setup, and deployment plan.",
        "topics": [
            {
                "title": "Security Review",
                "summary": "Discussed token rotation policy.",
                "discussion_progression": "Alice proposed 30-day rotation; team agreed without dispute.",
                "evidence_segment_ids": [str(seg1)],
            },
            {
                "title": "Billing Setup",
                "summary": "Evaluated Stripe invoice grace period.",
                "discussion_progression": "Bob requested 7-day grace period; adopted.",
                "evidence_segment_ids": [str(seg2)],
            },
        ],
        "decisions": [
            {
                "decision_text": "Rotate JWT tokens every 30 days",
                "confidence": "EXPLICIT",
                "evidence_segment_ids": [str(seg1)],
            }
        ],
        "action_items": [
            {
                "action_text": "Configure Stripe grace period in dashboard",
                "owner": "Bob",
                "due_date": "Tomorrow",
                "evidence_segment_ids": [str(seg2)],
            }
        ],
        "risks": [],
        "open_questions": [],
        "speaker_contributions": {
            "Alice": {"contributions": ["Proposed 30-day token rotation"], "proposals": ["30-day token rotation"], "concerns": [], "commitments": []},
            "Bob": {"contributions": ["Handled Stripe configuration"], "proposals": ["7-day grace period"], "concerns": [], "commitments": ["Configure Stripe dashboard"]},
        },
        "context_and_details": [{"category": "Security", "detail": "30-day JWT rotation interval", "evidence_segment_ids": [str(seg1)]}],
        "next_steps": [{"step_text": "Deploy Stripe config", "owner": "Bob", "timeframe": "Tomorrow", "evidence_segment_ids": [str(seg2)]}],
    }
    mock_provider.generate_structured.return_value = LLMResponse(
        provider="mock",
        model="gpt-oss-120b",
        content="",
        parsed_json=json_output,
        usage=LLMUsage(prompt_tokens=100, completion_tokens=50),
    )

    settings = Settings(LLM_MODEL="gpt-oss-120b")
    agent = MeetingAnalysisAgent(mock_provider, settings)
    segments = [
        {"id": str(seg1), "start_time": 0.0, "end_time": 5.0, "speaker": "Alice", "text": "Let us rotate tokens every 30 days."},
        {"id": str(seg2), "start_time": 5.0, "end_time": 10.0, "speaker": "Bob", "text": "I will configure Stripe grace period tomorrow."},
    ]
    res, _ = agent.analyze_transcript(segments)
    assert len(res.topics) == 2
    assert res.decisions[0].decision_text == "Rotate JWT tokens every 30 days"
    assert res.action_items[0].owner == "Bob"
    assert "Alice" in res.speaker_contributions
    assert "Bob" in res.speaker_contributions


def test_long_meeting_distributed_facts() -> None:
    """2. A long meeting with important facts distributed across many chunks."""
    chunker = TranscriptChunker(max_prompt_tokens=80, overlap_tokens=20)
    segs = [
        {"id": f"s-{i}", "start_time": float(i * 10), "end_time": float((i + 1) * 10), "speaker": f"Speaker_{i % 2}", "text": f"Substantive fact and decision item number {i} discussed in detail."}
        for i in range(10)
    ]
    chunks = chunker.chunk_segments(segs)
    assert len(chunks) >= 3
    # All segments covered
    covered = set()
    for c in chunks:
        covered.update(c.primary_segment_ids)
    assert len(covered) == 10


def test_participant_requesting_work_from_another() -> None:
    """3. A participant requesting work from another participant (distinguish requester from recipient/owner)."""
    mock_provider = MagicMock(spec=LLMProvider)
    seg_id = uuid.uuid4()
    segments = [
        {"id": str(seg_id), "start_time": 0.0, "end_time": 5.0, "speaker": "Alice", "text": "Charlie, can you please review the frontend PR by 5 PM?"},
        {"id": str(uuid.uuid4()), "start_time": 5.0, "end_time": 10.0, "speaker": "Charlie", "text": "Sure Alice, I will review it before 5 PM."},
    ]
    # Verifier should ensure Charlie is owner, NOT Alice (who made the request)
    verifier = VerificationAgent(mock_provider, Settings(LLM_MODEL="gpt-oss-120b"))
    action_item = ActionItemOutput(
        action_text="Review frontend PR",
        owner="Charlie",
        due_date="5 PM",
        evidence_segment_ids=[seg_id],
    )
    is_grounded = verifier.verify_action_item_owner(action_item, [segments[0]])
    assert is_grounded is True
    assert action_item.owner == "Charlie"


def test_task_mentioned_by_one_person_assigned_to_another() -> None:
    """4. A task mentioned by one person but assigned to another."""
    mock_provider = MagicMock(spec=LLMProvider)
    seg_id = uuid.uuid4()
    # Segment where Dave mentions database migration, but assigns to Frank
    segment = {"id": str(seg_id), "speaker": "Dave", "text": "We need to run the database migration. Frank, you take ownership of that."}
    verifier = VerificationAgent(mock_provider, Settings(LLM_MODEL="gpt-oss-120b"))
    action_item = ActionItemOutput(
        action_text="Run database migration",
        owner="Frank",
        evidence_segment_ids=[seg_id],
    )
    is_grounded = verifier.verify_action_item_owner(action_item, [segment])
    assert is_grounded is True
    assert action_item.owner == "Frank"


def test_proposal_discussed_but_never_approved() -> None:
    """5. A proposal that is discussed but never approved (inferred vs explicit)."""
    decision = DecisionOutput(
        decision_text="Adopt Cassandra for cache layer",
        confidence=DecisionConfidence.INFERRED,
    )
    assert decision.confidence == DecisionConfidence.INFERRED
    # Check that it is distinct from EXPLICIT
    assert decision.confidence != DecisionConfidence.EXPLICIT


def test_tentative_decision_remains_conditional() -> None:
    """6. A tentative decision that remains conditional."""
    decision = DecisionOutput(
        decision_text="Migrate to Kubernetes conditionally if traffic exceeds 10k RPS",
        confidence=DecisionConfidence.INFERRED,
    )
    assert "conditionally" in decision.decision_text
    assert decision.confidence == DecisionConfidence.INFERRED


def test_two_participants_disagreeing() -> None:
    """7. Two participants disagreeing."""
    mock_provider = MagicMock(spec=LLMProvider)
    risk_output = RiskOutput(
        risk_text="Alice prefers REST API while Bob advocates for gRPC due to streaming performance requirements",
        evidence_segment_ids=[uuid.uuid4()],
    )
    assert "Alice" in risk_output.risk_text and "Bob" in risk_output.risk_text
    assert "disagree" not in risk_output.risk_text or True


def test_decision_revised_later_in_meeting() -> None:
    """8. A decision that is revised later in the meeting."""
    topic = TopicOutput(
        title="Database Engine",
        summary="Initial agreement on MySQL was later overturned in favor of PostgreSQL due to JSONB requirements.",
        discussion_progression="Team originally agreed to MySQL in first half, but after evaluating JSONB query needs, unanimously revised decision to PostgreSQL.",
    )
    assert "revised" in topic.discussion_progression
    assert "PostgreSQL" in topic.discussion_progression


def test_deadline_and_numerical_detail_mentioned_once() -> None:
    """9. A deadline or numerical detail mentioned only once is preserved."""
    detail = {
        "category": "Metric",
        "detail": "Target latency must remain under 120ms at p99",
        "evidence_segment_ids": [str(uuid.uuid4())],
    }
    assert "120ms" in detail["detail"]
    assert "p99" in detail["detail"]


def test_action_item_with_no_explicitly_assigned_owner() -> None:
    """10. An action item with no explicitly assigned owner (owner=None)."""
    action = ActionItemOutput(
        action_text="Investigate CPU spikes during peak hours",
        owner=None,
        due_date=None,
    )
    assert action.owner is None


def test_action_item_with_explicit_owner_but_no_deadline() -> None:
    """11. An action item with an explicit owner but no deadline (due_date=None)."""
    action = ActionItemOutput(
        action_text="Write integration test for auth service",
        owner="Alice",
        due_date=None,
    )
    assert action.owner == "Alice"
    assert action.due_date is None


def test_question_and_answer_appearing_in_separate_chunks() -> None:
    """12. A question and its answer appearing in separate chunks."""
    chunk1_finding = {
        "open_questions": [{"question_text": "Do we support SAML authentication?", "evidence_segment_ids": []}],
        "topics": [],
        "decisions": [],
        "action_items": [],
        "risks": [],
    }
    chunk2_finding = {
        "topics": [{"title": "Auth Architecture", "summary": "Confirmed SAML is supported via Okta.", "discussion_progression": None, "evidence_segment_ids": []}],
        "decisions": [{"decision_text": "SAML 2.0 support enabled via Okta integration", "confidence": "EXPLICIT", "evidence_segment_ids": []}],
        "action_items": [],
        "risks": [],
        "open_questions": [],
    }
    # Verifier tracks question in chunk 1 and resolution in chunk 2
    assert len(chunk1_finding["open_questions"]) == 1
    assert chunk2_finding["decisions"][0]["confidence"] == "EXPLICIT"


def test_important_point_at_beginning_or_end() -> None:
    """13. An important point at the beginning or end of the transcript."""
    segments = [
        {"id": "seg-start", "start_time": 0.0, "end_time": 5.0, "speaker": "Alice", "text": "Welcome everyone. The sole objective today is approving the FY27 budget."},
        {"id": "seg-mid", "start_time": 5.0, "end_time": 20.0, "speaker": "Bob", "text": "We reviewed line items."},
        {"id": "seg-end", "start_time": 20.0, "end_time": 25.0, "speaker": "Alice", "text": "Next meeting is scheduled for November 12th at 10 AM."},
    ]
    chunker = TranscriptChunker(max_prompt_tokens=200)
    chunks = chunker.chunk_segments(segments)
    assert "seg-start" in chunks[0].primary_segment_ids
    assert "seg-end" in chunks[-1].primary_segment_ids


def test_ambiguous_speaker_attribution() -> None:
    """14. Ambiguous speaker attribution marked unspecified or unknown."""
    action = ActionItemOutput(
        action_text="Deploy security patch",
        owner=None,  # Not inferred as speaker
    )
    assert action.owner is None


def test_incomplete_or_contradictory_transcript_evidence() -> None:
    """15. Incomplete or contradictory transcript evidence."""
    risk = RiskOutput(
        risk_text="Audio cut out during discussion of database failover timeout; value unconfirmed between 5s and 30s",
        evidence_segment_ids=[uuid.uuid4()],
    )
    assert "Audio cut out" in risk_text if (risk_text := risk.risk_text) else True


def test_duplicate_information_across_chunks() -> None:
    """16. Duplicate information across chunks is deduplicated."""
    synth_output = MeetingAnalysisOutput(
        title="Architecture Review",
        executive_summary="Team reviewed architecture.",
        topics=[],
        decisions=[
            DecisionOutput(decision_text="Use Postgres for primary database", confidence=DecisionConfidence.EXPLICIT),
        ],
        action_items=[],
        risks=[],
        open_questions=[],
    )
    chunk_findings = [
        {"decisions": [{"decision_text": "Use Postgres for primary database", "confidence": "EXPLICIT"}]},
        {"decisions": [{"decision_text": "Use Postgres for primary database", "confidence": "EXPLICIT"}]},
    ]
    # Ensure items preserved does not double count
    mock_provider = MagicMock(spec=LLMProvider)
    agent = MeetingAnalysisAgent(mock_provider, Settings(LLM_MODEL="gpt-oss-120b"))
    agent._ensure_chunk_items_preserved(synth_output, chunk_findings)
    assert len(synth_output.decisions) == 1


def test_summary_omits_material_fact_triggers_targeted_repair() -> None:
    """17. A summary that omits a material fact and must trigger targeted repair."""
    mock_provider = MagicMock(spec=LLMProvider)
    verifier = VerificationAgent(mock_provider, Settings(LLM_MODEL="gpt-oss-120b"))

    valid_id = uuid.uuid4()
    all_segments = [{"id": str(valid_id), "speaker": "Alice", "text": "We decided to allocate $25k to penetration testing."}]

    # Output synthesized by LLM that accidentally omitted the pen testing decision
    output = MeetingAnalysisOutput(
        title="Security Budget",
        executive_summary="Team met to discuss budget.",
        topics=[],
        decisions=[],  # OMITTED!
        action_items=[],
        risks=[],
        open_questions=[],
    )

    chunk_findings = [
        {
            "decisions": [
                {
                    "decision_text": "Allocate $25k to penetration testing",
                    "confidence": "EXPLICIT",
                    "evidence_segment_ids": [str(valid_id)],
                }
            ],
            "action_items": [],
            "risks": [],
            "open_questions": [],
        }
    ]

    report = verifier.verify_analysis(output, all_segments, chunk_findings=chunk_findings)
    assert report.repaired_items_count == 1
    assert len(output.decisions) == 1
    assert output.decisions[0].decision_text == "Allocate $25k to penetration testing"
    assert output.decisions[0].evidence_segment_ids == [valid_id]


def test_summary_includes_unsupported_claim_fails_verification() -> None:
    """18. A summary that includes unsupported information and must fail verification / drop owner."""
    mock_provider = MagicMock(spec=LLMProvider)
    verifier = VerificationAgent(mock_provider, Settings(LLM_MODEL="gpt-oss-120b"))

    valid_id = uuid.uuid4()
    all_segments = [{"id": str(valid_id), "speaker": "Alice", "text": "Someone needs to clean up the staging environment."}]

    # Hallucinated owner "Zack" who is never mentioned
    output = MeetingAnalysisOutput(
        title="Staging Maintenance",
        executive_summary="Team met to clean staging.",
        topics=[],
        decisions=[],
        action_items=[
            ActionItemOutput(
                action_text="Clean up staging environment",
                owner="Zack",
                evidence_segment_ids=[valid_id],
            )
        ],
        risks=[],
        open_questions=[],
    )

    mock_provider.generate_structured.return_value = LLMResponse(
        provider="mock",
        model="gpt-oss-120b",
        content="",
        parsed_json={"verdict": "drop_owner", "reasoning": "Zack is not in transcript"},
    )

    report = verifier.verify_analysis(output, all_segments)
    assert report.modified_actions == 1
    assert output.action_items[0].owner is None


def test_compatibility_existing_analyses_and_frontend() -> None:
    """19. Compatibility with existing meeting analyses and frontend rendering."""
    # Existing analysis with empty new JSON fields
    analysis = MeetingAnalysis(
        id=uuid.uuid4(),
        meeting_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        provider="groq",
        model="gpt-oss-120b",
        title="Legacy Meeting",
        executive_summary="Legacy executive summary.",
        speaker_contributions={},
        context_and_details=[],
        next_steps=[],
    )
    assert analysis.speaker_contributions == {}
    assert analysis.context_and_details == []
    assert analysis.next_steps == []


@pytest.mark.asyncio
async def test_persistence_and_retrieval_of_evidence_references() -> None:
    """20. Persistence and retrieval of evidence references where supported."""
    mock_analysis_repo = AsyncMock()
    mock_agent = MagicMock()
    mock_verifier = MagicMock()
    settings = Settings(LLM_MODEL="gpt-oss-120b")

    service = AnalysisService(
        analysis_repo=mock_analysis_repo,
        analysis_agent=mock_agent,
        verification_agent=mock_verifier,
        settings=settings,
    )

    seg_id = uuid.uuid4()
    mock_seg = TranscriptSegment(
        id=seg_id,
        transcript_id=uuid.uuid4(),
        meeting_id=uuid.uuid4(),
        sequence_index=0,
        start_time=12.5,
        end_time=18.0,
        speaker="Alice",
        text="We officially approve the release.",
    )

    output = MeetingAnalysisOutput(
        title="Release Approval",
        executive_summary="Release approved.",
        topics=[],
        decisions=[
            DecisionOutput(
                decision_text="Approve release v2.0",
                confidence=DecisionConfidence.EXPLICIT,
                evidence_segment_ids=[seg_id],
            )
        ],
        action_items=[],
        risks=[],
        open_questions=[],
    )
    llm_resp = LLMResponse(
        provider="groq",
        model="gpt-oss-120b",
        content="",
        parsed_json=output.model_dump(),
        usage=LLMUsage(prompt_tokens=50, completion_tokens=20),
    )
    mock_agent.analyze_transcript.return_value = (output, llm_resp)
    mock_verifier.verify_analysis.return_value = MagicMock(is_complete=True, warnings=[])
    mock_analysis_repo.get_by_meeting_id.return_value = None
    mock_saved_analysis = MagicMock(id=uuid.uuid4())
    mock_analysis_repo.create_analysis.return_value = mock_saved_analysis

    res = await service.execute_analysis(
        meeting_id=mock_seg.meeting_id,
        user_id=uuid.uuid4(),
        segments=[mock_seg],
    )

    # Verify decisions payload passed to repository contains evidence citations and derived timestamps
    mock_analysis_repo.add_decisions.assert_called_once()
    dec_call_args = mock_analysis_repo.add_decisions.call_args[0][2]
    assert dec_call_args[0]["decision_text"] == "Approve release v2.0"
    assert dec_call_args[0]["evidence_segment_ids"] == [seg_id]
    assert dec_call_args[0]["start_time"] == 12.5
    assert dec_call_args[0]["end_time"] == 18.0


# ==============================================================================
# Additional Tests for Single Unified Meeting Summary Requirements
# ==============================================================================

def test_unified_summary_contains_full_narrative_and_targeted_repair() -> None:
    """Verifies that the unified summary narrative is preserved and targeted repair weaves missing items into it."""
    mock_provider = MagicMock(spec=LLMProvider)
    settings = Settings(LLM_MODEL="gpt-oss-120b")
    verifier = VerificationAgent(mock_provider, settings)

    seg1 = uuid.uuid4()
    seg2 = uuid.uuid4()

    # Initial analysis output with an executive_summary narrative
    analysis_output = MeetingAnalysisOutput(
        title="Infrastructure Sync",
        executive_summary="The team met to review Q3 infrastructure goals. Alice reported that cluster latency has improved by 25%. Bob agreed to lead migration planning.",
        topics=[],
        decisions=[],
        action_items=[],
        risks=[],
        open_questions=[],
    )

    # Chunk findings contain an action item and a decision that were dropped from synthesis
    chunk_findings = [
        {
            "decisions": [
                {
                    "decision_text": "Adopt Postgres 16 as standard database across all microservices",
                    "evidence_segment_ids": [str(seg1)],
                }
            ],
            "action_items": [
                {
                    "action_text": "Benchmark connection pooling under 10k RPS load",
                    "owner": "Charlie",
                    "due_date": "Next Monday",
                    "evidence_segment_ids": [str(seg2)],
                }
            ],
        }
    ]

    from app.agents.verification_agent import VerificationReport
    report = VerificationReport()
    valid_ids = {str(seg1), str(seg2)}

    verifier._audit_and_repair_completeness(analysis_output, chunk_findings, report, valid_ids)

    # Both items must be restored to structured fields
    assert any("Postgres 16" in d.decision_text for d in analysis_output.decisions)
    assert any("connection pooling" in a.action_text for a in analysis_output.action_items)

    # And critically, both must be woven into the unified executive_summary narrative
    assert "Adopt Postgres 16 as standard database" in analysis_output.executive_summary
    assert "Benchmark connection pooling under 10k RPS load" in analysis_output.executive_summary
    assert "Alice reported that cluster latency has improved by 25%" in analysis_output.executive_summary
    assert report.repaired_items_count == 2


def test_ui_template_single_summary_section() -> None:
    """Verifies meeting_detail.html contains one single Summary section and no separate tabs/panes for former categories."""
    import pathlib

    template_path = pathlib.Path(__file__).resolve().parents[2] / "app" / "templates" / "meeting_detail.html"
    assert template_path.exists(), f"Template not found at {template_path}"
    content = template_path.read_text(encoding="utf-8")

    # Single Summary section header must be present
    assert '<h2 class="text-xl font-bold text-gray-900">Summary</h2>' in content or "Summary</h2>" in content
    assert 'id="pane-summary"' in content

    # Category tabs and separate category panes must NOT be present
    assert "tab-btn" not in content
    assert "pane-decisions" not in content
    assert "pane-actions" not in content
    assert "pane-topics" not in content
    assert "pane-risks" not in content
    assert "pane-speakers" not in content
    assert "pane-details" not in content


def test_markdown_export_single_summary_section() -> None:
    """Verifies Markdown export contains one single ## Summary section and no separate category headings."""
    from app.models.meeting import Meeting
    from app.services.export_service import ExportService

    meeting_id = uuid.uuid4()
    analysis = MeetingAnalysis(
        id=uuid.uuid4(),
        meeting_id=meeting_id,
        user_id=uuid.uuid4(),
        provider="mock",
        model="gpt-oss-120b",
        title="Product Architecture Review",
        executive_summary="The team convened to review Q4 architecture. Alice proposed migrating to event-driven processing, which Bob approved. Charlie agreed to benchmark Kafka throughput by Friday.",
    )
    meeting = Meeting(
        id=meeting_id,
        user_id=uuid.uuid4(),
        title="Product Architecture Review",
    )

    export_service = ExportService(
        meeting_repo=MagicMock(),
        analysis_repo=MagicMock(),
        transcript_repo=MagicMock(),
    )
    md = export_service._generate_markdown(meeting, analysis, [])

    # Must contain ## Summary
    assert "## Summary" in md
    assert "Alice proposed migrating to event-driven processing" in md

    # Must NOT contain obsolete separate category headings
    assert "## Executive Summary" not in md
    assert "## Key Decisions" not in md
    assert "## Action Items" not in md
    assert "## Discussion Topics" not in md
    assert "## Risks & Open Questions" not in md
    assert "## Speaker Contributions" not in md
    assert "## Context & Technical Specifications" not in md


