"""Make the recipient-scoped notification inbox migration-owned.

Revision ID: 20260809_01
Revises: 20260808_02
Create Date: 2026-08-09 00:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260809_01"
down_revision: str | None = "20260808_02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Local/dev historically received this table from Base.metadata.create_all.
    # Production must receive the same schema from Alembic. Preserve the
    # already-created local table while making fresh managed upgrades complete.
    # In the current chain the table is always owned by the pre-governance
    # baseline (20260627_00), so this guard returns early and this revision
    # never creates it.
    if sa.inspect(op.get_bind()).has_table("notifications"):
        return

    _ = op.create_table(
        "notifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("recipient_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("type", sa.String(length=80), nullable=False),
        sa.Column("subject", sa.String(length=200), nullable=False),
        sa.Column("body", sa.Text(), server_default="", nullable=False),
        sa.Column("target_type", sa.String(length=40), nullable=False),
        sa.Column("target_id", sa.String(length=100), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["employees.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["recipient_id"],
            ["employees.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_notifications_recipient_unread",
        "notifications",
        ["recipient_id", "read_at"],
        unique=False,
    )
    op.create_index(
        "ix_notifications_created_at",
        "notifications",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        "ix_notifications_target",
        "notifications",
        ["target_type", "target_id"],
        unique=False,
    )


def downgrade() -> None:
    # `notifications` is owned by the pre-governance baseline (20260627_00),
    # not by this revision: its upgrade guard early-returns whenever the table
    # exists, which is always true on the managed chain. Dropping it here would
    # destroy a baseline-owned table and break a head -> baseline downgrade
    # round-trip. The baseline downgrade removes the table.
    return
