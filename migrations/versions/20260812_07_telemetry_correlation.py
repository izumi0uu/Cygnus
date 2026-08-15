"""Add correlation/trace columns for end-to-end request tracing (CYG-142).

Revision ID: 20260812_07
Revises: 20260812_06
Create Date: 2026-08-12 00:00:00

Adds the two bounded columns that make one request traceable end-to-end:
- ``audit_log.correlation_id`` — canonical request ID (UUID) propagated from
  HTTP → MCP → ARQ job → audit row; indexed for cross-surface joins.
- ``audit_log.traceparent`` — W3C traceparent derived from the correlation ID.
- ``mcp_query_log.correlation_id`` / ``mcp_query_log.traceparent`` — same
  identity on MCP tool-execution rows so request→tool→job→audit joins hold.

Both columns are nullable and carry no payloads or secrets; the sanitized
identity lives in the runtime observability package
(``cygnus.observability``) and is written by the runtime shell's audit/log
services, not by the migration itself.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260812_07"
down_revision: str | None = "20260812_06"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: W3C traceparent has the fixed shape 00-<32 hex>-<16 hex>-<2 hex> (55 chars).
_TRACEPARENT_LENGTH = 55


def upgrade() -> None:
    op.add_column(
        "audit_log",
        sa.Column(
            "correlation_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
            comment="Canonical end-to-end request correlation ID (UUID).",
        ),
    )
    op.add_column(
        "audit_log",
        sa.Column(
            "traceparent",
            sa.String(length=_TRACEPARENT_LENGTH),
            nullable=True,
            comment="W3C traceparent derived from correlation_id.",
        ),
    )
    op.create_index(
        "ix_audit_log_correlation_id",
        "audit_log",
        ["correlation_id"],
        unique=False,
    )

    op.add_column(
        "mcp_query_log",
        sa.Column(
            "correlation_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
            comment="Canonical end-to-end request correlation ID (UUID).",
        ),
    )
    op.add_column(
        "mcp_query_log",
        sa.Column(
            "traceparent",
            sa.String(length=_TRACEPARENT_LENGTH),
            nullable=True,
            comment="W3C traceparent derived from correlation_id.",
        ),
    )
    op.create_index(
        "ix_mcp_query_log_correlation_id",
        "mcp_query_log",
        ["correlation_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_mcp_query_log_correlation_id", table_name="mcp_query_log")
    op.drop_column("mcp_query_log", "traceparent")
    op.drop_column("mcp_query_log", "correlation_id")

    op.drop_index("ix_audit_log_correlation_id", table_name="audit_log")
    op.drop_column("audit_log", "traceparent")
    op.drop_column("audit_log", "correlation_id")
