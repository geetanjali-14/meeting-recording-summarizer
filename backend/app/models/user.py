from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.meeting import Meeting


class User(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """User account model for authentication, ownership, and quota enforcement."""

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String, nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true"), nullable=False
    )
    quota_minutes_per_month: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Relationships
    meetings: Mapped[list["Meeting"]] = relationship(
        "Meeting",
        back_populates="user",
        cascade="all, delete-orphan",
    )

    def __init__(
        self,
        email: str,
        display_name: str | None = None,
        is_active: bool = True,
        quota_minutes_per_month: int | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            email=email,
            display_name=display_name,
            is_active=is_active,
            quota_minutes_per_month=quota_minutes_per_month,
            **kwargs,
        )
