"""Add durable ticket-cluster to draft promotion bindings.

Revision ID: 20260811_03
Revises: 20260811_02
Create Date: 2026-08-11 00:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260811_03"
down_revision: str | None = "20260811_02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    _ = op.create_table(
        "governance_ticket_draft_promotions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("signal_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("draft_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("command_id", sa.String(length=220), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("source_signal_version", sa.Integer(), nullable=False),
        sa.Column("expected_assignment_version", sa.Integer(), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "source_signal_version >= 1 AND expected_assignment_version >= 1",
            name="ck_governance_ticket_draft_promotions_versions",
        ),
        sa.CheckConstraint(
            "char_length(reason) BETWEEN 1 AND 2000",
            name="ck_governance_ticket_draft_promotions_reason",
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["employees.id"],
            name="fk_ticket_draft_promotions_actor",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["draft_id"],
            ["wiki_page_drafts.id"],
            name="fk_ticket_draft_promotions_draft",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["signal_id"],
            ["governance_signals.id"],
            name="fk_ticket_draft_promotions_signal",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "command_id",
            name="uq_governance_ticket_draft_promotions_command_id",
        ),
        sa.UniqueConstraint(
            "draft_id",
            name="uq_governance_ticket_draft_promotions_draft_id",
        ),
        sa.UniqueConstraint(
            "signal_id",
            name="uq_governance_ticket_draft_promotions_signal_id",
        ),
    )
    op.create_index(
        "ix_governance_ticket_draft_promotions_created",
        "governance_ticket_draft_promotions",
        ["created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_governance_ticket_draft_promotions_created",
        table_name="governance_ticket_draft_promotions",
    )
    op.drop_table("governance_ticket_draft_promotions")
