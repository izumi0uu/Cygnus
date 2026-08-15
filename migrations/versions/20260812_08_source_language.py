"""Persist an explicit normalized language tag on every Source.

Revision ID: 20260812_08
Revises: 20260812_07
Create Date: 2026-08-12 00:00:00

Adds ``sources.language`` and backfills every existing row to ``en`` (the
product default locale). The tag is explicit user input, validated by
``cygnus.substrate.source_language.normalize_source_language`` — it is never
auto-detected. The compiler writes canonical WikiPage rows under this exact
tag, so pages from a ``zh`` source land under the ``zh`` identity
(scope_type, scope_id, language, normalized_path) enforced by
``20260812_06_canonical_wiki_page_identity`` and stay separate from ``en``
pages under the same scope/path.

Linear and fully reversible: ``upgrade`` adds + backfills + not-nulls the
column; ``downgrade`` drops it.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260812_08"
down_revision: str | None = "20260812_07"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Mirrors wiki_service.DEFAULT_PAGE_LANGUAGE / substrate.source_language.
_BACKFILL_LANGUAGE = "en"


def upgrade() -> None:
    op.add_column(
        "sources",
        sa.Column("language", sa.String(length=10), nullable=True),
    )
    # Existing rows are legacy en sources: backfill the explicit tag before
    # enforcing NOT NULL so no row is ever language-less.
    connection = op.get_bind()
    _ = connection.execute(
        sa.text(
            "UPDATE sources SET language = :lang WHERE language IS NULL"
        ).bindparams(lang=_BACKFILL_LANGUAGE)
    )
    op.alter_column(
        "sources",
        "language",
        existing_type=sa.String(length=10),
        nullable=False,
        server_default=sa.text("'en'"),
    )


def downgrade() -> None:
    op.drop_column("sources", "language")
