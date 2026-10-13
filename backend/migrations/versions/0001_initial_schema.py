"""Baseline initial schema with PostgreSQL 15+ and pg_trgm/gin support

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-10-13 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001_initial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. users
    op.create_table(
        "users",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("quota_minutes_per_month", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_index("idx_users_email", "users", ["email"])

    # 2. meetings
    meeting_status = postgresql.ENUM(
        "CREATED", "ACTIVE", "DELETING", "PURGED", name="meeting_status", create_type=False
    )
    meeting_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "meetings",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("meeting_date", sa.Date(), server_default=sa.func.current_date(), nullable=False),
        sa.Column(
            "status",
            meeting_status,
            server_default="CREATED",
            nullable=False,
        ),
        sa.Column(
            "speaker_mappings",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_meetings_user_id", "meetings", ["user_id"])
    op.create_index("idx_meetings_status", "meetings", ["status"])

    # 3. recordings
    recording_status = postgresql.ENUM(
        "PRESIGNED", "UPLOADED", "DELETED", name="recording_status", create_type=False
    )
    recording_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "recordings",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("meeting_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("storage_key", sa.String(), nullable=False),
        sa.Column("original_filename", sa.String(), nullable=False),
        sa.Column("content_type", sa.String(), nullable=False),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256_hash", sa.String(), nullable=True),
        sa.Column(
            "status",
            recording_status,
            server_default="PRESIGNED",
            nullable=False,
        ),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["meeting_id"], ["meetings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("meeting_id"),
    )
    op.create_index("idx_recordings_user_id", "recordings", ["user_id"])

    # 4. processing_jobs
    job_status = postgresql.ENUM(
        "PENDING",
        "RUNNING",
        "COMPLETED",
        "FAILED",
        "CANCELLED",
        name="job_status",
        create_type=False,
    )
    job_status.create(op.get_bind(), checkfirst=True)

    job_stage = postgresql.ENUM(
        "CREATED",
        "VALIDATING",
        "EXTRACTING_AUDIO",
        "TRANSCRIBING",
        "DIARIZING",
        "ANALYZING",
        "VERIFYING",
        "SAVING",
        "COMPLETED",
        "FAILED",
        name="job_stage",
        create_type=False,
    )
    job_stage.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "processing_jobs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("meeting_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("celery_task_id", sa.String(), nullable=True),
        sa.Column(
            "status",
            job_status,
            server_default="PENDING",
            nullable=False,
        ),
        sa.Column(
            "stage",
            job_stage,
            server_default="CREATED",
            nullable=False,
        ),
        sa.Column("attempt", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default="3", nullable=False),
        sa.Column("error_code", sa.String(), nullable=True),
        sa.Column("error_message", sa.String(), nullable=True),
        sa.Column("worker_id", sa.String(), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "enqueued_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["meeting_id"], ["meetings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("meeting_id"),
    )
    op.create_index("idx_jobs_celery_task_id", "processing_jobs", ["celery_task_id"])
    op.create_index("idx_jobs_status_stage", "processing_jobs", ["status", "stage"])
    op.create_index("idx_jobs_lease_recovery", "processing_jobs", ["status", "lease_expires_at"])
    op.create_index("idx_jobs_user_id", "processing_jobs", ["user_id"])

    # 5. transcripts
    op.create_table(
        "transcripts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("meeting_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("model", sa.String(), nullable=True),
        sa.Column("diarization_provider", sa.String(), nullable=True),
        sa.Column("language", sa.String(), nullable=True),
        sa.Column("total_duration_seconds", sa.Float(), nullable=True),
        sa.Column("segment_count", sa.Integer(), nullable=True),
        sa.Column("raw_transcript_text", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["meeting_id"], ["meetings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("meeting_id"),
    )
    op.create_index("idx_transcripts_user_id", "transcripts", ["user_id"])

    # 6. transcript_segments
    op.create_table(
        "transcript_segments",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("transcript_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("meeting_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sequence_index", sa.Integer(), nullable=False),
        sa.Column("start_time", sa.Float(), nullable=False),
        sa.Column("end_time", sa.Float(), nullable=False),
        sa.Column("speaker_label", sa.String(), nullable=True),
        sa.Column("speaker", sa.String(), nullable=True),
        sa.Column("text", sa.String(), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(["meeting_id"], ["meetings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["transcript_id"], ["transcripts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "transcript_id", "sequence_index", name="transcript_segments_sequence_unique"
        ),
    )
    op.create_index(
        "idx_segments_transcript_seq", "transcript_segments", ["transcript_id", "sequence_index"]
    )
    op.create_index(
        "idx_segments_transcript_time", "transcript_segments", ["transcript_id", "start_time"]
    )
    op.create_index("idx_segments_speaker_label", "transcript_segments", ["speaker_label"])
    op.create_index("idx_segments_meeting_id", "transcript_segments", ["meeting_id"])

    # 7. meeting_analyses
    op.create_table(
        "meeting_analyses",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("meeting_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column("executive_summary", sa.String(), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("estimated_cost_usd", sa.Numeric(precision=10, scale=6), nullable=True),
        sa.Column("pricing_version", sa.String(), nullable=True),
        sa.Column(
            "verification_performed", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("verification_model", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["meeting_id"], ["meetings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("meeting_id"),
    )
    op.create_index("idx_analyses_user_id", "meeting_analyses", ["user_id"])
    op.create_index("idx_analyses_meeting_id", "meeting_analyses", ["meeting_id"])

    # 8. topics
    op.create_table(
        "topics",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("analysis_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("meeting_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("summary", sa.String(), nullable=True),
        sa.Column("sequence_index", sa.Integer(), nullable=False),
        sa.Column("start_time", sa.Float(), nullable=True),
        sa.Column("end_time", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(["analysis_id"], ["meeting_analyses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["meeting_id"], ["meetings.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_topics_analysis_id", "topics", ["analysis_id", "sequence_index"])
    op.create_index("idx_topics_meeting_id", "topics", ["meeting_id"])

    # 9. decisions
    confidence_level = postgresql.ENUM(
        "EXPLICIT", "INFERRED", name="confidence_level", create_type=False
    )
    confidence_level.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "decisions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("analysis_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("meeting_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("decision_text", sa.String(), nullable=False),
        sa.Column("sequence_index", sa.Integer(), nullable=False),
        sa.Column(
            "confidence",
            confidence_level,
            server_default="EXPLICIT",
            nullable=False,
        ),
        sa.Column("start_time", sa.Float(), nullable=True),
        sa.Column("end_time", sa.Float(), nullable=True),
        sa.Column(
            "evidence_segment_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["analysis_id"], ["meeting_analyses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["meeting_id"], ["meetings.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_decisions_analysis_id", "decisions", ["analysis_id", "sequence_index"])
    op.create_index("idx_decisions_meeting_id", "decisions", ["meeting_id"])
    op.create_index(
        "idx_decisions_evidence", "decisions", ["evidence_segment_ids"], postgresql_using="gin"
    )

    # 10. action_items
    op.create_table(
        "action_items",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("analysis_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("meeting_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action_text", sa.String(), nullable=False),
        sa.Column("owner", sa.String(), nullable=True),
        sa.Column("due_date", sa.String(), nullable=True),
        sa.Column("sequence_index", sa.Integer(), nullable=False),
        sa.Column("start_time", sa.Float(), nullable=True),
        sa.Column("end_time", sa.Float(), nullable=True),
        sa.Column(
            "evidence_segment_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["analysis_id"], ["meeting_analyses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["meeting_id"], ["meetings.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_action_items_analysis_id", "action_items", ["analysis_id", "sequence_index"]
    )
    op.create_index("idx_action_items_meeting_id", "action_items", ["meeting_id"])
    op.create_index(
        "idx_action_items_evidence",
        "action_items",
        ["evidence_segment_ids"],
        postgresql_using="gin",
    )

    # 11. risks
    op.create_table(
        "risks",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("analysis_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("meeting_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("risk_text", sa.String(), nullable=False),
        sa.Column("sequence_index", sa.Integer(), nullable=False),
        sa.Column("start_time", sa.Float(), nullable=True),
        sa.Column("end_time", sa.Float(), nullable=True),
        sa.Column(
            "evidence_segment_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["analysis_id"], ["meeting_analyses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["meeting_id"], ["meetings.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_risks_analysis_id", "risks", ["analysis_id", "sequence_index"])
    op.create_index("idx_risks_meeting_id", "risks", ["meeting_id"])
    op.create_index("idx_risks_evidence", "risks", ["evidence_segment_ids"], postgresql_using="gin")

    # 12. open_questions
    op.create_table(
        "open_questions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("analysis_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("meeting_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("question_text", sa.String(), nullable=False),
        sa.Column("sequence_index", sa.Integer(), nullable=False),
        sa.Column("start_time", sa.Float(), nullable=True),
        sa.Column("end_time", sa.Float(), nullable=True),
        sa.Column(
            "evidence_segment_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["analysis_id"], ["meeting_analyses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["meeting_id"], ["meetings.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_open_questions_analysis_id", "open_questions", ["analysis_id", "sequence_index"]
    )
    op.create_index("idx_open_questions_meeting_id", "open_questions", ["meeting_id"])
    op.create_index(
        "idx_open_questions_evidence",
        "open_questions",
        ["evidence_segment_ids"],
        postgresql_using="gin",
    )

    # 13. chat_sessions & chat_messages (Phase 12 Future)
    chat_role = postgresql.ENUM("USER", "ASSISTANT", "SYSTEM", name="chat_role", create_type=False)
    chat_role.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "chat_sessions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("meeting_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["meeting_id"], ["meetings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "chat_messages",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("meeting_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", chat_role, nullable=False),
        sa.Column("content", sa.String(), nullable=False),
        sa.Column(
            "citation_segment_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["meeting_id"], ["meetings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"], ["chat_sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("chat_messages")
    op.drop_table("chat_sessions")
    op.drop_table("open_questions")
    op.drop_table("risks")
    op.drop_table("action_items")
    op.drop_table("decisions")
    op.drop_table("topics")
    op.drop_table("meeting_analyses")
    op.drop_table("transcript_segments")
    op.drop_table("transcripts")
    op.drop_table("processing_jobs")
    op.drop_table("recordings")
    op.drop_table("meetings")
    op.drop_table("users")

    # Drop enums
    op.execute("DROP TYPE IF EXISTS chat_role")
    op.execute("DROP TYPE IF EXISTS confidence_level")
    op.execute("DROP TYPE IF EXISTS job_stage")
    op.execute("DROP TYPE IF EXISTS job_status")
    op.execute("DROP TYPE IF EXISTS recording_status")
    op.execute("DROP TYPE IF EXISTS meeting_status")
