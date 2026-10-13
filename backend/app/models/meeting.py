import enum
import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import Date, DateTime, Enum, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.meeting_analysis import MeetingAnalysis
    from app.models.processing_job import ProcessingJob
    from app.models.recording import Recording
    from app.models.transcript import Transcript, TranscriptSegment
    from app.models.user import User


class MeetingStatus(enum.StrEnum):
    CREATED = "CREATED"
    ACTIVE = "ACTIVE"
    DELETING = "DELETING"
    PURGED = "PURGED"


class Meeting(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Aggregate root container for meeting recordings, transcript, and analysis."""

    __tablename__ = "meetings"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        index=True,
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    meeting_date: Mapped[date] = mapped_column(
        Date,
        default=func.current_date(),
        nullable=False,
    )
    status: Mapped[MeetingStatus] = mapped_column(
        Enum(MeetingStatus, name="meeting_status"),
        default=MeetingStatus.CREATED,
        index=True,
        nullable=False,
    )
    speaker_mappings: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        default=dict,
        nullable=False,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="meetings")
    recording: Mapped["Recording | None"] = relationship(
        "Recording",
        back_populates="meeting",
        uselist=False,
        cascade="all, delete-orphan",
    )
    job: Mapped["ProcessingJob | None"] = relationship(
        "ProcessingJob",
        back_populates="meeting",
        uselist=False,
        cascade="all, delete-orphan",
    )
    transcript: Mapped["Transcript | None"] = relationship(
        "Transcript",
        back_populates="meeting",
        uselist=False,
        cascade="all, delete-orphan",
    )
    transcript_segments: Mapped[list["TranscriptSegment"]] = relationship(
        "TranscriptSegment",
        back_populates="meeting",
        cascade="all, delete-orphan",
    )
    analysis: Mapped["MeetingAnalysis | None"] = relationship(
        "MeetingAnalysis",
        back_populates="meeting",
        uselist=False,
        cascade="all, delete-orphan",
    )

    def __init__(
        self,
        user_id: uuid.UUID,
        title: str,
        description: str | None = None,
        status: MeetingStatus = MeetingStatus.CREATED,
        speaker_mappings: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            user_id=user_id,
            title=title,
            description=description,
            status=status,
            speaker_mappings=speaker_mappings or {},
            **kwargs,
        )
