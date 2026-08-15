"""Add actor-bound tool command receipts for governed session draft writes.

CYG-140: propose/update accept an explicit actor-bound command_id and persist
one replay receipt in the same caller-owned transaction as the draft/ledger/
audit truth. Exact replay returns the stored result; reusing the command id
with different actor-bound input conflicts without writes.

Revision ID: 20260812_05
Revises: 20260812_04
Create Date: 2026-08-12 00:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260812_05"
down_revision: str | None = "20260812_04"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("governance_tool_command_receipts"):
        return

    _ = op.create_table(
        "governance_tool_command_receipts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tool_name", sa.String(length=60), nullable=False),
        sa.Column("command_id", sa.String(length=220), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column(
            "result_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "tool_name IN ('propose_knowledge_object', 'update_draft_object')",
            name="ck_governance_tool_command_receipts_tool_name",
        ),
        sa.CheckConstraint(
            "tool_name = btrim(tool_name) AND char_length(tool_name) BETWEEN 1 AND 60",
            name="ck_governance_tool_command_receipts_tool_name_shape",
        ),
        sa.CheckConstraint(
            "command_id = btrim(command_id) "
            "AND char_length(command_id) BETWEEN 1 AND 220",
            name="ck_governance_tool_command_receipts_command_id",
        ),
        sa.CheckConstraint(
            "char_length(request_fingerprint) = 64",
            name="ck_governance_tool_command_receipts_fingerprint",
        ),
        sa.ForeignKeyConstraint(["actor_id"], ["employees.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "actor_id",
            "tool_name",
            "command_id",
            name="uq_governance_tool_command_receipts_actor_tool_command",
        ),
    )
    op.create_index(
        "ix_governance_tool_command_receipts_actor_created",
        "governance_tool_command_receipts",
        ["actor_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("governance_tool_command_receipts"):
        return
    op.drop_index(
        "ix_governance_tool_command_receipts_actor_created",
        table_name="governance_tool_command_receipts",
    )
    op.drop_table("governance_tool_command_receipts")
