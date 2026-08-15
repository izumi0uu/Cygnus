"""Add explicit freshness attestation columns to sources.

Revision ID: 20260812_02
Revises: 20260812_01
Create Date: 2026-08-12 00:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260812_02"
down_revision: str | None = "20260812_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "sources",
        sa.Column(
            "freshness_state",
            sa.String(length=20),
            server_default=sa.text("'unknown'"),
            nullable=False,
            comment=(
                "Explicit freshness attestation: unknown | fresh | stale. "
                "Never inferred."
            ),
        ),
    )
    op.add_column(
        "sources",
        sa.Column(
            "freshness_actor_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
            comment="Employee who recorded the explicit freshness attestation.",
        ),
    )
    op.add_column(
        "sources",
        sa.Column(
            "freshness_reason",
            sa.Text(),
            nullable=True,
            comment="Why the explicit freshness attestation was recorded.",
        ),
    )
    op.add_column(
        "sources",
        sa.Column(
            "freshness_attested_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="When the explicit freshness attestation was recorded.",
        ),
    )
    op.add_column(
        "sources",
        sa.Column(
            "freshness_expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment=(
                "When a FRESH attestation lapses; expired attestations are never fresh."
            ),
        ),
    )
    op.create_check_constraint(
        "ck_sources_freshness_state",
        "sources",
        "freshness_state IN ('unknown', 'fresh', 'stale')",
    )
    op.create_foreign_key(
        "fk_sources_freshness_actor",
        "sources",
        "employees",
        ["freshness_actor_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_sources_freshness_state",
        "sources",
        ["freshness_state"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_sources_freshness_state", table_name="sources")
    op.drop_constraint("fk_sources_freshness_actor", "sources", type_="foreignkey")
    op.drop_constraint("ck_sources_freshness_state", "sources", type_="check")
    op.drop_column("sources", "freshness_expires_at")
    op.drop_column("sources", "freshness_attested_at")
    op.drop_column("sources", "freshness_reason")
    op.drop_column("sources", "freshness_actor_id")
    op.drop_column("sources", "freshness_state")
