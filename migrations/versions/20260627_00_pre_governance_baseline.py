"""Create the pre-governance schema baseline.

This migration freezes the entire application schema as it existed before the
governance era (all tables created via ``Base.metadata.create_all`` up to
2026-07-27, commit 7702276): every pre-governance table, enum, constraint and
index. Later governance migrations build on top of this root.

Revision ID: 20260627_00
Revises:
Create Date: 2026-08-12
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from pgvector.sqlalchemy import HALFVEC, Vector

revision: str = "20260627_00"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The only database-level enum predating governance. Created explicitly so the
# upgrade is deterministic and the downgrade can drop it.
skill_status = postgresql.ENUM(
    "active",
    "processing",
    "deleting",
    "deprecated",
    "archived",
    name="skill_status",
    create_type=False,
)


def upgrade() -> None:
    # Vector/HALFVEC columns require the pgvector extension. IF NOT EXISTS keeps
    # this idempotent for stacks that already bootstrap the extension.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute(
        "CREATE TYPE skill_status AS ENUM ('active', 'processing', 'deleting', "
        "'deprecated', 'archived')"
    )

    _ = op.create_table(
        "app_config",
        sa.Column(
            "key",
            sa.String(length=100),
            nullable=False,
        ),
        sa.Column(
            "value",
            sa.Text(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("key"),
    )
    _ = op.create_table(
        "audit_log",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "principal_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment="Employee or agent ID",
        ),
        sa.Column(
            "principal_type",
            sa.String(length=20),
            nullable=False,
            comment="human or agent",
        ),
        sa.Column(
            "action",
            sa.String(length=50),
            nullable=False,
            comment="Action attempted (read, list, delete...)",
        ),
        sa.Column(
            "resource_type",
            sa.String(length=50),
            nullable=False,
            comment="Type of resource: source, wiki_page, etc.",
        ),
        sa.Column(
            "resource_id",
            sa.String(length=100),
            nullable=False,
            comment="UUID or identifier of the resource",
        ),
        sa.Column(
            "decision",
            sa.String(length=10),
            nullable=False,
            comment="allow or deny",
        ),
        sa.Column(
            "reason",
            sa.Text(),
            comment="Human-readable reason for the decision",
        ),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            comment="Extra context (IP, user agent, request ID...)",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_audit_log_principal", "audit_log", ["principal_id"], unique=False
    )
    op.create_index(
        "ix_audit_log_resource",
        "audit_log",
        ["resource_type", "resource_id"],
        unique=False,
    )
    op.create_index("ix_audit_log_timestamp", "audit_log", ["timestamp"], unique=False)
    _ = op.create_table(
        "departments",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "name",
            sa.String(length=200),
            nullable=False,
        ),
        sa.Column(
            "description",
            sa.Text(),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    _ = op.create_table(
        "embedding_jobs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "model_spec_id",
            sa.String(length=128),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
        ),
        sa.Column(
            "total_pages",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "done_pages",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "error_message",
            sa.Text(),
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
        ),
        sa.Column(
            "finished_at",
            sa.DateTime(timezone=True),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_embedding_jobs_status",
        "embedding_jobs",
        ["status", "created_at"],
        unique=False,
    )
    _ = op.create_table(
        "employees",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "name",
            sa.String(length=200),
            nullable=False,
        ),
        sa.Column(
            "email",
            sa.String(length=200),
            nullable=False,
        ),
        sa.Column(
            "password_hash",
            sa.String(length=500),
            comment="bcrypt hash of password",
        ),
        sa.Column(
            "role",
            sa.String(length=20),
            nullable=False,
            comment="admin or employee — system-level role",
        ),
        sa.Column(
            "global_role",
            sa.String(length=30),
            nullable=False,
            comment="viewer, contributor, knowledge_manager, or admin",
        ),
        sa.Column(
            "mcp_token",
            sa.String(length=500),
            comment="DEPRECATED — legacy plaintext token, no longer read or written",
        ),
        sa.Column(
            "mcp_token_hash",
            sa.String(length=64),
            comment="HMAC-SHA256(pepper, token) — primary lookup key for MCP auth",
        ),
        sa.Column(
            "mcp_token_prefix",
            sa.String(length=12),
            comment="First 12 chars of the token for UI display (e.g. ark_aBcD…)",
        ),
        sa.Column(
            "mcp_token_rotated_at",
            sa.DateTime(timezone=True),
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
        ),
        sa.Column(
            "last_connected",
            sa.DateTime(timezone=True),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("email"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("mcp_token"),
    )
    op.create_index("ix_employees_email", "employees", ["email"], unique=False)
    op.create_index("ix_employees_mcp_token", "employees", ["mcp_token"], unique=False)
    op.create_index(
        "ix_employees_mcp_token_hash",
        "employees",
        ["mcp_token_hash"],
        unique=True,
        postgresql_where=sa.text("mcp_token_hash IS NOT NULL"),
    )
    _ = op.create_table(
        "knowledge_types",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "slug",
            sa.String(length=50),
            nullable=False,
            comment="URL-safe identifier, e.g. 'sop', 'product', 'hr-policy'",
        ),
        sa.Column(
            "name",
            sa.String(length=100),
            nullable=False,
            comment="Display name, e.g. 'Standard Operating Procedure'",
        ),
        sa.Column(
            "color",
            sa.String(length=20),
            comment="Hex color for UI badge",
        ),
        sa.Column(
            "description",
            sa.Text(),
        ),
        sa.Column(
            "sort_order",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("slug"),
        sa.PrimaryKeyConstraint("id"),
    )
    _ = op.create_table(
        "notes",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "title",
            sa.String(length=500),
        ),
        sa.Column(
            "content",
            sa.Text(),
        ),
        sa.Column(
            "note_type",
            sa.String(length=50),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    _ = op.create_table(
        "oauth_clients",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "client_id",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "name",
            sa.String(length=200),
            nullable=False,
        ),
        sa.Column(
            "redirect_uris",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_oauth_clients_client_id", "oauth_clients", ["client_id"], unique=True
    )
    _ = op.create_table(
        "skills",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "name",
            sa.String(length=200),
            nullable=False,
        ),
        sa.Column(
            "slug",
            sa.String(length=200),
            nullable=False,
        ),
        sa.Column(
            "scope_type",
            sa.String(length=20),
            nullable=False,
            comment="Scope type: global, project, department, team",
        ),
        sa.Column(
            "scope_id",
            postgresql.UUID(as_uuid=True),
            comment="Scope entity ID. Null for global scope.",
        ),
        sa.Column(
            "current_version",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "version_hash",
            sa.String(length=64),
        ),
        sa.Column(
            "storage_path",
            sa.String(length=1000),
        ),
        sa.Column(
            "status",
            skill_status,
            nullable=False,
            server_default="active",
        ),
        sa.Column(
            "is_system",
            sa.Boolean(),
            nullable=False,
            server_default="false",
            comment="True for skills seeded from source code. Immutable via API.",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_index("ix_skills_slug", "skills", ["slug"], unique=True)
    _ = op.create_table(
        "stats_daily_rollup",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "date",
            sa.DateTime(timezone=True),
            nullable=False,
            comment="UTC date the metric covers (midnight UTC)",
        ),
        sa.Column(
            "metric_key",
            sa.String(length=80),
            nullable=False,
            comment="e.g. wiki.pages.total, mcp.queries.zero_result, draft.pending",
        ),
        sa.Column(
            "dimensions",
            postgresql.JSONB(astext_type=sa.Text()),
            comment="{department_id, project_id, tool_name, source}",
        ),
        sa.Column(
            "dimensions_hash",
            sa.String(length=64),
            nullable=False,
            comment="md5 of canonical-serialized dimensions; empty string when dimensions is NULL",
        ),
        sa.Column(
            "value_numeric",
            sa.Float(),
        ),
        sa.Column(
            "value_json",
            postgresql.JSONB(astext_type=sa.Text()),
        ),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "date", "metric_key", "dimensions_hash", name="uq_stats_rollup_keys"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_stats_rollup_date", "stats_daily_rollup", ["date"], unique=False
    )
    op.create_index(
        "ix_stats_rollup_metric",
        "stats_daily_rollup",
        ["metric_key", "date"],
        unique=False,
    )
    _ = op.create_table(
        "wiki_pages",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "slug",
            sa.String(length=300),
            nullable=False,
        ),
        sa.Column(
            "title",
            sa.String(length=500),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            comment="Lifecycle status: seed | developing | mature | evergreen",
        ),
        sa.Column(
            "content_md",
            sa.Text(),
            nullable=False,
        ),
        sa.Column(
            "summary",
            sa.Text(),
            nullable=False,
        ),
        sa.Column(
            "scope_type",
            sa.String(length=20),
            nullable=False,
            comment="Scope type: global or project",
        ),
        sa.Column(
            "scope_id",
            postgresql.UUID(as_uuid=True),
            comment="Project/workspace ID. Null for global scope.",
        ),
        sa.Column(
            "knowledge_type_slugs",
            postgresql.ARRAY(sa.String()),
            nullable=False,
        ),
        sa.Column(
            "source_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            nullable=False,
        ),
        sa.Column(
            "version",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "orphaned",
            sa.Boolean(),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_wiki_pages_status", "wiki_pages", ["status"], unique=False)
    _ = op.create_table(
        "employee_departments",
        sa.Column(
            "employee_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "department_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["employee_id"], ["employees.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["department_id"], ["departments.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("employee_id", "department_id"),
    )
    op.create_index(
        "ix_employee_departments_department_id",
        "employee_departments",
        ["department_id"],
        unique=False,
    )
    _ = op.create_table(
        "mcp_query_log",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "employee_id",
            postgresql.UUID(as_uuid=True),
            comment="Caller; NULL if token resolution failed before call",
        ),
        sa.Column(
            "tool_name",
            sa.String(length=80),
            nullable=False,
            comment="MCP tool invoked: search_wiki, read_wiki_page, propose_wiki_edit, ...",
        ),
        sa.Column(
            "query_text",
            sa.Text(),
            comment="Search/query string when applicable",
        ),
        sa.Column(
            "result_count",
            sa.Integer(),
        ),
        sa.Column(
            "latency_ms",
            sa.Integer(),
        ),
        sa.Column(
            "scope_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            comment="Department/project/filters used for the call",
        ),
        sa.Column(
            "result_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            comment="IDs returned (wiki_page_id or source_id list)",
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            comment="ok | error | denied",
        ),
        sa.Column(
            "error_message",
            sa.Text(),
        ),
        sa.ForeignKeyConstraint(["employee_id"], ["employees.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_mcp_query_log_created_at", "mcp_query_log", ["created_at"], unique=False
    )
    op.create_index(
        "ix_mcp_query_log_employee_id", "mcp_query_log", ["employee_id"], unique=False
    )
    op.create_index(
        "ix_mcp_query_log_tool_name", "mcp_query_log", ["tool_name"], unique=False
    )
    op.create_index(
        "ix_mcp_query_log_zero_result",
        "mcp_query_log",
        ["created_at", "result_count"],
        unique=False,
    )
    _ = op.create_table(
        "notifications",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "recipient_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "type",
            sa.String(length=80),
            nullable=False,
        ),
        sa.Column(
            "subject",
            sa.String(length=200),
            nullable=False,
        ),
        sa.Column(
            "body",
            sa.Text(),
            nullable=False,
        ),
        sa.Column(
            "target_type",
            sa.String(length=40),
            nullable=False,
        ),
        sa.Column(
            "target_id",
            sa.String(length=100),
            nullable=False,
        ),
        sa.Column(
            "actor_id",
            postgresql.UUID(as_uuid=True),
            comment="Employee who caused the event (author/reviewer)",
        ),
        sa.Column(
            "read_at",
            sa.DateTime(timezone=True),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["recipient_id"], ["employees.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["actor_id"], ["employees.id"], ondelete="SET NULL"),
    )
    op.create_index(
        "ix_notifications_created_at", "notifications", ["created_at"], unique=False
    )
    op.create_index(
        "ix_notifications_recipient_unread",
        "notifications",
        ["recipient_id", "read_at"],
        unique=False,
    )
    op.create_index(
        "ix_notifications_target",
        "notifications",
        ["target_type", "target_id"],
        unique=False,
    )
    _ = op.create_table(
        "oauth_auth_codes",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "code",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "client_id",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "employee_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "redirect_uri",
            sa.String(length=2000),
            nullable=False,
        ),
        sa.Column(
            "code_challenge",
            sa.String(length=128),
            nullable=False,
        ),
        sa.Column(
            "code_challenge_method",
            sa.String(length=10),
            nullable=False,
        ),
        sa.Column(
            "scope",
            sa.String(length=500),
        ),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "used",
            sa.Boolean(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["employee_id"], ["employees.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["client_id"], ["oauth_clients.client_id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ix_oauth_auth_codes_code", "oauth_auth_codes", ["code"], unique=True
    )
    _ = op.create_table(
        "skill_contributions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "skill_id",
            postgresql.UUID(as_uuid=True),
        ),
        sa.Column(
            "contributor_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "base_version",
            sa.Integer(),
            comment="Version number this contribution was forked from. Null for new skills.",
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
        ),
        sa.Column(
            "revision_round",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "last_returned_note",
            sa.Text(),
        ),
        sa.Column(
            "scope_type",
            sa.String(length=20),
            nullable=False,
            comment="Scope type for NEW skills: global or department",
        ),
        sa.Column(
            "scope_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            comment="List of Department IDs if scope_type is department",
        ),
        sa.Column(
            "title",
            sa.String(length=200),
            nullable=False,
        ),
        sa.Column(
            "storage_path",
            sa.String(length=1000),
            comment="MinIO prefix for this contribution's files, e.g. 'skill-contributions/{id}/'",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["contributor_id"], ["employees.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["skill_id"], ["skills.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_skill_contributions_contributor_id",
        "skill_contributions",
        ["contributor_id"],
        unique=False,
    )
    op.create_index(
        "ix_skill_contributions_status", "skill_contributions", ["status"], unique=False
    )
    _ = op.create_table(
        "skill_departments",
        sa.Column(
            "skill_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "department_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["skill_id"], ["skills.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("skill_id", "department_id"),
        sa.ForeignKeyConstraint(
            ["department_id"], ["departments.id"], ondelete="CASCADE"
        ),
    )
    _ = op.create_table(
        "skill_versions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "skill_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "version_number",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "version_hash",
            sa.String(length=64),
        ),
        sa.Column(
            "storage_path",
            sa.String(length=1000),
        ),
        sa.Column(
            "changelog",
            sa.Text(),
        ),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["created_by"], ["employees.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["skill_id"], ["skills.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_skill_versions_skill_id", "skill_versions", ["skill_id"], unique=False
    )
    _ = op.create_table(
        "sources",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "title",
            sa.String(length=500),
        ),
        sa.Column(
            "full_text",
            sa.Text(),
        ),
        sa.Column(
            "source_type",
            sa.String(length=50),
        ),
        sa.Column(
            "scope_type",
            sa.String(length=20),
            nullable=False,
            comment="Scope type: global or project",
        ),
        sa.Column(
            "scope_id",
            postgresql.UUID(as_uuid=True),
            comment="Project/workspace ID when scope_type=project. Null for global.",
        ),
        sa.Column(
            "knowledge_type_id",
            postgresql.UUID(as_uuid=True),
        ),
        sa.Column(
            "contributed_by_employee_id",
            postgresql.UUID(as_uuid=True),
        ),
        sa.Column(
            "file_path",
            sa.String(length=1000),
        ),
        sa.Column(
            "url",
            sa.String(length=2000),
        ),
        sa.Column(
            "minio_key",
            sa.String(length=500),
        ),
        sa.Column(
            "file_name",
            sa.String(length=500),
        ),
        sa.Column(
            "file_size",
            sa.Integer(),
        ),
        sa.Column(
            "status",
            sa.String(length=50),
            nullable=False,
        ),
        sa.Column(
            "error_message",
            sa.Text(),
        ),
        sa.Column(
            "progress",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "progress_message",
            sa.String(length=500),
        ),
        sa.Column(
            "job_id",
            sa.String(length=200),
        ),
        sa.Column(
            "extracted_token_count",
            sa.Integer(),
            comment="tiktoken cl100k_base count of full_text. Used by upload gate.",
        ),
        sa.Column(
            "auto_recover_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment="Times sweep_stuck_processing_cron has flipped this source from 'processing' back to 'error'. Reset on successful plan_ready/ready. Gated by settings.max_auto_recover_attempts.",
        ),
        sa.Column(
            "pipeline_strategy",
            sa.String(length=20),
            comment="single_pass | standard | hierarchical — set by Phase 0 triage",
        ),
        sa.Column(
            "pipeline_phase",
            sa.String(length=30),
            comment="Current MRP phase: map | reduce | plan_review | refine | verify | commit",
        ),
        sa.Column(
            "preserve_verbatim",
            sa.Boolean(),
            nullable=False,
            server_default="false",
            comment="If True, skip the LLM wiki pipeline (MRP). The raw full_text is chunked + embedded as-is into source_chunk_embeddings_<dim> so it is searchable in the same semantic pool as wiki pages, but never rewritten. For high-fidelity docs (decrees, official gazettes).",
        ),
        sa.Column(
            "outline_json",
            postgresql.JSONB(astext_type=sa.Text()),
        ),
        sa.Column(
            "page_offsets",
            postgresql.JSONB(astext_type=sa.Text()),
        ),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["contributed_by_employee_id"], ["employees.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["knowledge_type_id"], ["knowledge_types.id"], ondelete="SET NULL"
        ),
    )
    _ = op.create_table(
        "wiki_branches",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "name",
            sa.String(length=100),
            nullable=False,
        ),
        sa.Column(
            "description",
            sa.Text(),
        ),
        sa.Column(
            "scope_type",
            sa.String(length=20),
            nullable=False,
        ),
        sa.Column(
            "scope_id",
            postgresql.UUID(as_uuid=True),
        ),
        sa.Column(
            "author_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
        ),
        sa.Column(
            "has_conflict",
            sa.Boolean(),
            nullable=False,
        ),
        sa.Column(
            "reviewer_id",
            postgresql.UUID(as_uuid=True),
        ),
        sa.Column(
            "reviewed_at",
            sa.DateTime(timezone=True),
        ),
        sa.Column(
            "reviewer_note",
            sa.Text(),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["author_id"], ["employees.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reviewer_id"], ["employees.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_wiki_branches_author_id", "wiki_branches", ["author_id"], unique=False
    )
    op.create_index(
        "ix_wiki_branches_status", "wiki_branches", ["status"], unique=False
    )
    _ = op.create_table(
        "wiki_links",
        sa.Column(
            "from_page_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "to_slug",
            sa.String(length=300),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["from_page_id"], ["wiki_pages.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("from_page_id", "to_slug"),
    )
    op.create_index(
        "ix_wiki_links_from_page_id", "wiki_links", ["from_page_id"], unique=False
    )
    op.create_index("ix_wiki_links_to_slug", "wiki_links", ["to_slug"], unique=False)
    _ = op.create_table(
        "wiki_page_embeddings_1024",
        sa.Column(
            "embedding",
            Vector(1024),
            nullable=False,
        ),
        sa.Column(
            "page_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "model_spec_id",
            sa.String(length=128),
            nullable=False,
        ),
        sa.Column(
            "content_hash",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "embedded_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("page_id", "model_spec_id"),
        sa.ForeignKeyConstraint(["page_id"], ["wiki_pages.id"], ondelete="CASCADE"),
    )
    _ = op.create_table(
        "wiki_page_embeddings_1536",
        sa.Column(
            "embedding",
            Vector(1536),
            nullable=False,
        ),
        sa.Column(
            "page_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "model_spec_id",
            sa.String(length=128),
            nullable=False,
        ),
        sa.Column(
            "content_hash",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "embedded_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["page_id"], ["wiki_pages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("page_id", "model_spec_id"),
    )
    _ = op.create_table(
        "wiki_page_embeddings_3072",
        sa.Column(
            "embedding",
            HALFVEC(3072),
            nullable=False,
        ),
        sa.Column(
            "page_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "model_spec_id",
            sa.String(length=128),
            nullable=False,
        ),
        sa.Column(
            "content_hash",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "embedded_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["page_id"], ["wiki_pages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("page_id", "model_spec_id"),
    )
    _ = op.create_table(
        "wiki_page_embeddings_768",
        sa.Column(
            "embedding",
            Vector(768),
            nullable=False,
        ),
        sa.Column(
            "page_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "model_spec_id",
            sa.String(length=128),
            nullable=False,
        ),
        sa.Column(
            "content_hash",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "embedded_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["page_id"], ["wiki_pages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("page_id", "model_spec_id"),
    )
    _ = op.create_table(
        "source_chunk_embeddings_1024",
        sa.Column(
            "embedding",
            Vector(1024),
            nullable=False,
        ),
        sa.Column(
            "source_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "chunk_index",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "model_spec_id",
            sa.String(length=128),
            nullable=False,
        ),
        sa.Column(
            "start_char",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "end_char",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "page_number",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "text",
            sa.Text(),
            nullable=False,
        ),
        sa.Column(
            "content_hash",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "embedded_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("source_id", "chunk_index", "model_spec_id"),
    )
    _ = op.create_table(
        "source_chunk_embeddings_1536",
        sa.Column(
            "embedding",
            Vector(1536),
            nullable=False,
        ),
        sa.Column(
            "source_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "chunk_index",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "model_spec_id",
            sa.String(length=128),
            nullable=False,
        ),
        sa.Column(
            "start_char",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "end_char",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "page_number",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "text",
            sa.Text(),
            nullable=False,
        ),
        sa.Column(
            "content_hash",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "embedded_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("source_id", "chunk_index", "model_spec_id"),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="CASCADE"),
    )
    _ = op.create_table(
        "source_chunk_embeddings_3072",
        sa.Column(
            "embedding",
            HALFVEC(3072),
            nullable=False,
        ),
        sa.Column(
            "source_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "chunk_index",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "model_spec_id",
            sa.String(length=128),
            nullable=False,
        ),
        sa.Column(
            "start_char",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "end_char",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "page_number",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "text",
            sa.Text(),
            nullable=False,
        ),
        sa.Column(
            "content_hash",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "embedded_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("source_id", "chunk_index", "model_spec_id"),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="CASCADE"),
    )
    _ = op.create_table(
        "source_chunk_embeddings_768",
        sa.Column(
            "embedding",
            Vector(768),
            nullable=False,
        ),
        sa.Column(
            "source_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "chunk_index",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "model_spec_id",
            sa.String(length=128),
            nullable=False,
        ),
        sa.Column(
            "start_char",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "end_char",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "page_number",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "text",
            sa.Text(),
            nullable=False,
        ),
        sa.Column(
            "content_hash",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "embedded_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("source_id", "chunk_index", "model_spec_id"),
    )
    _ = op.create_table(
        "source_chunk_extracts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "source_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "chunk_index",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "start_char",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "end_char",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "section_path",
            sa.Text(),
        ),
        sa.Column(
            "extract_json",
            postgresql.JSONB(astext_type=sa.Text()),
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
        ),
        sa.Column(
            "error_message",
            sa.Text(),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_id", "chunk_index", name="uq_sce_source_chunk"),
    )
    op.create_index(
        "ix_sce_source_status",
        "source_chunk_extracts",
        ["source_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_source_chunk_extracts_source_id",
        "source_chunk_extracts",
        ["source_id"],
        unique=False,
    )
    _ = op.create_table(
        "source_compilation_plans",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "source_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "plan_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=30),
            nullable=False,
        ),
        sa.Column(
            "reviewed_by",
            postgresql.UUID(as_uuid=True),
        ),
        sa.Column(
            "review_note",
            sa.Text(),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "reviewed_at",
            sa.DateTime(timezone=True),
        ),
        sa.UniqueConstraint("source_id"),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reviewed_by"], ["employees.id"], ondelete="SET NULL"),
    )
    op.create_index(
        "ix_scp_status", "source_compilation_plans", ["status"], unique=False
    )
    _ = op.create_table(
        "source_departments",
        sa.Column(
            "source_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "department_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("source_id", "department_id"),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["department_id"], ["departments.id"], ondelete="CASCADE"
        ),
    )
    _ = op.create_table(
        "source_images",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "source_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "minio_key",
            sa.Text(),
            nullable=False,
        ),
        sa.Column(
            "page_number",
            sa.Integer(),
        ),
        sa.Column(
            "image_index",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "caption",
            sa.Text(),
        ),
        sa.Column(
            "content_type",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "size_bytes",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_id", "image_index", name="uq_source_images_source_idx"
        ),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_source_images_source_id", "source_images", ["source_id"], unique=False
    )
    _ = op.create_table(
        "wiki_page_drafts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "page_id",
            postgresql.UUID(as_uuid=True),
        ),
        sa.Column(
            "draft_kind",
            sa.String(length=20),
            nullable=False,
        ),
        sa.Column(
            "suggested_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
        ),
        sa.Column(
            "author_id",
            postgresql.UUID(as_uuid=True),
        ),
        sa.Column(
            "content_md",
            sa.Text(),
            nullable=False,
        ),
        sa.Column(
            "note",
            sa.Text(),
        ),
        sa.Column(
            "base_version",
            sa.Integer(),
        ),
        sa.Column(
            "revision_round",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "last_returned_note",
            sa.Text(),
        ),
        sa.Column(
            "ai_check_status",
            sa.String(length=20),
            nullable=False,
        ),
        sa.Column(
            "ai_check_results",
            postgresql.JSONB(astext_type=sa.Text()),
        ),
        sa.Column(
            "ai_checked_at",
            sa.DateTime(timezone=True),
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
        ),
        sa.Column(
            "source",
            sa.String(length=40),
            nullable=False,
        ),
        sa.Column(
            "source_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
        ),
        sa.Column(
            "branch_id",
            postgresql.UUID(as_uuid=True),
        ),
        sa.Column(
            "reviewed_by_id",
            postgresql.UUID(as_uuid=True),
        ),
        sa.Column(
            "reviewed_at",
            sa.DateTime(timezone=True),
        ),
        sa.Column(
            "reviewer_note",
            sa.Text(),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["page_id"], ["wiki_pages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["branch_id"], ["wiki_branches.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by_id"], ["employees.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["author_id"], ["employees.id"], ondelete="SET NULL"),
    )
    op.create_index(
        "ix_wiki_drafts_author_id", "wiki_page_drafts", ["author_id"], unique=False
    )
    op.create_index(
        "ix_wiki_drafts_branch_id", "wiki_page_drafts", ["branch_id"], unique=False
    )
    op.create_index(
        "ix_wiki_drafts_page_id", "wiki_page_drafts", ["page_id"], unique=False
    )
    op.create_index(
        "ix_wiki_drafts_status", "wiki_page_drafts", ["status"], unique=False
    )
    _ = op.create_table(
        "wiki_draft_rounds",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "draft_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "round_no",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "content_md",
            sa.Text(),
            nullable=False,
        ),
        sa.Column(
            "author_note",
            sa.Text(),
        ),
        sa.Column(
            "reviewer_return_note",
            sa.Text(),
        ),
        sa.Column(
            "ai_check_results",
            postgresql.JSONB(astext_type=sa.Text()),
        ),
        sa.Column(
            "submitted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["draft_id"], ["wiki_page_drafts.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_wiki_draft_rounds_draft_id",
        "wiki_draft_rounds",
        ["draft_id", "round_no"],
        unique=False,
    )
    _ = op.create_table(
        "wiki_page_revisions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "page_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "version",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "content_md",
            sa.Text(),
            nullable=False,
        ),
        sa.Column(
            "change_type",
            sa.String(length=30),
            nullable=False,
        ),
        sa.Column(
            "draft_id",
            postgresql.UUID(as_uuid=True),
        ),
        sa.Column(
            "changed_by_id",
            postgresql.UUID(as_uuid=True),
        ),
        sa.Column(
            "change_note",
            sa.Text(),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["changed_by_id"], ["employees.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["draft_id"], ["wiki_page_drafts.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["page_id"], ["wiki_pages.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_wiki_revisions_page_id", "wiki_page_revisions", ["page_id"], unique=False
    )
    op.create_index(
        "uq_wiki_revisions_page_version",
        "wiki_page_revisions",
        ["page_id", "version"],
        unique=True,
    )


def downgrade() -> None:
    # Reverse the upgrade's topological construction one table at a time. An FK
    # can depend on a parent table's unique index, so parent indexes remain
    # until every child table and its constraints have been removed.
    op.drop_index("uq_wiki_revisions_page_version", table_name="wiki_page_revisions")
    op.drop_index("ix_wiki_revisions_page_id", table_name="wiki_page_revisions")
    op.drop_table("wiki_page_revisions")

    op.drop_index("ix_wiki_draft_rounds_draft_id", table_name="wiki_draft_rounds")
    op.drop_table("wiki_draft_rounds")

    op.drop_index("ix_wiki_drafts_status", table_name="wiki_page_drafts")
    op.drop_index("ix_wiki_drafts_page_id", table_name="wiki_page_drafts")
    op.drop_index("ix_wiki_drafts_branch_id", table_name="wiki_page_drafts")
    op.drop_index("ix_wiki_drafts_author_id", table_name="wiki_page_drafts")
    op.drop_table("wiki_page_drafts")

    op.drop_index("ix_source_images_source_id", table_name="source_images")
    op.drop_table("source_images")

    op.drop_table("source_departments")

    op.drop_index("ix_scp_status", table_name="source_compilation_plans")
    op.drop_table("source_compilation_plans")

    op.drop_index(
        "ix_source_chunk_extracts_source_id", table_name="source_chunk_extracts"
    )
    op.drop_index("ix_sce_source_status", table_name="source_chunk_extracts")
    op.drop_table("source_chunk_extracts")

    op.drop_table("source_chunk_embeddings_768")
    op.drop_table("source_chunk_embeddings_3072")
    op.drop_table("source_chunk_embeddings_1536")
    op.drop_table("source_chunk_embeddings_1024")

    op.drop_table("wiki_page_embeddings_768")
    op.drop_table("wiki_page_embeddings_3072")
    op.drop_table("wiki_page_embeddings_1536")
    op.drop_table("wiki_page_embeddings_1024")

    op.drop_index("ix_wiki_links_to_slug", table_name="wiki_links")
    op.drop_index("ix_wiki_links_from_page_id", table_name="wiki_links")
    op.drop_table("wiki_links")

    op.drop_index("ix_wiki_branches_status", table_name="wiki_branches")
    op.drop_index("ix_wiki_branches_author_id", table_name="wiki_branches")
    op.drop_table("wiki_branches")

    op.drop_table("sources")

    op.drop_index("ix_skill_versions_skill_id", table_name="skill_versions")
    op.drop_table("skill_versions")

    op.drop_table("skill_departments")

    op.drop_index("ix_skill_contributions_status", table_name="skill_contributions")
    op.drop_index(
        "ix_skill_contributions_contributor_id", table_name="skill_contributions"
    )
    op.drop_table("skill_contributions")

    op.drop_index("ix_oauth_auth_codes_code", table_name="oauth_auth_codes")
    op.drop_table("oauth_auth_codes")

    op.drop_index("ix_notifications_target", table_name="notifications")
    op.drop_index("ix_notifications_recipient_unread", table_name="notifications")
    op.drop_index("ix_notifications_created_at", table_name="notifications")
    op.drop_table("notifications")

    op.drop_index("ix_mcp_query_log_zero_result", table_name="mcp_query_log")
    op.drop_index("ix_mcp_query_log_tool_name", table_name="mcp_query_log")
    op.drop_index("ix_mcp_query_log_employee_id", table_name="mcp_query_log")
    op.drop_index("ix_mcp_query_log_created_at", table_name="mcp_query_log")
    op.drop_table("mcp_query_log")

    op.drop_index(
        "ix_employee_departments_department_id", table_name="employee_departments"
    )
    op.drop_table("employee_departments")

    op.drop_index("ix_wiki_pages_status", table_name="wiki_pages")
    op.drop_table("wiki_pages")

    op.drop_index("ix_stats_rollup_metric", table_name="stats_daily_rollup")
    op.drop_index("ix_stats_rollup_date", table_name="stats_daily_rollup")
    op.drop_table("stats_daily_rollup")

    op.drop_index("ix_skills_slug", table_name="skills")
    op.drop_table("skills")

    op.drop_index("ix_oauth_clients_client_id", table_name="oauth_clients")
    op.drop_table("oauth_clients")

    op.drop_table("notes")
    op.drop_table("knowledge_types")

    op.drop_index("ix_employees_mcp_token_hash", table_name="employees")
    op.drop_index("ix_employees_mcp_token", table_name="employees")
    op.drop_index("ix_employees_email", table_name="employees")
    op.drop_table("employees")

    op.drop_index("ix_embedding_jobs_status", table_name="embedding_jobs")
    op.drop_table("embedding_jobs")

    op.drop_table("departments")

    op.drop_index("ix_audit_log_timestamp", table_name="audit_log")
    op.drop_index("ix_audit_log_resource", table_name="audit_log")
    op.drop_index("ix_audit_log_principal", table_name="audit_log")
    op.drop_table("audit_log")

    op.drop_table("app_config")
    op.execute("DROP TYPE skill_status")
