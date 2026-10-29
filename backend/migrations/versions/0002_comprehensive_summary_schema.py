"""Add comprehensive summary fields: speaker_contributions, context_and_details, next_steps, structured_data to meeting_analyses and topics.discussion_progression

Revision ID: 0002_comprehensive_summary
Revises: 0001_initial_schema
Create Date: 2026-10-29 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0002_comprehensive_summary"
down_revision: str | None = "0001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Add fields to meeting_analyses
    op.add_column(
        "meeting_analyses",
        sa.Column(
            "speaker_contributions",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "meeting_analyses",
        sa.Column(
            "context_and_details",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "meeting_analyses",
        sa.Column(
            "next_steps",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "meeting_analyses",
        sa.Column(
            "structured_data",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )

    # 2. Add discussion_progression to topics
    op.add_column(
        "topics",
        sa.Column(
            "discussion_progression",
            sa.String(),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("topics", "discussion_progression")
    op.drop_column("meeting_analyses", "structured_data")
    op.drop_column("meeting_analyses", "next_steps")
    op.drop_column("meeting_analyses", "context_and_details")
    op.drop_column("meeting_analyses", "speaker_contributions")
