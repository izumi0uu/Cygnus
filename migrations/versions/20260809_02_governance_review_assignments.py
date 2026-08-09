"""Add durable review-owner assignments and transition history.

Revision ID: 20260809_02
Revises: 20260809_01
Create Date: 2026-08-09 00:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260809_02"
down_revision: str | None = "20260809_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("governance_review_assignments"):
        _ = op.create_table(
            "governance_review_assignments",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("signal_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column(
                "lifecycle_state",
                sa.String(length=20),
                server_default="unassigned",
                nullable=False,
            ),
            sa.Column("owner_ref", sa.String(length=220), nullable=True),
            sa.Column("escalation_reason", sa.Text(), nullable=True),
            sa.Column("version", sa.Integer(), server_default="1", nullable=False),
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
                "(lifecycle_state = 'unassigned' AND owner_ref IS NULL "
                "AND escalation_reason IS NULL) OR "
                "(lifecycle_state = 'assigned' AND owner_ref IS NOT NULL "
                "AND escalation_reason IS NULL) OR "
                "(lifecycle_state = 'escalated' AND owner_ref IS NOT NULL "
                "AND escalation_reason IS NOT NULL "
                "AND char_length(escalation_reason) BETWEEN 1 AND 2000)",
                name="ck_governance_review_assignments_state",
            ),
            sa.ForeignKeyConstraint(
                ["signal_id"],
                ["governance_signals.id"],
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "signal_id",
                name="uq_governance_review_assignments_signal",
            ),
        )
        op.create_index(
            "ix_governance_review_assignments_state",
            "governance_review_assignments",
            ["lifecycle_state", "updated_at"],
            unique=False,
        )
        op.create_index(
            "ix_governance_review_assignments_owner",
            "governance_review_assignments",
            ["owner_ref"],
            unique=False,
        )

    inspector = sa.inspect(bind)
    if not inspector.has_table("governance_review_assignment_events"):
        _ = op.create_table(
            "governance_review_assignment_events",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("assignment_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("sequence", sa.Integer(), nullable=False),
            sa.Column("command_id", sa.String(length=220), nullable=False),
            sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
            sa.Column("event_type", sa.String(length=40), nullable=False),
            sa.Column("from_state", sa.String(length=20), nullable=True),
            sa.Column("to_state", sa.String(length=20), nullable=False),
            sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("owner_ref", sa.String(length=220), nullable=True),
            sa.Column("reason", sa.Text(), nullable=False),
            sa.Column(
                "occurred_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.CheckConstraint(
                "event_type IN ('initialized', 'assigned', 'reassigned', "
                "'escalated', 'released')",
                name="ck_governance_review_assignment_events_type",
            ),
            sa.CheckConstraint(
                "to_state IN ('unassigned', 'assigned', 'escalated')",
                name="ck_governance_review_assignment_events_state",
            ),
            sa.CheckConstraint(
                "char_length(reason) BETWEEN 1 AND 2000",
                name="ck_governance_review_assignment_events_reason",
            ),
            sa.ForeignKeyConstraint(
                ["assignment_id"],
                ["governance_review_assignments.id"],
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("command_id"),
            sa.UniqueConstraint(
                "assignment_id",
                "sequence",
                name="uq_governance_review_assignment_events_sequence",
            ),
        )
        op.create_index(
            "ix_governance_review_assignment_events_assignment",
            "governance_review_assignment_events",
            ["assignment_id", "occurred_at"],
            unique=False,
        )
        op.create_index(
            "ix_governance_review_assignment_events_type",
            "governance_review_assignment_events",
            ["event_type"],
            unique=False,
        )

    signal_columns = {
        column["name"] for column in sa.inspect(bind).get_columns("governance_signals")
    }
    legacy_owner = (
        "NULLIF(BTRIM(signal.queue_owner), '')"
        if "queue_owner" in signal_columns
        else "NULL"
    )
    op.execute(
        sa.text(
            f"""
            INSERT INTO governance_review_assignments (
                id,
                signal_id,
                lifecycle_state,
                owner_ref,
                escalation_reason,
                version,
                created_at,
                updated_at
            )
            SELECT
                gen_random_uuid(),
                signal.id,
                CASE WHEN {legacy_owner} IS NULL THEN 'unassigned' ELSE 'assigned' END,
                {legacy_owner},
                NULL,
                1,
                signal.created_at,
                signal.updated_at
            FROM governance_signals AS signal
            WHERE NOT EXISTS (
                SELECT 1
                FROM governance_review_assignments AS assignment
                WHERE assignment.signal_id = signal.id
            )
            """
        )
    )
    op.execute(
        sa.text(
            """
            INSERT INTO governance_review_assignment_events (
                id,
                assignment_id,
                sequence,
                command_id,
                request_fingerprint,
                event_type,
                from_state,
                to_state,
                actor_id,
                owner_ref,
                reason,
                occurred_at
            )
            SELECT
                gen_random_uuid(),
                assignment.id,
                1,
                'review-assignment:init:' || signal.id::text,
                md5(
                    signal.signal_ref || ':' || assignment.lifecycle_state || ':' ||
                    COALESCE(assignment.owner_ref, '')
                ),
                'initialized',
                NULL,
                assignment.lifecycle_state,
                signal.created_by_id,
                assignment.owner_ref,
                'Review assignment initialized during durable-provider migration.',
                assignment.created_at
            FROM governance_review_assignments AS assignment
            JOIN governance_signals AS signal ON signal.id = assignment.signal_id
            WHERE NOT EXISTS (
                SELECT 1
                FROM governance_review_assignment_events AS event
                WHERE event.assignment_id = assignment.id
                  AND event.sequence = 1
            )
            """
        )
    )
    if "queue_owner" in signal_columns:
        op.drop_column("governance_signals", "queue_owner")


def downgrade() -> None:
    bind = op.get_bind()
    signal_columns = {
        column["name"] for column in sa.inspect(bind).get_columns("governance_signals")
    }
    if "queue_owner" not in signal_columns:
        op.add_column(
            "governance_signals",
            sa.Column("queue_owner", sa.String(length=220), nullable=True),
        )
    if sa.inspect(bind).has_table("governance_review_assignments"):
        op.execute(
            sa.text(
                """
                UPDATE governance_signals AS signal
                SET queue_owner = assignment.owner_ref
                FROM governance_review_assignments AS assignment
                WHERE assignment.signal_id = signal.id
                  AND assignment.lifecycle_state IN ('assigned', 'escalated')
                """
            )
        )
    if sa.inspect(bind).has_table("governance_review_assignment_events"):
        op.drop_table("governance_review_assignment_events")
    if sa.inspect(bind).has_table("governance_review_assignments"):
        op.drop_table("governance_review_assignments")
