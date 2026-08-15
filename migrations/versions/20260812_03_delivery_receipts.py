"""Add durable propagation delivery receipts and desired digests.

Revision ID: 20260812_03
Revises: 20260812_02
Create Date: 2026-08-12 00:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260812_03"
down_revision: str | None = "20260812_02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "governance_propagations",
        sa.Column(
            "desired_digest",
            sa.String(length=64),
            nullable=True,
            comment=(
                "SHA-256 of the canonical approved publication payload staged "
                "for outbound delivery; a signed acknowledgment must echo it "
                "exactly."
            ),
        ),
    )
    _ = op.create_table(
        "governance_propagation_deliveries",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("propagation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("publication_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("surface_id", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("command_id", sa.String(length=220), nullable=False),
        sa.Column("idempotency_key", sa.String(length=220), nullable=False),
        sa.Column("desired_digest", sa.String(length=64), nullable=False),
        sa.Column("canonical_payload", postgresql.JSONB(), nullable=False),
        sa.Column("expected_page_version", sa.Integer(), nullable=False),
        sa.Column("expected_approval_version", sa.Integer(), nullable=False),
        sa.Column("expected_binding_versions", postgresql.JSONB(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("correlation_id", sa.String(length=200), nullable=True),
        sa.Column("traceparent", sa.String(length=200), nullable=True),
        sa.Column(
            "attempt_evidence",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("acknowledged_digest", sa.String(length=64), nullable=True),
        sa.Column("acknowledged_version", sa.Integer(), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ack_receipt_ref", sa.String(length=220), nullable=True),
        sa.Column("ack_correlation_id", sa.String(length=200), nullable=True),
        sa.Column("ack_traceparent", sa.String(length=200), nullable=True),
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
            "status IN ('pending', 'in_flight', 'synced', 'failed', 'dead_letter')",
            name="ck_governance_propagation_deliveries_status",
        ),
        sa.CheckConstraint(
            "attempts >= 0 AND max_attempts >= 1",
            name="ck_governance_propagation_deliveries_attempts",
        ),
        sa.CheckConstraint(
            "expected_page_version >= 1 AND expected_approval_version >= 1",
            name="ck_governance_propagation_deliveries_versions",
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["employees.id"],
            name="fk_propagation_deliveries_actor",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["propagation_id"],
            ["governance_propagations.id"],
            name="fk_propagation_deliveries_propagation",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["publication_id"],
            ["governance_publications.id"],
            name="fk_propagation_deliveries_publication",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "command_id",
            name="uq_governance_propagation_deliveries_command_id",
        ),
        sa.UniqueConstraint(
            "idempotency_key",
            name="uq_governance_propagation_deliveries_idempotency_key",
        ),
        sa.UniqueConstraint(
            "propagation_id",
            name="uq_governance_propagation_deliveries_propagation",
        ),
    )
    op.create_index(
        "ix_governance_propagation_deliveries_status",
        "governance_propagation_deliveries",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_governance_propagation_deliveries_publication",
        "governance_propagation_deliveries",
        ["publication_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_governance_propagation_deliveries_publication",
        table_name="governance_propagation_deliveries",
    )
    op.drop_index(
        "ix_governance_propagation_deliveries_status",
        table_name="governance_propagation_deliveries",
    )
    op.drop_table("governance_propagation_deliveries")
    op.drop_column("governance_propagations", "desired_digest")
