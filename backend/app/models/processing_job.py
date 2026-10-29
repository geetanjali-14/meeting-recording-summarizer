import enum
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.meeting import Meeting
    from app.models.user import User


class JobStatus(enum.StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class JobStage(enum.StrEnum):
    CREATED = "CREATED"
    VALIDATING = "VALIDATING"
    EXTRACTING_AUDIO = "EXTRACTING_AUDIO"
    TRANSCRIBING = "TRANSCRIBING"
    DIARIZING = "DIARIZING"
    ANALYZING = "ANALYZING"
    VERIFYING = "VERIFYING"
    SAVING = "SAVING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class InvalidJobStateTransitionError(ValueError):
    """Raised when an illegal state machine transition is attempted."""

    pass


class ProcessingJob(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Asynchronous processing job with renewable worker lease tracking."""

    __tablename__ = "processing_jobs"

    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("meetings.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        index=True,
        nullable=False,
    )
    celery_task_id: Mapped[str | None] = mapped_column(
        String,
        index=True,
        nullable=True,
    )
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, name="job_status"),
        default=JobStatus.PENDING,
        nullable=False,
    )
    stage: Mapped[JobStage] = mapped_column(
        Enum(JobStage, name="job_stage"),
        default=JobStage.CREATED,
        nullable=False,
    )
    attempt: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String, nullable=True)
    error_message: Mapped[str | None] = mapped_column(String, nullable=True)
    worker_id: Mapped[str | None] = mapped_column(String, nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    enqueued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        nullable=False,
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    meeting: Mapped["Meeting"] = relationship("Meeting", back_populates="job")
    user: Mapped["User"] = relationship("User")

    __table_args__ = (
        Index("idx_jobs_status_stage", "status", "stage"),
        Index(
            "idx_jobs_lease_recovery",
            "status",
            "lease_expires_at",
            postgresql_where=(status == JobStatus.RUNNING),
        ),
    )

    def transition_to(
        self,
        new_status: JobStatus,
        new_stage: JobStage | None = None,
        error_message: str | None = None,
    ) -> None:
        """Transitions job status and stage according to architectural state machine rules."""
        # Completed jobs can only transition to PENDING (for restart)
        if self.status == JobStatus.COMPLETED:
            raise InvalidJobStateTransitionError(f"Cannot transition COMPLETED job to {new_status}")

        # Cancelled jobs cannot transition to running or completed
        if self.status == JobStatus.CANCELLED and new_status in (
            JobStatus.RUNNING,
            JobStatus.COMPLETED,
        ):
            raise InvalidJobStateTransitionError(f"Cannot transition CANCELLED job to {new_status}")

        self.status = new_status
        if new_stage is not None:
            self.stage = new_stage
        if error_message is not None:
            self.error_message = error_message
