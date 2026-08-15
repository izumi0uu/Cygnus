"""Add monotonic employee portal session versions.

Revision ID: 20260815_02
Revises: 20260815_01
Create Date: 2026-08-15 00:00:00

Every existing employee starts at version zero. Portal JWT revocations advance this
value with an atomic SQL increment; MCP token state is intentionally unaffected.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260815_02"
down_revision: str | None = "20260815_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "employees",
        sa.Column(
            "session_version",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("0"),
            comment="Monotonic portal JWT revocation version; independent of MCP tokens",
        ),
    )
    op.create_check_constraint(
        "ck_employees_session_version_nonnegative",
        "employees",
        "session_version >= 0",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_employees_session_version_nonnegative",
        "employees",
        type_="check",
    )
    op.drop_column("employees", "session_version")
