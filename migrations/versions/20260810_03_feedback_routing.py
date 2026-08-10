"""Add replay-safe feedback routing intents.

Revision ID: 20260810_03
Revises: 20260810_02
Create Date: 2026-08-10 00:00:00
"""

from __future__ import annotations

from collections.abc import Sequence
import hashlib
import json

from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine import RowMapping
from sqlalchemy.dialects import postgresql

revision: str = "20260810_03"
down_revision: str | None = "20260810_02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _legacy_feedback_fingerprint(row: RowMapping) -> str:
    audience_context = row["audience_context"]
    if not isinstance(audience_context, dict):
        raise RuntimeError("legacy feedback audience_context must be an object")
    payload: dict[str, object] = {
        "actor_id": str(row["actor_id"]),
        "signal_type": row["signal_type"],
        "audience_context": audience_context,
        "object_id": row["object_id"],
        "page_id": str(row["page_id"]) if row["page_id"] is not None else None,
        "draft_id": str(row["draft_id"]) if row["draft_id"] is not None else None,
        "notes": row["notes"],
        "source_context_ref": row["source_context_ref"],
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _backfill_feedback_command_identity(bind: sa.Connection) -> None:
    rows = bind.execute(
        sa.text(
            """
            SELECT id, command_id, signal_type, actor_id, audience_context,
                   object_id, page_id, draft_id, notes, source_context_ref
            FROM governance_feedback_signals
            WHERE command_id IS NULL OR request_fingerprint IS NULL
            ORDER BY id
            """
        )
    ).mappings()
    update_statement = sa.text(
        """
        UPDATE governance_feedback_signals
        SET command_id = :command_id,
            request_fingerprint = :request_fingerprint
        WHERE id = :signal_id
        """
    )
    for row in rows:
        signal_id = row["id"]
        bind.execute(
            update_statement,
            {
                "signal_id": signal_id,
                "command_id": row["command_id"] or f"legacy-feedback:{signal_id}",
                "request_fingerprint": _legacy_feedback_fingerprint(row),
            },
        )


def _backfill_feedback_routes() -> None:
    op.execute(
        sa.text(
            """
            INSERT INTO governance_feedback_routes (
                id,
                feedback_signal_id,
                route_kind,
                lifecycle_state
            )
            SELECT
                gen_random_uuid(),
                signal.id,
                CASE signal.signal_type
                    WHEN 'low_rating' THEN 'review'
                    WHEN 'stale_answer' THEN 'refresh'
                END,
                'queued'
            FROM governance_feedback_signals AS signal
            WHERE signal.signal_type IN ('low_rating', 'stale_answer')
            ON CONFLICT (feedback_signal_id, route_kind) DO NOTHING
            """
        )
    )


def _ensure_feedback_command_columns(
    bind: sa.Connection,
    inspector: sa.Inspector,
) -> None:
    if not inspector.has_table("governance_feedback_signals"):
        return

    columns = {
        column["name"]
        for column in inspector.get_columns("governance_feedback_signals")
    }
    if "command_id" not in columns:
        op.add_column(
            "governance_feedback_signals",
            sa.Column("command_id", sa.String(length=220), nullable=True),
        )
    if "request_fingerprint" not in columns:
        op.add_column(
            "governance_feedback_signals",
            sa.Column("request_fingerprint", sa.String(length=64), nullable=True),
        )

    _backfill_feedback_command_identity(bind)
    inspector = sa.inspect(bind)
    columns = {
        column["name"]
        for column in inspector.get_columns("governance_feedback_signals")
    }
    if "command_id" in columns:
        op.alter_column("governance_feedback_signals", "command_id", nullable=False)
    if "request_fingerprint" in columns:
        op.alter_column(
            "governance_feedback_signals",
            "request_fingerprint",
            nullable=False,
        )

    unique_names = {
        constraint.get("name")
        for constraint in inspector.get_unique_constraints(
            "governance_feedback_signals"
        )
    }
    if "uq_governance_feedback_signals_command_id" not in unique_names:
        op.create_unique_constraint(
            "uq_governance_feedback_signals_command_id",
            "governance_feedback_signals",
            ["command_id"],
        )

    check_names = {
        constraint.get("name")
        for constraint in inspector.get_check_constraints("governance_feedback_signals")
    }
    if "ck_governance_feedback_signals_command_id" not in check_names:
        op.create_check_constraint(
            "ck_governance_feedback_signals_command_id",
            "governance_feedback_signals",
            "command_id = btrim(command_id) AND char_length(command_id) BETWEEN 1 AND 220",
        )
    if "ck_governance_feedback_signals_request_fingerprint" not in check_names:
        op.create_check_constraint(
            "ck_governance_feedback_signals_request_fingerprint",
            "governance_feedback_signals",
            "char_length(request_fingerprint) = 64",
        )


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    _ensure_feedback_command_columns(bind, inspector)

    inspector = sa.inspect(bind)
    if not inspector.has_table("governance_feedback_signals"):
        return
    if not inspector.has_table("governance_feedback_routes"):
        _ = op.create_table(
            "governance_feedback_routes",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column(
                "feedback_signal_id",
                postgresql.UUID(as_uuid=True),
                nullable=False,
            ),
            sa.Column("route_kind", sa.String(length=20), nullable=False),
            sa.Column(
                "lifecycle_state",
                sa.String(length=20),
                server_default="queued",
                nullable=False,
            ),
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
                "route_kind IN ('review', 'refresh')",
                name="ck_governance_feedback_routes_kind",
            ),
            sa.CheckConstraint(
                "lifecycle_state = 'queued'",
                name="ck_governance_feedback_routes_state",
            ),
            sa.ForeignKeyConstraint(
                ["feedback_signal_id"],
                ["governance_feedback_signals.id"],
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "feedback_signal_id",
                "route_kind",
                name="uq_governance_feedback_routes_signal_kind",
            ),
        )
        op.create_index(
            "ix_governance_feedback_routes_queue",
            "governance_feedback_routes",
            ["route_kind", "lifecycle_state", "created_at"],
            unique=False,
        )

    _backfill_feedback_routes()


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("governance_feedback_routes"):
        op.drop_index(
            "ix_governance_feedback_routes_queue",
            table_name="governance_feedback_routes",
        )
        op.drop_table("governance_feedback_routes")

    inspector = sa.inspect(bind)
    if not inspector.has_table("governance_feedback_signals"):
        return
    check_names = {
        constraint.get("name")
        for constraint in inspector.get_check_constraints("governance_feedback_signals")
    }
    for name in (
        "ck_governance_feedback_signals_request_fingerprint",
        "ck_governance_feedback_signals_command_id",
    ):
        if name in check_names:
            op.drop_constraint(name, "governance_feedback_signals", type_="check")
    unique_names = {
        constraint.get("name")
        for constraint in inspector.get_unique_constraints(
            "governance_feedback_signals"
        )
    }
    if "uq_governance_feedback_signals_command_id" in unique_names:
        op.drop_constraint(
            "uq_governance_feedback_signals_command_id",
            "governance_feedback_signals",
            type_="unique",
        )
    columns = {
        column["name"]
        for column in inspector.get_columns("governance_feedback_signals")
    }
    if "request_fingerprint" in columns:
        op.drop_column("governance_feedback_signals", "request_fingerprint")
    if "command_id" in columns:
        op.drop_column("governance_feedback_signals", "command_id")
