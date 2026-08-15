"""Add canonical approval and publish scope guard columns to publications.

Revision ID: 20260812_01
Revises: 20260811_03
Create Date: 2026-08-12 00:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260812_01"
down_revision: str | None = "20260811_03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "governance_publications",
        sa.Column(
            "approval_digest",
            sa.String(length=64),
            server_default="",
            nullable=False,
        ),
    )
    op.add_column(
        "governance_publications",
        sa.Column(
            "scope_digest",
            sa.String(length=64),
            server_default="",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("governance_publications", "scope_digest")
    op.drop_column("governance_publications", "approval_digest")
