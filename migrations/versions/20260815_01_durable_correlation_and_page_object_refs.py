"""Correlate durable commands and canonicalize page-backed governed object refs.

Revision ID: 20260815_01
Revises: 20260812_08
Create Date: 2026-08-15 00:00:00

Historical command rows remain nullable for request correlation. New runtime paths
supply a UUID correlation ID and optional W3C traceparent before writing one of the
indexed externally-queryable durable command/outbox records.

Page-backed governed references move from the ambiguous legacy ``ko-<slug>`` form
to ``ko-page-<wiki_page_id>``. The data migration changes only rows with a
persisted page identity, recomputes audience binding keys, and updates dependent
signal binding references. Immutable pending, in-flight, or synced delivery
payloads are never reinterpreted under a new identity: an upgrade/downgrade stops
before any mutation if their object ref would differ. Operators must explicitly
rebind/republish after resolving that boundary; no alias or fabricated
acknowledgement is introduced.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import hashlib
import json
from typing import Any

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260815_01"
down_revision: str | None = "20260812_08"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TRACEPARENT_LENGTH = 55
_CORRELATION_TABLES = (
    "governance_feedback_signals",
    "governance_tool_command_receipts",
    "governance_feedback_routes",
    "governance_review_assignment_events",
    "governance_ticket_draft_promotions",
    "governance_ledger_events",
    "governance_publications",
    "source_dispatch_executions",
)


# These names are deliberately explicit rather than derived: Alembic downgrade
# must remove exactly the index created by upgrade.
_CORRELATION_INDEXES = (
    ("governance_feedback_signals", "ix_governance_feedback_signals_correlation_id"),
    (
        "governance_tool_command_receipts",
        "ix_governance_tool_command_receipts_correlation_id",
    ),
    ("governance_feedback_routes", "ix_governance_feedback_routes_correlation_id"),
    (
        "governance_review_assignment_events",
        "ix_governance_review_assignment_events_correlation_id",
    ),
    (
        "governance_ticket_draft_promotions",
        "ix_governance_ticket_draft_promotions_correlation_id",
    ),
    ("governance_ledger_events", "ix_governance_ledger_events_correlation_id"),
    ("governance_publications", "ix_governance_publications_correlation_id"),
    (
        "source_dispatch_executions",
        "ix_source_dispatch_execution_correlation_id",
    ),
)


def _canonical_ref(page_id: object) -> str:
    return f"ko-page-{page_id}"


def _legacy_ref(slug: object) -> str:
    return f"ko-{slug}"


def _canonical_dimension(raw_values: object, *, label: str) -> tuple[str, ...]:
    if not isinstance(raw_values, list):
        raise RuntimeError(
            "canonical object-ref migration found an invalid audience dimension "
            f"for {label}: expected JSON list"
        )
    normalized: set[str] = set()
    for raw_value in raw_values:
        if not isinstance(raw_value, str):
            raise RuntimeError(
                "canonical object-ref migration found a non-string audience "
                f"dimension in {label}"
            )
        value = raw_value.strip()
        if not value:
            raise RuntimeError(
                "canonical object-ref migration found a blank audience dimension "
                f"in {label}"
            )
        normalized.add(value)
    return tuple(sorted(normalized))


def _binding_key(row: Mapping[str, Any], object_ref: str) -> str:
    dimensions = {
        "brands": _canonical_dimension(row["brands"], label="brands"),
        "product_lines": _canonical_dimension(
            row["product_lines"], label="product_lines"
        ),
        "plans": _canonical_dimension(row["plans"], label="plans"),
        "regions": _canonical_dimension(row["regions"], label="regions"),
        "languages": _canonical_dimension(row["languages"], label="languages"),
        "product_versions": _canonical_dimension(
            row["product_versions"], label="product_versions"
        ),
    }
    visibility = row["visibility"]
    variant_ref = row["variant_ref"]
    channel = row["channel"]
    if not all(
        isinstance(value, str) and value.strip()
        for value in (visibility, variant_ref, channel)
    ):
        raise RuntimeError(
            "canonical object-ref migration found a blank audience binding identity"
        )
    audience_filter = {
        "visibility": visibility.strip(),
        **{key: list(value) for key, value in dimensions.items()},
        "is_global": not any(dimensions.values()),
    }
    payload = {
        "page_id": str(row["page_id"]),
        "object_ref": object_ref,
        "variant_ref": variant_ref.strip(),
        "channel": channel.strip(),
        "audience_filter": audience_filter,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _active_delivery_mismatches(
    connection: sa.Connection,
    *,
    target: str,
) -> list[Mapping[str, Any]]:
    """Return nonterminal/synced deliveries whose immutable payload uses another ref.

    ``target`` is ``canonical`` during upgrade and ``legacy`` during downgrade.
    A pending/in-flight record could be delivered after the migration, while a
    synced row is an acknowledged downstream identity. Neither can be rewritten
    or silently reinterpreted under the other ref.
    """
    expected = (
        "'ko-page-' || page.id::text" if target == "canonical" else "'ko-' || page.slug"
    )
    rows = connection.execute(
        sa.text(
            "SELECT d.id AS delivery_id, d.status, publication.id AS publication_id, "
            "publication.object_ref AS publication_object_ref, "
            f"{expected} AS expected_object_ref, "
            "d.canonical_payload ->> 'object_ref' AS payload_object_ref "
            "FROM governance_propagation_deliveries AS d "
            "JOIN governance_publications AS publication "
            "ON publication.id = d.publication_id "
            "JOIN wiki_pages AS page ON page.id = publication.page_id "
            "WHERE d.status IN ('pending', 'in_flight', 'synced') "
            "AND (d.canonical_payload ->> 'object_ref') IS DISTINCT FROM "
            f"{expected} "
            "ORDER BY d.id LIMIT 20"
        )
    ).mappings()
    return list(rows)


def _guard_active_delivery_payloads(
    connection: sa.Connection,
    *,
    target: str,
) -> None:
    mismatches = _active_delivery_mismatches(connection, target=target)
    if not mismatches:
        return
    details = "; ".join(
        "delivery_id={delivery_id} publication_id={publication_id} "
        "status={status} payload={payload_object_ref!r} expected={expected_object_ref!r}".format(
            **row
        )
        for row in mismatches
    )
    raise RuntimeError(
        "canonical object-ref migration is blocked by active immutable delivery "
        f"payloads; drain or terminally resolve them before retrying: {details}"
    )


def _guard_ambiguous_feedback_refs(connection: sa.Connection) -> None:
    """Do not preserve a slug-based feedback alias without a page identity."""
    rows = connection.execute(
        sa.text(
            "SELECT id, object_id FROM governance_feedback_signals "
            "WHERE object_id LIKE 'ko-%' "
            "AND object_id NOT LIKE 'ko-page-%' "
            "AND page_id IS NULL ORDER BY id LIMIT 20"
        )
    ).mappings()
    ambiguous = list(rows)
    if not ambiguous:
        return
    details = "; ".join(
        f"feedback_id={row['id']} object_id={row['object_id']!r}" for row in ambiguous
    )
    raise RuntimeError(
        "canonical object-ref migration cannot retain page-ambiguous feedback "
        f"references; bind each row to a page or make it unavailable first: {details}"
    )


def _binding_key_updates(
    connection: sa.Connection,
    *,
    canonical: bool,
) -> list[tuple[str, str, str, str]]:
    """Return (id, old_key, new_key, object_ref) for every audience binding."""
    rows = connection.execute(
        sa.text(
            "SELECT id, page_id, variant_ref, channel, visibility, brands, "
            "product_lines, plans, regions, languages, product_versions, binding_key "
            "FROM governance_audience_bindings ORDER BY id"
        )
    ).mappings()
    updates: list[tuple[str, str, str, str]] = []
    seen_keys: set[str] = set()
    for row in rows:
        object_ref = (
            _canonical_ref(row["page_id"])
            if canonical
            else _legacy_ref(
                connection.execute(
                    sa.text("SELECT slug FROM wiki_pages WHERE id = :page_id"),
                    {"page_id": row["page_id"]},
                ).scalar_one()
            )
        )
        old_key = row["binding_key"]
        if not isinstance(old_key, str):
            raise RuntimeError(
                "canonical object-ref migration found a non-string binding key"
            )
        new_key = _binding_key(row, object_ref)
        if new_key in seen_keys:
            raise RuntimeError(
                "canonical object-ref migration would create duplicate audience binding keys"
            )
        seen_keys.add(new_key)
        updates.append((str(row["id"]), old_key, new_key, object_ref))
    return updates


def _rewrite_binding_keys(connection: sa.Connection, *, canonical: bool) -> None:
    updates = _binding_key_updates(connection, canonical=canonical)
    if not updates:
        return

    # A final key can theoretically equal another row's old key. Stage both
    # unique columns and dependent signal references so Postgres never sees a
    # transient UNIQUE collision or rewrites a just-migrated signal twice.
    for binding_id, old_key, _new_key, _object_ref in updates:
        connection.execute(
            sa.text(
                "UPDATE governance_audience_bindings SET binding_key = :temporary "
                "WHERE id = :id"
            ),
            {"id": binding_id, "temporary": f"migrating:{binding_id}"},
        )
        connection.execute(
            sa.text(
                "UPDATE governance_signals SET audience_binding_ref = :temporary "
                "WHERE audience_binding_ref = :old_key"
            ),
            {"temporary": f"migrating-binding-ref:{binding_id}", "old_key": old_key},
        )
    for binding_id, _old_key, new_key, object_ref in updates:
        connection.execute(
            sa.text(
                "UPDATE governance_audience_bindings "
                "SET object_ref = :object_ref, binding_key = :binding_key "
                "WHERE id = :id"
            ),
            {"id": binding_id, "object_ref": object_ref, "binding_key": new_key},
        )
        connection.execute(
            sa.text(
                "UPDATE governance_signals SET audience_binding_ref = :new_key "
                "WHERE audience_binding_ref = :temporary"
            ),
            {"new_key": new_key, "temporary": f"migrating-binding-ref:{binding_id}"},
        )


def _rewrite_page_backed_object_refs(
    connection: sa.Connection, *, canonical: bool
) -> None:
    prefix = "'ko-page-' || p.id::text" if canonical else "'ko-' || p.slug"
    _rewrite_binding_keys(connection, canonical=canonical)

    connection.execute(
        sa.text(
            "UPDATE governance_signals AS g SET object_ref = "
            f"{prefix} FROM wiki_pages AS p WHERE g.page_id = p.id"
        )
    )
    connection.execute(
        sa.text(
            "UPDATE governance_feedback_signals AS f SET object_id = "
            f"{prefix} FROM wiki_pages AS p WHERE f.page_id = p.id"
        )
    )
    connection.execute(
        sa.text(
            "UPDATE governance_publications AS publication SET "
            f"object_ref = {prefix}, "
            "candidate = jsonb_set("
            "publication.candidate, '{object_id}', "
            f"to_jsonb(({prefix})::text), true), "
            "preview = jsonb_set("
            "publication.preview, '{object_id}', "
            f"to_jsonb(({prefix})::text), true) "
            "FROM wiki_pages AS p WHERE publication.page_id = p.id"
        )
    )


def _add_correlation_columns() -> None:
    for table in _CORRELATION_TABLES:
        op.add_column(
            table,
            sa.Column("correlation_id", postgresql.UUID(as_uuid=True), nullable=True),
        )
        op.add_column(
            table,
            sa.Column(
                "traceparent", sa.String(length=_TRACEPARENT_LENGTH), nullable=True
            ),
        )
    for table, index in _CORRELATION_INDEXES:
        op.create_index(index, table, ["correlation_id"], unique=False)


def _drop_correlation_columns() -> None:
    for table, index in reversed(_CORRELATION_INDEXES):
        op.drop_index(index, table_name=table)
    for table in reversed(_CORRELATION_TABLES):
        op.drop_column(table, "traceparent")
        op.drop_column(table, "correlation_id")


def upgrade() -> None:
    connection = op.get_bind()
    _guard_active_delivery_payloads(connection, target="canonical")
    _guard_ambiguous_feedback_refs(connection)
    _rewrite_page_backed_object_refs(connection, canonical=True)
    _add_correlation_columns()


def downgrade() -> None:
    connection = op.get_bind()
    _guard_active_delivery_payloads(connection, target="legacy")
    _rewrite_page_backed_object_refs(connection, canonical=False)
    _drop_correlation_columns()
