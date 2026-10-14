import uuid
from typing import Any
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


class UserRepository:
    """Repository for User account persistence and just-in-time provisioning."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        """Retrieves a user by primary key UUID."""
        stmt = select(User).where(User.id == user_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_email(self, email: str) -> User | None:
        """Retrieves a user by email address."""
        stmt = select(User).where(User.email == email)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def upsert_user(
        self,
        user_id: uuid.UUID,
        email: str,
        display_name: str | None = None,
    ) -> User:
        """Idempotently provisions or updates a user upon verified authentication.
        
        Uses PostgreSQL ON CONFLICT (id) DO UPDATE to guarantee safety under concurrent requests.
        """
        now = datetime.now(UTC)
        stmt = (
            insert(User)
            .values(
                id=user_id,
                email=email,
                display_name=display_name,
                is_active=True,
                created_at=now,
                updated_at=now,
            )
            .on_conflict_do_update(
                index_elements=[User.id],
                set_={
                    "email": email,
                    "updated_at": now,
                    # If display_name is provided, update it; otherwise leave existing
                    **({"display_name": display_name} if display_name else {}),
                },
            )
            .returning(User)
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        user = result.scalar_one()
        return user
