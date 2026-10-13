import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.meeting import Meeting
    from app.models.user import User


class RecordingStatus(enum.StrEnum):
    PRESIGNED = "PRESIGNED"
    UPLOADED = "UPLOADED"
    DELETED = "DELETED"


class Recording(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Media object storage metadata and lifecycle record."""

    __tablename__ = "recordings"

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
    storage_key: Mapped[str] = mapped_column(String, nullable=False)
    original_filename: Mapped[str] = mapped_column(String, nullable=False)
    content_type: Mapped[str] = mapped_column(String, nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[RecordingStatus] = mapped_column(
        Enum(RecordingStatus, name="recording_status"),
        default=RecordingStatus.PRESIGNED,
        nullable=False,
    )
    uploaded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Relationships
    meeting: Mapped["Meeting"] = relationship("Meeting", back_populates="recording")
    user: Mapped["User"] = relationship("User")

    def __init__(
        self,
        meeting_id: uuid.UUID,
        user_id: uuid.UUID,
        storage_key: str,
        original_filename: str,
        content_type: str,
        file_size_bytes: int,
        status: RecordingStatus = RecordingStatus.PRESIGNED,
        sha256_hash: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            meeting_id=meeting_id,
            user_id=user_id,
            storage_key=storage_key,
            original_filename=original_filename,
            content_type=content_type,
            file_size_bytes=file_size_bytes,
            status=status,
            sha256_hash=sha256_hash,
            **kwargs,
        )
