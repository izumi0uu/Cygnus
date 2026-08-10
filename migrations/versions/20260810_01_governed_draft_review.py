"""Add versioned staged Wiki drafts and their durable pre-review outbox.

Revision ID: 20260810_01
Revises: 20260809_02
Create Date: 2026-08-10 00:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260810_01"
down_revision: str | None = "20260809_02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("wiki_page_drafts"):
        return

    columns = {column["name"] for column in inspector.get_columns("wiki_page_drafts")}
    if "version" not in columns:
        op.add_column(
            "wiki_page_drafts",
            sa.Column(
                "version",
                sa.Integer(),
                nullable=False,
                server_default="1",
            ),
        )

    inspector = sa.inspect(bind)
    if not inspector.has_table("wiki_draft_ai_pre_review_dispatches"):
        op.create_table(
            "wiki_draft_ai_pre_review_dispatches",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("draft_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("draft_version", sa.Integer(), nullable=False),
            sa.Column("revision_round", sa.Integer(), nullable=False),
            sa.Column("job_id", sa.String(length=180), nullable=False),
            sa.Column(
                "dispatch_status",
                sa.String(length=20),
                server_default="pending",
                nullable=False,
            ),
            sa.Column(
                "attempt_count",
                sa.Integer(),
                server_default="0",
                nullable=False,
            ),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("terminal_reason", sa.String(length=80), nullable=True),
            sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("enqueued_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.CheckConstraint(
                "dispatch_status IN ('pending', 'dispatching', 'enqueued', "
                "'running', 'completed', 'disabled', 'stale', 'failed')",
                name="ck_wiki_draft_ai_pre_review_dispatch_status",
            ),
            sa.CheckConstraint(
                "(dispatch_status IN ('pending', 'dispatching', 'enqueued', 'running') "
                "AND terminal_reason IS NULL) OR "
                "(dispatch_status IN ('completed', 'disabled', 'stale', 'failed') "
                "AND terminal_reason IS NOT NULL)",
                name="ck_wiki_draft_ai_pre_review_dispatch_terminal_reason",
            ),
            sa.CheckConstraint(
                "attempt_count >= 0",
                name="ck_wiki_draft_ai_pre_review_dispatch_attempts",
            ),
            sa.CheckConstraint(
                "draft_version >= 1 AND revision_round >= 0",
                name="ck_wiki_draft_ai_pre_review_dispatch_revision_values",
            ),
            sa.ForeignKeyConstraint(
                ["draft_id"],
                ["wiki_page_drafts.id"],
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "draft_id",
                "draft_version",
                "revision_round",
                name="uq_wiki_draft_ai_pre_review_dispatch_revision",
            ),
            sa.UniqueConstraint(
                "job_id",
                name="uq_wiki_draft_ai_pre_review_dispatch_job",
            ),
        )
        op.create_index(
            "ix_wiki_draft_ai_pre_review_dispatch_recovery",
            "wiki_draft_ai_pre_review_dispatches",
            ["dispatch_status", "next_attempt_at", "lease_expires_at"],
            unique=False,
        )

    # Existing committed queued rows predate the outbox.  Convert them into
    # immediately recoverable leases; pending rows receive normal durable
    # intents.  The revision key makes this backfill idempotent on rerun.
    op.execute(
        sa.text(
            """
            INSERT INTO wiki_draft_ai_pre_review_dispatches (
                id,
                draft_id,
                draft_version,
                revision_round,
                job_id,
                dispatch_status,
                attempt_count,
                lease_expires_at,
                created_at,
                updated_at
            )
            SELECT
                gen_random_uuid(),
                draft.id,
                draft.version,
                COALESCE(draft.revision_round, 0),
                'ai-pre-review:' || draft.id::text || ':' || draft.version::text
                    || ':' || COALESCE(draft.revision_round, 0)::text,
                CASE
                    WHEN draft.ai_check_status = 'queued' THEN 'dispatching'
                    ELSE 'pending'
                END,
                0,
                CASE
                    WHEN draft.ai_check_status = 'queued' THEN now()
                    ELSE NULL
                END,
                COALESCE(draft.updated_at, draft.created_at, now()),
                COALESCE(draft.updated_at, draft.created_at, now())
            FROM wiki_page_drafts AS draft
            WHERE draft.status = 'pending'
              AND draft.ai_check_status IN ('pending', 'queued')
            ON CONFLICT (draft_id, draft_version, revision_round) DO NOTHING
            """
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("wiki_draft_ai_pre_review_dispatches"):
        op.drop_table("wiki_draft_ai_pre_review_dispatches")

    inspector = sa.inspect(bind)
    if not inspector.has_table("wiki_page_drafts"):
        return
    columns = {column["name"] for column in inspector.get_columns("wiki_page_drafts")}
    if "version" in columns:
        op.drop_column("wiki_page_drafts", "version")
