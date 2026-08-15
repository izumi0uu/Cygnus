"""Add durable governance signals.

Revision ID: 20260808_01
Revises: 20260727_01
Create Date: 2026-08-08 00:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260808_01"
down_revision: str | None = "20260727_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    _ = op.create_table(
        "governance_signals",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("signal_ref", sa.String(length=220), nullable=False),
        sa.Column("signal_type", sa.String(length=40), nullable=False),
        sa.Column("object_ref", sa.String(length=320), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("object_type", sa.String(length=50), nullable=False),
        sa.Column("page_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("audience_binding_ref", sa.String(length=220), nullable=True),
        sa.Column(
            "audience_filter", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column(
            "affected_surfaces", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column(
            "trigger_signals",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("evidence_source_type", sa.String(length=40), nullable=False),
        sa.Column("freshness", sa.String(length=20), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("evidence_excerpt", sa.Text(), nullable=False),
        sa.Column("queue_owner", sa.String(length=220), nullable=True),
        sa.Column(
            "status", sa.String(length=20), server_default="active", nullable=False
        ),
        sa.Column(
            "observed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=False),
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
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint(
            "signal_type IN ('ticket_cluster', 'human_rewrite', 'source_failure', "
            "'release_delta', 'incident_delta')",
            name="ck_governance_signals_type",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'resolved', 'dismissed')",
            name="ck_governance_signals_status",
        ),
        sa.CheckConstraint(
            "freshness IN ('fresh', 'stale', 'unknown')",
            name="ck_governance_signals_freshness",
        ),
        sa.CheckConstraint(
            "audience_filter IS NOT NULL OR "
            "(audience_binding_ref IS NOT NULL AND page_id IS NOT NULL)",
            name="ck_governance_signals_audience",
        ),
        sa.CheckConstraint(
            "(status = 'active' AND resolved_at IS NULL) OR "
            "(status <> 'active' AND resolved_at IS NOT NULL)",
            name="ck_governance_signals_resolution",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"], ["employees.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["page_id"], ["wiki_pages.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("signal_ref"),
    )
    op.create_index(
        "ix_governance_signals_status_observed",
        "governance_signals",
        ["status", "observed_at"],
        unique=False,
    )
    op.create_index(
        "ix_governance_signals_page",
        "governance_signals",
        ["page_id"],
        unique=False,
    )
    op.create_index(
        "ix_governance_signals_source",
        "governance_signals",
        ["source_id"],
        unique=False,
    )
    op.create_index(
        "ix_governance_signals_object",
        "governance_signals",
        ["object_ref"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_governance_signals_object", table_name="governance_signals")
    op.drop_index("ix_governance_signals_source", table_name="governance_signals")
    op.drop_index("ix_governance_signals_page", table_name="governance_signals")
    op.drop_index(
        "ix_governance_signals_status_observed", table_name="governance_signals"
    )
    op.drop_table("governance_signals")
