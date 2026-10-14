import json
import re
import uuid
from typing import Any

from app.models.meeting import Meeting
from app.models.meeting_analysis import MeetingAnalysis
from app.models.transcript import TranscriptSegment
from app.repositories.analysis_repository import AnalysisRepository
from app.repositories.meeting_repository import MeetingRepository
from app.repositories.transcript_repository import TranscriptRepository
from app.schemas.export import ExportFormat, ExportResponse


def format_seconds(seconds: float | None) -> str:
    if seconds is None:
        return "N/A"
    mins = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{mins}:{secs:02d}"


def sanitize_filename(name: str) -> str:
    cleaned = re.sub(r"[^\w\-_\. ]", "_", name)
    return re.sub(r"\s+", "_", cleaned).strip("_")


class ExportService:
    """Service to generate formatted Markdown and JSON exports of meeting intelligence."""

    def __init__(
        self,
        meeting_repo: MeetingRepository,
        analysis_repo: AnalysisRepository,
        transcript_repo: TranscriptRepository,
    ) -> None:
        self.meeting_repo = meeting_repo
        self.analysis_repo = analysis_repo
        self.transcript_repo = transcript_repo

    async def export_meeting(
        self,
        meeting_id: uuid.UUID,
        user_id: uuid.UUID,
        export_format: ExportFormat,
    ) -> ExportResponse:
        # 1. Enforce tenant isolation
        meeting = await self.meeting_repo.get_by_id(meeting_id=meeting_id, user_id=user_id)
        if meeting is None:
            raise ValueError("Meeting not found")

        # 2. Retrieve analysis and transcript if available
        analysis = await self.analysis_repo.get_by_meeting_id(
            meeting_id=meeting_id,
            user_id=user_id,
            include_children=True,
        )

        transcript = await self.transcript_repo.get_by_meeting_id(
            meeting_id=meeting_id,
            user_id=user_id,
        )
        segments: list[TranscriptSegment] = []
        if transcript is not None:
            seq_segs = await self.transcript_repo.get_segments_by_transcript(transcript.id)
            segments = list(seq_segs)

        # 3. Build export data based on requested format
        safe_title = sanitize_filename(meeting.title or "Meeting")

        if export_format == ExportFormat.JSON:
            filename = f"{safe_title}_analysis.json"
            content = self._generate_json(meeting, analysis, segments)
            content_type = "application/json"
        else:
            filename = f"{safe_title}_analysis.md"
            content = self._generate_markdown(meeting, analysis, segments)
            content_type = "text/markdown"

        return ExportResponse(
            meeting_id=meeting.id,
            format=export_format.value,
            filename=filename,
            content_type=content_type,
            content=content,
            metadata={
                "has_analysis": analysis is not None,
                "has_transcript": transcript is not None,
                "segment_count": len(segments),
            },
        )

    def _generate_json(
        self,
        meeting: Meeting,
        analysis: MeetingAnalysis | None,
        segments: list[TranscriptSegment],
    ) -> str:
        data: dict[str, Any] = {
            "meeting": {
                "id": str(meeting.id),
                "title": meeting.title,
                "description": meeting.description,
                "meeting_date": str(meeting.meeting_date) if meeting.meeting_date else None,
                "created_at": meeting.created_at.isoformat() if meeting.created_at else None,
            },
            "analysis": None,
            "transcript_summary": {
                "total_segments": len(segments),
            },
        }

        if analysis is not None:
            data["analysis"] = {
                "id": str(analysis.id),
                "title": analysis.title,
                "executive_summary": analysis.executive_summary,
                "model": analysis.model,
                "estimated_cost_usd": float(analysis.estimated_cost_usd)
                if analysis.estimated_cost_usd is not None
                else None,
                "topics": [
                    {
                        "sequence_index": t.sequence_index,
                        "title": t.title,
                        "summary": t.summary,
                        "start_time": t.start_time,
                        "end_time": t.end_time,
                    }
                    for t in sorted(analysis.topics, key=lambda x: x.sequence_index)
                ],
                "decisions": [
                    {
                        "sequence_index": d.sequence_index,
                        "decision_text": d.decision_text,
                        "confidence": d.confidence.value if d.confidence else None,
                        "start_time": d.start_time,
                        "end_time": d.end_time,
                        "evidence_segment_ids": [
                            str(sid) for sid in (d.evidence_segment_ids or [])
                        ],
                    }
                    for d in sorted(analysis.decisions, key=lambda x: x.sequence_index)
                ],
                "action_items": [
                    {
                        "sequence_index": a.sequence_index,
                        "action_text": a.action_text,
                        "owner": a.owner,
                        "due_date": a.due_date,
                        "start_time": a.start_time,
                        "end_time": a.end_time,
                        "evidence_segment_ids": [
                            str(sid) for sid in (a.evidence_segment_ids or [])
                        ],
                    }
                    for a in sorted(analysis.action_items, key=lambda x: x.sequence_index)
                ],
                "risks": [
                    {
                        "sequence_index": r.sequence_index,
                        "risk_text": r.risk_text,
                        "start_time": r.start_time,
                        "end_time": r.end_time,
                        "evidence_segment_ids": [
                            str(sid) for sid in (r.evidence_segment_ids or [])
                        ],
                    }
                    for r in sorted(analysis.risks, key=lambda x: x.sequence_index)
                ],
                "open_questions": [
                    {
                        "sequence_index": q.sequence_index,
                        "question_text": q.question_text,
                        "start_time": q.start_time,
                        "end_time": q.end_time,
                        "evidence_segment_ids": [
                            str(sid) for sid in (q.evidence_segment_ids or [])
                        ],
                    }
                    for q in sorted(analysis.open_questions, key=lambda x: x.sequence_index)
                ],
            }

        return json.dumps(data, indent=2)

    def _generate_markdown(
        self,
        meeting: Meeting,
        analysis: MeetingAnalysis | None,
        segments: list[TranscriptSegment],
    ) -> str:
        lines: list[str] = [
            f"# {meeting.title or 'Meeting Summary'}",
            "",
            f"- **Date:** {meeting.meeting_date or 'N/A'}",
        ]
        if meeting.description:
            lines.append(f"- **Description:** {meeting.description}")
        lines.append("")

        if analysis is None:
            lines.extend(
                [
                    "## Executive Summary",
                    "",
                    "_No intelligence analysis available for this meeting._",
                    "",
                ]
            )
        else:
            lines.extend(
                [
                    "## Executive Summary",
                    "",
                    analysis.executive_summary or "_No executive summary generated._",
                    "",
                ]
            )

            if analysis.topics:
                lines.extend(["## Discussion Topics", ""])
                for t in sorted(analysis.topics, key=lambda x: x.sequence_index):
                    ts = ""
                    if t.start_time is not None:
                        ts = f" ({format_seconds(t.start_time)} - {format_seconds(t.end_time)})"
                    lines.append(f"### {t.title}{ts}")
                    if t.summary:
                        lines.append(f"{t.summary}\n")

            if analysis.decisions:
                lines.extend(["## Decisions", ""])
                for d in sorted(analysis.decisions, key=lambda x: x.sequence_index):
                    conf = f" [{d.confidence.value}]" if d.confidence else ""
                    ts = ""
                    if d.start_time is not None:
                        ts = f" ({format_seconds(d.start_time)} - {format_seconds(d.end_time)})"
                    lines.append(f"- **Decision:** {d.decision_text}{conf}{ts}")
                lines.append("")

            if analysis.action_items:
                lines.extend(["## Action Items", ""])
                for a in sorted(analysis.action_items, key=lambda x: x.sequence_index):
                    owner = f" **Owner:** {a.owner}" if a.owner else " **Owner:** _Unassigned_"
                    due = f" | **Due:** {a.due_date}" if a.due_date else " | **Due:** _None_"
                    ts = ""
                    if a.start_time is not None:
                        t_str = f"{format_seconds(a.start_time)} - {format_seconds(a.end_time)}"
                        ts = f" | **Time:** {t_str}"
                    lines.append(f"- [ ] {a.action_text} — {owner}{due}{ts}")
                lines.append("")

            if analysis.risks:
                lines.extend(["## Risks & Blockers", ""])
                for r in sorted(analysis.risks, key=lambda x: x.sequence_index):
                    ts = ""
                    if r.start_time is not None:
                        ts = f" ({format_seconds(r.start_time)} - {format_seconds(r.end_time)})"
                    lines.append(f"- ⚠️ {r.risk_text}{ts}")
                lines.append("")

            if analysis.open_questions:
                lines.extend(["## Open Questions", ""])
                for q in sorted(analysis.open_questions, key=lambda x: x.sequence_index):
                    ts = ""
                    if q.start_time is not None:
                        ts = f" ({format_seconds(q.start_time)} - {format_seconds(q.end_time)})"
                    lines.append(f"- ❓ {q.question_text}{ts}")
                lines.append("")

        if segments:
            lines.extend(
                [
                    "---",
                    f"## Transcript ({len(segments)} segments)",
                    "",
                ]
            )
            for s in segments:
                speaker = s.speaker or s.speaker_label or "Speaker"
                time_range = f"[{format_seconds(s.start_time)} - {format_seconds(s.end_time)}]"
                lines.append(f"{time_range} **{speaker}:** {s.text}")

        return "\n".join(lines)
