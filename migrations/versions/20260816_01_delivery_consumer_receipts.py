"""Add durable signed delivery-consumer receipts.

Revision ID: 20260816_01
Revises: 20260815_02
Create Date: 2026-08-16 00:00:00

The bounded internal delivery consumer retains only immutable receipt metadata;
the delivered support payload is intentionally never persisted here.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260816_01"
down_revision: str | None = "20260815_02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    _ = op.create_table(
        "delivery_consumer_receipts",
        sa.Column("delivery_id", sa.String(length=220), nullable=False),
        sa.Column("body_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "publication_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("surface_id", sa.String(length=120), nullable=False),
        sa.Column("object_version", sa.Integer(), nullable=False),
        sa.Column("receipt_ref", sa.String(length=220), nullable=False),
        sa.Column(
            "accepted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "delivery_id = btrim(delivery_id) "
            "AND char_length(delivery_id) BETWEEN 1 AND 220",
            name="ck_delivery_consumer_receipts_delivery_id_shape",
        ),
        sa.CheckConstraint(
            "delivery_id = 'delivery:' || publication_id::text || ':' || surface_id",
            name="ck_delivery_consumer_receipts_identity_binding",
        ),
        sa.CheckConstraint(
            "char_length(body_sha256) = 64",
            name="ck_delivery_consumer_receipts_body_sha256_shape",
        ),
        sa.CheckConstraint(
            "surface_id = btrim(surface_id) "
            "AND char_length(surface_id) BETWEEN 1 AND 120",
            name="ck_delivery_consumer_receipts_surface_id_shape",
        ),
        sa.CheckConstraint(
            "object_version >= 1",
            name="ck_delivery_consumer_receipts_object_version",
        ),
        sa.CheckConstraint(
            "receipt_ref = btrim(receipt_ref) "
            "AND char_length(receipt_ref) BETWEEN 1 AND 220",
            name="ck_delivery_consumer_receipts_receipt_ref_shape",
        ),
        sa.PrimaryKeyConstraint("delivery_id"),
        sa.UniqueConstraint(
            "receipt_ref",
            name="uq_delivery_consumer_receipts_receipt_ref",
        ),
    )


def downgrade() -> None:
    op.drop_table("delivery_consumer_receipts")
