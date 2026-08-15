"""Add durable governance write and publication ledger.

Revision ID: 20260727_01
Revises: 20260627_00
Create Date: 2026-07-27 14:41:56
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260727_01"
down_revision: str | None = "20260627_00"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    _ = op.create_table(
        "governance_ledger_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("draft_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=50), nullable=False),
        sa.Column("from_state", sa.String(length=30), nullable=True),
        sa.Column("to_state", sa.String(length=30), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("idempotency_key", sa.String(length=220), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["actor_id"], ["employees.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["draft_id"], ["wiki_page_drafts.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "draft_id",
            "sequence",
            name="uq_governance_ledger_events_draft_sequence",
        ),
        sa.UniqueConstraint("idempotency_key"),
    )
    op.create_index(
        "ix_governance_ledger_events_draft_recorded",
        "governance_ledger_events",
        ["draft_id", "recorded_at"],
        unique=False,
    )
    op.create_index(
        "ix_governance_ledger_events_type",
        "governance_ledger_events",
        ["event_type"],
        unique=False,
    )

    _ = op.create_table(
        "governance_publications",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("draft_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("page_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("approval_event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("publish_event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("command_id", sa.String(length=200), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("object_ref", sa.String(length=320), nullable=False),
        sa.Column("object_type", sa.String(length=50), nullable=False),
        sa.Column("object_version", sa.Integer(), nullable=False),
        sa.Column("action_key", sa.String(length=50), nullable=False),
        sa.Column(
            "target_channels", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("previous_object_status", sa.String(length=30), nullable=False),
        sa.Column("effective_object_status", sa.String(length=30), nullable=False),
        sa.Column("candidate", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("preview", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "opened_bindings", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column(
            "removed_bindings", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column(
            "held_bindings", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column(
            "action_log", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("published_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "published_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["approval_event_id"],
            ["governance_ledger_events.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["draft_id"], ["wiki_page_drafts.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["page_id"], ["wiki_pages.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["publish_event_id"],
            ["governance_ledger_events.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["published_by_id"], ["employees.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("command_id"),
        sa.UniqueConstraint("publish_event_id"),
    )
    op.create_index(
        "ix_governance_publications_draft_published",
        "governance_publications",
        ["draft_id", "published_at"],
        unique=False,
    )
    op.create_index(
        "ix_governance_publications_object_published",
        "governance_publications",
        ["object_ref", "published_at"],
        unique=False,
    )

    _ = op.create_table(
        "governance_propagations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("publication_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("surface_id", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "channel_refs", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column(
            "binding_refs", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column(
            "follow_up_commands",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("last_event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("updated_by_id", postgresql.UUID(as_uuid=True), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["last_event_id"],
            ["governance_ledger_events.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["publication_id"],
            ["governance_publications.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_id"], ["employees.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "publication_id",
            "surface_id",
            name="uq_governance_propagations_publication_surface",
        ),
    )
    op.create_index(
        "ix_governance_propagations_status",
        "governance_propagations",
        ["status"],
        unique=False,
    )

    # We only know each legacy draft's current persisted state. Record that
    # observation as one imported snapshot; do not invent intermediate history.
    op.execute(
        sa.text(
            """
            INSERT INTO governance_ledger_events (
                id,
                draft_id,
                sequence,
                event_type,
                from_state,
                to_state,
                actor_id,
                idempotency_key,
                reason,
                payload,
                occurred_at,
                recorded_at
            )
            SELECT
                gen_random_uuid(),
                draft.id,
                1,
                'state_imported',
                NULL,
                CASE draft.status
                    WHEN 'pending' THEN 'in_review'
                    ELSE draft.status
                END,
                COALESCE(draft.reviewed_by_id, draft.author_id),
                'legacy-state:' || draft.id::text || ':' || draft.status,
                'Imported from the pre-ledger WikiPageDraft snapshot',
                jsonb_build_object(
                    'origin', 'legacy_snapshot',
                    'source_status', draft.status,
                    'revision_round', draft.revision_round,
                    'page_id', draft.page_id
                ),
                COALESCE(draft.reviewed_at, draft.updated_at, draft.created_at, now()),
                now()
            FROM wiki_page_drafts AS draft
            """
        )
    )


def downgrade() -> None:
    op.drop_index(
        "ix_governance_propagations_status",
        table_name="governance_propagations",
    )
    op.drop_table("governance_propagations")
    op.drop_index(
        "ix_governance_publications_object_published",
        table_name="governance_publications",
    )
    op.drop_index(
        "ix_governance_publications_draft_published",
        table_name="governance_publications",
    )
    op.drop_table("governance_publications")
    op.drop_index(
        "ix_governance_ledger_events_type",
        table_name="governance_ledger_events",
    )
    op.drop_index(
        "ix_governance_ledger_events_draft_recorded",
        table_name="governance_ledger_events",
    )
    op.drop_table("governance_ledger_events")
