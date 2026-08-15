"""Add durable governed consumption-feedback signals.

Revision ID: 20260810_02
Revises: 20260810_01
Create Date: 2026-08-10 00:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260810_02"
down_revision: str | None = "20260810_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_SIGNAL_TYPES = (
    "'answer_accepted', 'human_rewrite', 'escalated', "
    "'low_rating', 'unsupported_answer', 'stale_answer'"
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("governance_feedback_signals"):
        return

    _ = op.create_table(
        "governance_feedback_signals",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("signal_type", sa.String(length=40), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "audience_context",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("object_id", sa.String(length=320), nullable=True),
        sa.Column("page_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("draft_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_context_ref", sa.String(length=500), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
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
            f"signal_type IN ({_SIGNAL_TYPES})",
            name="ck_governance_feedback_signals_type",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(audience_context) = 'object' "
            "AND audience_context ?& ARRAY["
            "'visibility', 'brand', 'product_line', 'plan_tier', 'region', "
            "'language', 'product_version'] "
            "AND audience_context - ARRAY["
            "'visibility', 'brand', 'product_line', 'plan_tier', 'region', "
            "'language', 'product_version'] = '{}'::jsonb "
            "AND jsonb_typeof(audience_context -> 'visibility') = 'string' "
            "AND (audience_context ->> 'visibility') IN ('internal', 'external') "
            "AND (jsonb_typeof(audience_context -> 'brand') = 'null' OR "
            "(jsonb_typeof(audience_context -> 'brand') = 'string' "
            "AND (audience_context ->> 'brand') = "
            "btrim(audience_context ->> 'brand') "
            "AND char_length(audience_context ->> 'brand') BETWEEN 1 AND 200)) "
            "AND (jsonb_typeof(audience_context -> 'product_line') = 'null' OR "
            "(jsonb_typeof(audience_context -> 'product_line') = 'string' "
            "AND (audience_context ->> 'product_line') = "
            "btrim(audience_context ->> 'product_line') "
            "AND char_length(audience_context ->> 'product_line') BETWEEN 1 AND 200)) "
            "AND (jsonb_typeof(audience_context -> 'plan_tier') = 'null' OR "
            "(jsonb_typeof(audience_context -> 'plan_tier') = 'string' "
            "AND (audience_context ->> 'plan_tier') = "
            "btrim(audience_context ->> 'plan_tier') "
            "AND char_length(audience_context ->> 'plan_tier') BETWEEN 1 AND 200)) "
            "AND (jsonb_typeof(audience_context -> 'region') = 'null' OR "
            "(jsonb_typeof(audience_context -> 'region') = 'string' "
            "AND (audience_context ->> 'region') = "
            "btrim(audience_context ->> 'region') "
            "AND char_length(audience_context ->> 'region') BETWEEN 1 AND 200)) "
            "AND (jsonb_typeof(audience_context -> 'language') = 'null' OR "
            "(jsonb_typeof(audience_context -> 'language') = 'string' "
            "AND (audience_context ->> 'language') = "
            "btrim(audience_context ->> 'language') "
            "AND char_length(audience_context ->> 'language') BETWEEN 1 AND 200)) "
            "AND (jsonb_typeof(audience_context -> 'product_version') = 'null' OR "
            "(jsonb_typeof(audience_context -> 'product_version') = 'string' "
            "AND (audience_context ->> 'product_version') = "
            "btrim(audience_context ->> 'product_version') "
            "AND char_length(audience_context ->> 'product_version') "
            "BETWEEN 1 AND 200))",
            name="ck_governance_feedback_signals_audience_context",
        ),
        sa.CheckConstraint(
            "object_id IS NULL OR (object_id = btrim(object_id) "
            "AND char_length(object_id) BETWEEN 1 AND 320)",
            name="ck_governance_feedback_signals_object_id",
        ),
        sa.CheckConstraint(
            "source_context_ref IS NULL OR (source_context_ref = "
            "btrim(source_context_ref) AND char_length(source_context_ref) "
            "BETWEEN 1 AND 500)",
            name="ck_governance_feedback_signals_source_context_ref",
        ),
        sa.CheckConstraint(
            "notes IS NULL OR (notes = btrim(notes) "
            "AND char_length(notes) BETWEEN 1 AND 10000)",
            name="ck_governance_feedback_signals_notes",
        ),
        sa.ForeignKeyConstraint(["actor_id"], ["employees.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["page_id"], ["wiki_pages.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["draft_id"], ["wiki_page_drafts.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_governance_feedback_signals_actor_created",
        "governance_feedback_signals",
        ["actor_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_governance_feedback_signals_object",
        "governance_feedback_signals",
        ["object_id"],
        unique=False,
    )
    op.create_index(
        "ix_governance_feedback_signals_page",
        "governance_feedback_signals",
        ["page_id"],
        unique=False,
    )
    op.create_index(
        "ix_governance_feedback_signals_draft",
        "governance_feedback_signals",
        ["draft_id"],
        unique=False,
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("governance_feedback_signals"):
        return
    for index_name in (
        "ix_governance_feedback_signals_draft",
        "ix_governance_feedback_signals_page",
        "ix_governance_feedback_signals_object",
        "ix_governance_feedback_signals_actor_created",
    ):
        op.drop_index(index_name, table_name="governance_feedback_signals")
    op.drop_table("governance_feedback_signals")
