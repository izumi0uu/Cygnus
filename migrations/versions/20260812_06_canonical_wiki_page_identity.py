"""Enforce canonical WikiPage identity (scope_type, scope_id, language, normalized_path).

Revision ID: 20260812_06
Revises: 20260812_05
Create Date: 2026-08-12 00:00:00

Adds ``language`` and ``normalized_path`` to ``wiki_pages``, backfills them
from existing rows, and fails with a diagnostic listing dirty duplicate
identity groups BEFORE creating the two partial unique indexes that enforce
the canonical identity. Two partial indexes are required because ``scope_id``
is nullable for the global scope: a plain UNIQUE constraint would treat NULL
scope_ids as distinct and let unlimited global rows share one identity.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260812_06"
down_revision: str | None = "20260812_05"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# SQL equivalent of wiki_service.normalize_page_path(): (slug or "").strip().lower().
# The backfill MUST produce exactly the identity the write path computes, or
# post-migration writes would drift from stored rows.
_BACKFILL_PATH_SQL = "lower(btrim(slug, E' \\t\\n\\r\\f\\v'))"

_DUPLICATE_LIMIT = 20


def _duplicate_identity_groups(
    connection: sa.engine.Connection,
    table: str = "wiki_pages",
) -> list[tuple[str, str, str, str, int]]:
    """Return (scope_type, scope_label, language, normalized_path, count) for
    every identity group holding more than one row, biggest groups first.

    ``scope_label`` renders NULL scope_id as ``<global>`` so the diagnostic
    reads clearly instead of showing ``None``. ``table`` is interpolated
    directly — it is only ever the internal ``wiki_pages`` constant or a
    test-owned throwaway table, never user input.
    """
    rows = connection.execute(
        sa.text(
            f"""
            SELECT scope_type,
                   COALESCE(scope_id::text, '<global>') AS scope_label,
                   language,
                   normalized_path,
                   count(*) AS n
            FROM {table}
            GROUP BY scope_type, scope_id, language, normalized_path
            HAVING count(*) > 1
            ORDER BY n DESC, scope_type, language, normalized_path
            LIMIT {_DUPLICATE_LIMIT}
            """
        )
    ).all()
    return [(r[0], r[1], r[2], r[3], int(r[4])) for r in rows]


def _duplicate_diagnostic(
    groups: Sequence[tuple[str, str, str, str, int]],
) -> str:
    """Human-readable failure message for dirty duplicate identities."""
    if not groups:
        return ""
    lines = [
        "WikiPage canonical identity migration blocked: existing rows violate "
        "the identity (scope_type, scope_id, language, normalized_path).",
        f"{len(groups)} duplicate group(s) found (showing up to {_DUPLICATE_LIMIT}):",
    ]
    for scope_type, scope_label, language, path, n in groups:
        lines.append(
            f"  - scope_type={scope_type!r} scope_id={scope_label!r} "
            f"language={language!r} normalized_path={path!r}: {n} rows"
        )
    lines.extend(
        [
            "",
            "The unique indexes are NOT created until every group has exactly one row.",
            "Remediation: for each group keep one surviving page, merge its "
            "content and",
            "revisions into that page, then delete the other rows (or move them to a",
            "distinct slug/scope/language) and re-run `alembic upgrade head`.",
        ]
    )
    return "\n".join(lines)


def upgrade() -> None:
    op.add_column(
        "wiki_pages", sa.Column("language", sa.String(length=10), nullable=True)
    )
    op.add_column(
        "wiki_pages",
        sa.Column("normalized_path", sa.String(length=300), nullable=True),
    )

    connection = op.get_bind()
    _ = connection.execute(
        sa.text("UPDATE wiki_pages SET language = 'en' WHERE language IS NULL")
    )
    _ = connection.execute(
        sa.text(
            f"UPDATE wiki_pages SET normalized_path = {_BACKFILL_PATH_SQL} "
            "WHERE normalized_path IS NULL"
        )
    )

    # Fail BEFORE creating the unique indexes so a dirty table is never
    # partially constrained; the raised diagnostic lists every duplicate
    # identity group and how to remediate.
    groups = _duplicate_identity_groups(connection)
    if groups:
        raise RuntimeError(_duplicate_diagnostic(groups))

    op.alter_column(
        "wiki_pages",
        "language",
        existing_type=sa.String(length=10),
        nullable=False,
        server_default=sa.text("'en'"),
    )
    op.alter_column(
        "wiki_pages",
        "normalized_path",
        existing_type=sa.String(length=300),
        nullable=False,
        server_default=sa.text("''"),
    )
    op.create_index(
        "uq_wiki_pages_canonical_identity_global",
        "wiki_pages",
        ["scope_type", "language", "normalized_path"],
        unique=True,
        postgresql_where=sa.text("scope_id IS NULL"),
    )
    op.create_index(
        "uq_wiki_pages_canonical_identity_scoped",
        "wiki_pages",
        ["scope_type", "scope_id", "language", "normalized_path"],
        unique=True,
        postgresql_where=sa.text("scope_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_wiki_pages_canonical_identity_scoped", table_name="wiki_pages")
    op.drop_index("uq_wiki_pages_canonical_identity_global", table_name="wiki_pages")
    op.drop_column("wiki_pages", "normalized_path")
    op.drop_column("wiki_pages", "language")
