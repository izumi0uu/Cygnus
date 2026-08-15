"""Add durable source dispatch executions and database-led deletion intent.

Revision ID: 20260812_04
Revises: 20260812_03
Create Date: 2026-08-12 00:00:00

Execution reliability (CYG-130 / CYG-128 source lifecycle):

- ``sources.dispatch_generation`` — monotonic pipeline cycle counter; worker
  attempts from an older generation are fenced as stale.
- ``sources.delete_requested_at`` — tombstone committed in the same transaction
  as the deletion intent, before any durable storage object is removed.
- ``source_dispatch_executions`` — outbox rows for each (source, generation,
  stage) worker handoff with a deterministic ARQ job id, lease fields, attempt
  budget and recovery index.
- ``source_deletions`` — database-led cleanup intent rows that survive the
  source row removal so partial object failures stay visible and retryable.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260812_04"
down_revision: str | None = "20260812_03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "sources",
        sa.Column(
            "dispatch_generation",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment="Monotonic execution generation. Bumped on every new "
            "pipeline cycle (initial ingest, retry, department-change "
            "re-ingest). Worker attempts from an older generation are fenced "
            "as stale.",
        ),
    )
    op.add_column(
        "sources",
        sa.Column(
            "delete_requested_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Tombstone: set in the same transaction as the source "
            "deletion intent, before any durable storage object is removed. "
            "The source row is removed only after cleanup completes.",
        ),
    )

    op.create_table(
        "source_dispatch_executions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("stage", sa.String(length=30), nullable=False),
        sa.Column("task_name", sa.String(length=120), nullable=False),
        sa.Column(
            "task_args",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("job_id", sa.String(length=200), nullable=False),
        sa.Column(
            "dispatch_status",
            sa.String(length=20),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lease_token", sa.String(length=64), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("enqueued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("terminal_reason", sa.String(length=80), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
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
            "dispatch_status IN ('pending', 'dispatching', 'enqueued', 'running', "
            "'completed', 'stale', 'failed')",
            name="ck_source_dispatch_execution_status",
        ),
        sa.CheckConstraint(
            "generation >= 1 AND attempt_count >= 0",
            name="ck_source_dispatch_execution_values",
        ),
        sa.CheckConstraint(
            "(dispatch_status IN ('pending', 'dispatching', 'enqueued', 'running') "
            "AND terminal_reason IS NULL) OR "
            "(dispatch_status IN ('completed', 'stale', 'failed') "
            "AND terminal_reason IS NOT NULL)",
            name="ck_source_dispatch_execution_terminal_reason",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["sources.id"],
            name="fk_source_dispatch_execution_source",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_id",
            "generation",
            "stage",
            name="uq_source_dispatch_execution_stage",
        ),
        sa.UniqueConstraint(
            "job_id",
            name="uq_source_dispatch_execution_job",
        ),
    )
    op.create_index(
        "ix_source_dispatch_execution_source",
        "source_dispatch_executions",
        ["source_id"],
        unique=False,
    )
    op.create_index(
        "ix_source_dispatch_execution_recovery",
        "source_dispatch_executions",
        ["dispatch_status", "next_attempt_at", "lease_expires_at"],
        unique=False,
    )

    op.create_table(
        "source_deletions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "requested_by_employee_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column("storage_prefix", sa.String(length=500), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'in_progress', 'completed', 'failed')",
            name="ck_source_deletions_status",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0",
            name="ck_source_deletions_attempts",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["sources.id"],
            name="fk_source_deletions_source",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_employee_id"],
            ["employees.id"],
            name="fk_source_deletions_requester",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_source_deletions_source",
        "source_deletions",
        ["source_id"],
        unique=False,
    )
    op.create_index(
        "ix_source_deletions_recovery",
        "source_deletions",
        ["status", "updated_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_source_deletions_recovery", table_name="source_deletions")
    op.drop_index("ix_source_deletions_source", table_name="source_deletions")
    op.drop_table("source_deletions")

    op.drop_index(
        "ix_source_dispatch_execution_recovery",
        table_name="source_dispatch_executions",
    )
    op.drop_index(
        "ix_source_dispatch_execution_source",
        table_name="source_dispatch_executions",
    )
    op.drop_table("source_dispatch_executions")

    op.drop_column("sources", "delete_requested_at")
    op.drop_column("sources", "dispatch_generation")
