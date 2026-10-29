import enum
import uuid
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Boolean,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.meeting import Meeting
    from app.models.user import User


class ConfidenceLevel(enum.StrEnum):
    EXPLICIT = "EXPLICIT"
    INFERRED = "INFERRED"


class MeetingAnalysis(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Aggregate header for structured meeting intelligence extraction and cost audit."""

    __tablename__ = "meeting_analyses"

    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("meetings.id", ondelete="CASCADE"),
        unique=True,
        index=True,
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        index=True,
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String, nullable=False)
    model: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str | None] = mapped_column(String, nullable=True)
    executive_summary: Mapped[str | None] = mapped_column(String, nullable=True)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    estimated_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)
    pricing_version: Mapped[str | None] = mapped_column(String, nullable=True)
    verification_performed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    verification_model: Mapped[str | None] = mapped_column(String, nullable=True)
    speaker_contributions: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default="{}", nullable=False
    )
    context_and_details: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, server_default="[]", nullable=False
    )
    next_steps: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, server_default="[]", nullable=False
    )
    structured_data: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default="{}", nullable=False
    )

    # Relationships
    meeting: Mapped["Meeting"] = relationship("Meeting", back_populates="analysis")
    user: Mapped["User"] = relationship("User")
    topics: Mapped[list["Topic"]] = relationship(
        "Topic",
        back_populates="analysis",
        cascade="all, delete-orphan",
        order_by="Topic.sequence_index",
    )
    decisions: Mapped[list["Decision"]] = relationship(
        "Decision",
        back_populates="analysis",
        cascade="all, delete-orphan",
        order_by="Decision.sequence_index",
    )
    action_items: Mapped[list["ActionItem"]] = relationship(
        "ActionItem",
        back_populates="analysis",
        cascade="all, delete-orphan",
        order_by="ActionItem.sequence_index",
    )
    risks: Mapped[list["Risk"]] = relationship(
        "Risk",
        back_populates="analysis",
        cascade="all, delete-orphan",
        order_by="Risk.sequence_index",
    )
    open_questions: Mapped[list["OpenQuestion"]] = relationship(
        "OpenQuestion",
        back_populates="analysis",
        cascade="all, delete-orphan",
        order_by="OpenQuestion.sequence_index",
    )


class Topic(Base, UUIDPrimaryKeyMixin):
    """Chronological discussion topic extracted from transcript."""

    __tablename__ = "topics"

    analysis_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("meeting_analyses.id", ondelete="CASCADE"),
        nullable=False,
    )
    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("meetings.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String, nullable=False)
    summary: Mapped[str | None] = mapped_column(String, nullable=True)
    discussion_progression: Mapped[str | None] = mapped_column(String, nullable=True)
    sequence_index: Mapped[int] = mapped_column(Integer, nullable=False)
    start_time: Mapped[float | None] = mapped_column(Float, nullable=True)
    end_time: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Relationships
    analysis: Mapped["MeetingAnalysis"] = relationship("MeetingAnalysis", back_populates="topics")

    __table_args__ = (Index("idx_topics_analysis_id", "analysis_id", "sequence_index"),)


class Decision(Base, UUIDPrimaryKeyMixin):
    """Decision entity with deterministic evidence citations."""

    __tablename__ = "decisions"

    analysis_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("meeting_analyses.id", ondelete="CASCADE"),
        nullable=False,
    )
    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("meetings.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    decision_text: Mapped[str] = mapped_column(String, nullable=False)
    sequence_index: Mapped[int] = mapped_column(Integer, nullable=False)
    confidence: Mapped[ConfidenceLevel] = mapped_column(
        Enum(ConfidenceLevel, name="confidence_level"),
        default=ConfidenceLevel.EXPLICIT,
        nullable=False,
    )
    start_time: Mapped[float | None] = mapped_column(Float, nullable=True)
    end_time: Mapped[float | None] = mapped_column(Float, nullable=True)
    evidence_segment_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)),
        default=list,
        nullable=False,
    )

    # Relationships
    analysis: Mapped["MeetingAnalysis"] = relationship(
        "MeetingAnalysis", back_populates="decisions"
    )

    __table_args__ = (
        Index("idx_decisions_analysis_id", "analysis_id", "sequence_index"),
        Index("idx_decisions_evidence", "evidence_segment_ids", postgresql_using="gin"),
    )


class ActionItem(Base, UUIDPrimaryKeyMixin):
    """Action item with explicit/null owner and deadline, linked to evidence segments."""

    __tablename__ = "action_items"

    analysis_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("meeting_analyses.id", ondelete="CASCADE"),
        nullable=False,
    )
    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("meetings.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    action_text: Mapped[str] = mapped_column(String, nullable=False)
    owner: Mapped[str | None] = mapped_column(String, nullable=True)
    due_date: Mapped[str | None] = mapped_column(String, nullable=True)
    sequence_index: Mapped[int] = mapped_column(Integer, nullable=False)
    start_time: Mapped[float | None] = mapped_column(Float, nullable=True)
    end_time: Mapped[float | None] = mapped_column(Float, nullable=True)
    evidence_segment_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)),
        default=list,
        nullable=False,
    )

    # Relationships
    analysis: Mapped["MeetingAnalysis"] = relationship(
        "MeetingAnalysis", back_populates="action_items"
    )

    __table_args__ = (
        Index("idx_action_items_analysis_id", "analysis_id", "sequence_index"),
        Index("idx_action_items_evidence", "evidence_segment_ids", postgresql_using="gin"),
    )


class Risk(Base, UUIDPrimaryKeyMixin):
    """Risk/concern extracted from meeting discussion linked to evidence segments."""

    __tablename__ = "risks"

    analysis_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("meeting_analyses.id", ondelete="CASCADE"),
        nullable=False,
    )
    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("meetings.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    risk_text: Mapped[str] = mapped_column(String, nullable=False)
    sequence_index: Mapped[int] = mapped_column(Integer, nullable=False)
    start_time: Mapped[float | None] = mapped_column(Float, nullable=True)
    end_time: Mapped[float | None] = mapped_column(Float, nullable=True)
    evidence_segment_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)),
        default=list,
        nullable=False,
    )

    # Relationships
    analysis: Mapped["MeetingAnalysis"] = relationship("MeetingAnalysis", back_populates="risks")

    __table_args__ = (
        Index("idx_risks_analysis_id", "analysis_id", "sequence_index"),
        Index("idx_risks_evidence", "evidence_segment_ids", postgresql_using="gin"),
    )


class OpenQuestion(Base, UUIDPrimaryKeyMixin):
    """Unresolved inquiry extracted from meeting discussion linked to evidence segments."""

    __tablename__ = "open_questions"

    analysis_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("meeting_analyses.id", ondelete="CASCADE"),
        nullable=False,
    )
    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("meetings.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    question_text: Mapped[str] = mapped_column(String, nullable=False)
    sequence_index: Mapped[int] = mapped_column(Integer, nullable=False)
    start_time: Mapped[float | None] = mapped_column(Float, nullable=True)
    end_time: Mapped[float | None] = mapped_column(Float, nullable=True)
    evidence_segment_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)),
        default=list,
        nullable=False,
    )

    # Relationships
    analysis: Mapped["MeetingAnalysis"] = relationship(
        "MeetingAnalysis", back_populates="open_questions"
    )

    __table_args__ = (
        Index("idx_open_questions_analysis_id", "analysis_id", "sequence_index"),
        Index("idx_open_questions_evidence", "evidence_segment_ids", postgresql_using="gin"),
    )
