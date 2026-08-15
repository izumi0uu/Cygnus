"""Add durable governance audience bindings.

Revision ID: 20260808_02
Revises: 20260808_01
Create Date: 2026-08-08 00:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260808_02"
down_revision: str | None = "20260808_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    _ = op.create_table(
        "governance_audience_bindings",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("page_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("object_ref", sa.String(length=320), nullable=False),
        sa.Column("variant_ref", sa.String(length=220), nullable=False),
        sa.Column("channel", sa.String(length=120), nullable=False),
        sa.Column("visibility", sa.String(length=20), nullable=False),
        sa.Column(
            "brands",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "product_lines",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "plans",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "regions",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "languages",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "product_versions",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "lifecycle_state",
            sa.String(length=20),
            server_default="active",
            nullable=False,
        ),
        sa.Column("binding_key", sa.String(length=64), nullable=False),
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
            "visibility IN ('internal', 'external')",
            name="ck_governance_audience_bindings_visibility",
        ),
        sa.CheckConstraint(
            "lifecycle_state IN ('active', 'held', 'removed')",
            name="ck_governance_audience_bindings_lifecycle",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"], ["employees.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["page_id"], ["wiki_pages.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("binding_key"),
    )
    op.create_index(
        "ix_governance_audience_bindings_object_state",
        "governance_audience_bindings",
        ["object_ref", "lifecycle_state"],
        unique=False,
    )
    op.create_index(
        "ix_governance_audience_bindings_page_state",
        "governance_audience_bindings",
        ["page_id", "lifecycle_state"],
        unique=False,
    )
    op.create_index(
        "ix_governance_audience_bindings_conflict",
        "governance_audience_bindings",
        ["object_ref", "channel", "visibility", "lifecycle_state"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_governance_audience_bindings_conflict",
        table_name="governance_audience_bindings",
    )
    op.drop_index(
        "ix_governance_audience_bindings_page_state",
        table_name="governance_audience_bindings",
    )
    op.drop_index(
        "ix_governance_audience_bindings_object_state",
        table_name="governance_audience_bindings",
    )
    op.drop_table("governance_audience_bindings")
