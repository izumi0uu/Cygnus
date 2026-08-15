"""Add leased lifecycle state to governed feedback routes.

Revision ID: 20260811_01
Revises: 20260810_03
Create Date: 2026-08-11 00:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260811_01"
down_revision: str | None = "20260810_03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_LEGACY_GOVERNANCE_SIGNAL_TYPES = (
    "'ticket_cluster', 'human_rewrite', 'source_failure', "
    "'release_delta', 'incident_delta'"
)
_GOVERNANCE_SIGNAL_TYPES = (
    f"{_LEGACY_GOVERNANCE_SIGNAL_TYPES}, 'low_rating', 'stale_answer'"
)
_ROUTE_STATE_CHECK = (
    "lifecycle_state IN ('queued', 'running', 'completed', 'blocked', 'failed')"
)
_ROUTE_LIFECYCLE_CHECK = (
    "(lifecycle_state = 'queued' AND lease_token IS NULL "
    "AND lease_expires_at IS NULL AND completed_at IS NULL "
    "AND outcome_signal_id IS NULL AND terminal_reason IS NULL) OR "
    "(lifecycle_state = 'running' AND lease_token IS NOT NULL "
    "AND lease_expires_at IS NOT NULL AND next_attempt_at IS NULL "
    "AND outcome_signal_id IS NULL AND completed_at IS NULL "
    "AND terminal_reason IS NULL AND last_error IS NULL) OR "
    "(lifecycle_state = 'completed' AND lease_token IS NULL "
    "AND lease_expires_at IS NULL AND next_attempt_at IS NULL "
    "AND outcome_signal_id IS NOT NULL AND completed_at IS NOT NULL "
    "AND terminal_reason IS NULL AND last_error IS NULL) OR "
    "(lifecycle_state = 'blocked' AND lease_token IS NULL "
    "AND lease_expires_at IS NULL AND next_attempt_at IS NULL "
    "AND terminal_reason IS NOT NULL AND completed_at IS NOT NULL "
    "AND last_error IS NULL AND outcome_signal_id IS NULL) OR "
    "(lifecycle_state = 'failed' AND lease_token IS NULL "
    "AND lease_expires_at IS NULL AND next_attempt_at IS NULL "
    "AND terminal_reason IS NOT NULL AND last_error IS NOT NULL "
    "AND completed_at IS NOT NULL AND outcome_signal_id IS NULL)"
)


def _replace_governance_signal_type_constraint(signal_types: str) -> None:
    op.drop_constraint(
        "ck_governance_signals_type",
        "governance_signals",
        type_="check",
    )
    op.create_check_constraint(
        "ck_governance_signals_type",
        "governance_signals",
        f"signal_type IN ({signal_types})",
    )


def upgrade() -> None:
    _replace_governance_signal_type_constraint(_GOVERNANCE_SIGNAL_TYPES)

    op.add_column(
        "governance_feedback_routes",
        sa.Column(
            "attempt_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
    )
    op.add_column(
        "governance_feedback_routes",
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
    )
    op.add_column(
        "governance_feedback_routes",
        sa.Column("lease_token", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "governance_feedback_routes",
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "governance_feedback_routes",
        sa.Column(
            "outcome_signal_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.add_column(
        "governance_feedback_routes",
        sa.Column("terminal_reason", sa.String(length=80), nullable=True),
    )
    op.add_column(
        "governance_feedback_routes",
        sa.Column("last_error", sa.Text(), nullable=True),
    )
    op.add_column(
        "governance_feedback_routes",
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )

    # CYG-118 routes were all queued under the former queued-only constraint.
    # Preserve that truth and give each one an immediately due timestamp without
    # manufacturing a terminal outcome.
    op.execute(
        sa.text(
            """
            UPDATE governance_feedback_routes
            SET next_attempt_at = now()
            WHERE lifecycle_state = 'queued' AND next_attempt_at IS NULL
            """
        )
    )

    op.create_foreign_key(
        "fk_governance_feedback_routes_outcome_signal",
        "governance_feedback_routes",
        "governance_signals",
        ["outcome_signal_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_governance_feedback_routes_outcome_signal",
        "governance_feedback_routes",
        ["outcome_signal_id"],
    )

    op.drop_constraint(
        "ck_governance_feedback_routes_state",
        "governance_feedback_routes",
        type_="check",
    )
    op.create_check_constraint(
        "ck_governance_feedback_routes_state",
        "governance_feedback_routes",
        _ROUTE_STATE_CHECK,
    )
    op.create_check_constraint(
        "ck_governance_feedback_routes_attempts",
        "governance_feedback_routes",
        "attempt_count >= 0",
    )
    op.create_check_constraint(
        "ck_governance_feedback_routes_lifecycle",
        "governance_feedback_routes",
        _ROUTE_LIFECYCLE_CHECK,
    )

    op.drop_index(
        "ix_governance_feedback_routes_queue",
        table_name="governance_feedback_routes",
    )
    op.create_index(
        "ix_governance_feedback_routes_queue",
        "governance_feedback_routes",
        [
            "lifecycle_state",
            "next_attempt_at",
            "lease_expires_at",
            "created_at",
        ],
        unique=False,
    )


def downgrade() -> None:
    # First make every post-upgrade route representable by the old queued-only
    # schema. This also removes every RESTRICT reference before outcome signals
    # are deleted below.
    op.execute(
        sa.text(
            """
            UPDATE governance_feedback_routes
            SET lifecycle_state = 'queued',
                attempt_count = 0,
                next_attempt_at = NULL,
                lease_token = NULL,
                lease_expires_at = NULL,
                outcome_signal_id = NULL,
                terminal_reason = NULL,
                last_error = NULL,
                completed_at = NULL
            """
        )
    )

    # The previous signal-type constraint cannot be restored while the types
    # introduced by this revision remain. Review assignments cascade from their
    # referenced governance signals.
    op.execute(
        sa.text(
            """
            DELETE FROM governance_signals
            WHERE signal_type IN ('low_rating', 'stale_answer')
            """
        )
    )
    _replace_governance_signal_type_constraint(_LEGACY_GOVERNANCE_SIGNAL_TYPES)

    op.drop_constraint(
        "ck_governance_feedback_routes_lifecycle",
        "governance_feedback_routes",
        type_="check",
    )
    op.drop_constraint(
        "ck_governance_feedback_routes_attempts",
        "governance_feedback_routes",
        type_="check",
    )
    op.drop_constraint(
        "ck_governance_feedback_routes_state",
        "governance_feedback_routes",
        type_="check",
    )
    op.create_check_constraint(
        "ck_governance_feedback_routes_state",
        "governance_feedback_routes",
        "lifecycle_state = 'queued'",
    )

    op.drop_index(
        "ix_governance_feedback_routes_queue",
        table_name="governance_feedback_routes",
    )
    op.create_index(
        "ix_governance_feedback_routes_queue",
        "governance_feedback_routes",
        ["route_kind", "lifecycle_state", "created_at"],
        unique=False,
    )

    op.drop_constraint(
        "uq_governance_feedback_routes_outcome_signal",
        "governance_feedback_routes",
        type_="unique",
    )
    op.drop_constraint(
        "fk_governance_feedback_routes_outcome_signal",
        "governance_feedback_routes",
        type_="foreignkey",
    )
    op.drop_column("governance_feedback_routes", "completed_at")
    op.drop_column("governance_feedback_routes", "last_error")
    op.drop_column("governance_feedback_routes", "terminal_reason")
    op.drop_column("governance_feedback_routes", "outcome_signal_id")
    op.drop_column("governance_feedback_routes", "lease_expires_at")
    op.drop_column("governance_feedback_routes", "lease_token")
    op.drop_column("governance_feedback_routes", "next_attempt_at")
    op.drop_column("governance_feedback_routes", "attempt_count")
