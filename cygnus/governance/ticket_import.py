"""Resolved-ticket export pilot for the governed Ticket-to-Knowledge loop.

Contract ``resolved-ticket-export/v1`` accepts UTF-8 CSV or JSONL. Required fields:
``ticket_id``, ``resolved_at``, ``issue_signature``, ``title``,
``sanitized_summary``, and ``sanitized_resolution``. Optional fields:
``product_line``, ``feature``, ``plan``, ``region``, ``language``,
``product_version``, and ``object_type``.

The caller owns de-identification. The importer performs no network access, uses no
LLM, and never approves or publishes knowledge. It validates the whole payload before
writing, then materializes qualifying candidates through the existing durable
GovernanceSignal owner in the caller's transaction.
"""

from __future__ import annotations
from typing import cast, final
from collections.abc import Iterable, Mapping
import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import hashlib
import io
import json
import re
from urllib.parse import quote
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from cygnus.domain.audience import AudienceFilter, Visibility
from cygnus.domain.objects import KnowledgeObjectType
from cygnus.evidence.records import EvidenceSourceType, FreshnessState
from cygnus.governance.signals import (
    GovernanceEvidenceRef,
    GovernanceSignalInput,
    create_governance_signal,
    governance_signal_to_dict,
)
from cygnus.review.intake import PressureSignalType
from cygnus.runtime.database.models import GovernanceSignal


TICKET_IMPORT_CONTRACT_VERSION = "resolved-ticket-export/v1"
MAX_IMPORT_BYTES = 5_000_000
MAX_IMPORT_RECORDS = 5_000
MAX_IMPORT_DIAGNOSTICS = 20
MAX_CLUSTER_EVIDENCE_REFS = 100

_REQUIRED_FIELDS = (
    "ticket_id",
    "resolved_at",
    "issue_signature",
    "title",
    "sanitized_summary",
    "sanitized_resolution",
)
_OPTIONAL_FIELDS = (
    "product_line",
    "feature",
    "plan",
    "region",
    "language",
    "product_version",
    "object_type",
)
_ALLOWED_FIELDS = frozenset((*_REQUIRED_FIELDS, *_OPTIONAL_FIELDS))
_ISSUE_SIGNATURE_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,159}$")


class TicketExportFormat(str, Enum):
    CSV = "csv"
    JSONL = "jsonl"


@dataclass(frozen=True, slots=True, kw_only=True)
class TicketImportDiagnostic:
    line: int | None
    field: str | None
    code: str
    message: str

    def to_dict(self) -> dict[str, object]:
        return {
            "line": self.line,
            "field": self.field,
            "code": self.code,
            "message": self.message,
        }


@final
class TicketImportValidationError(ValueError):
    """Bounded diagnostics for a rejected export; no writes have occurred."""

    def __init__(
        self,
        diagnostics: Iterable[TicketImportDiagnostic],
        *,
        total_errors: int | None = None,
    ) -> None:
        bounded = tuple(diagnostics)[:MAX_IMPORT_DIAGNOSTICS]
        self.diagnostics = bounded
        self.total_errors = max(total_errors or len(bounded), len(bounded))
        super().__init__(
            f"resolved-ticket export failed validation with {self.total_errors} error(s)"
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "contract_version": TICKET_IMPORT_CONTRACT_VERSION,
            "error": "invalid_resolved_ticket_export",
            "total_errors": self.total_errors,
            "diagnostics": [item.to_dict() for item in self.diagnostics],
            "diagnostics_truncated": self.total_errors > len(self.diagnostics),
        }


@final
class _DiagnosticCollector:
    def __init__(self) -> None:
        self.items: list[TicketImportDiagnostic] = []
        self.total: int = 0

    def add(
        self,
        *,
        line: int | None,
        field: str | None,
        code: str,
        message: str,
    ) -> None:
        self.total += 1
        if len(self.items) < MAX_IMPORT_DIAGNOSTICS:
            self.items.append(
                TicketImportDiagnostic(
                    line=line,
                    field=field,
                    code=code,
                    message=message,
                )
            )

    def raise_if_any(self) -> None:
        if self.total:
            raise TicketImportValidationError(self.items, total_errors=self.total)


@dataclass(frozen=True, slots=True, kw_only=True)
class ResolvedTicketRecord:
    ticket_id: str
    resolved_at: datetime
    issue_signature: str
    title: str
    sanitized_summary: str
    sanitized_resolution: str
    product_line: str | None = None
    feature: str | None = None
    plan: str | None = None
    region: str | None = None
    language: str | None = None
    product_version: str | None = None
    object_type: KnowledgeObjectType = KnowledgeObjectType.TROUBLESHOOTING_FLOW

    @property
    def cluster_key(self) -> tuple[str, ...]:
        return (
            self.issue_signature,
            self.product_line or "",
            self.feature or "",
            self.plan or "",
            self.region or "",
            self.language or "",
            self.product_version or "",
            self.object_type.value,
        )

    def canonical_dict(self) -> dict[str, str | None]:
        return {
            "ticket_id": self.ticket_id,
            "resolved_at": self.resolved_at.astimezone(timezone.utc).isoformat(),
            "issue_signature": self.issue_signature,
            "title": self.title,
            "sanitized_summary": self.sanitized_summary,
            "sanitized_resolution": self.sanitized_resolution,
            "product_line": self.product_line,
            "feature": self.feature,
            "plan": self.plan,
            "region": self.region,
            "language": self.language,
            "product_version": self.product_version,
            "object_type": self.object_type.value,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class TicketClusterCandidate:
    cluster_ref: str
    signal_ref: str
    source_ref: str
    issue_signature: str
    title: str
    object_type: KnowledgeObjectType
    audience_filter: AudienceFilter
    feature: str | None
    member_count: int
    minimum_cluster_size: int
    window_start: datetime
    window_end: datetime
    evidence_refs: tuple[GovernanceEvidenceRef, ...]
    import_digest: str
    representative_excerpt: str

    @property
    def qualifies(self) -> bool:
        return self.member_count >= self.minimum_cluster_size

    def to_signal_input(self) -> GovernanceSignalInput:
        if not self.qualifies:
            raise ValueError(
                "non-qualifying ticket clusters cannot create governance signals"
            )
        feature_scope = f"; feature={self.feature}" if self.feature else ""
        return GovernanceSignalInput(
            signal_ref=self.signal_ref,
            signal_type=PressureSignalType.TICKET_CLUSTER,
            object_ref=self.cluster_ref,
            title=self.title,
            object_type=self.object_type,
            audience_filter=self.audience_filter,
            affected_surfaces=("copilot", "review_queue"),
            trigger_signals=(
                "ticket_pressure",
                "ticket_cluster",
                f"ticket_import:{self.import_digest}",
            ),
            evidence_source_type=EvidenceSourceType.RESOLVED_TICKET,
            freshness=FreshnessState.UNKNOWN,
            summary=(
                f"{self.member_count} resolved tickets share issue_signature="
                f"{self.issue_signature}{feature_scope} in immutable export "
                f"{self.source_ref}."
            ),
            reason=(
                f"member_count={self.member_count} met minimum_cluster_size="
                f"{self.minimum_cluster_size}; import_digest={self.import_digest}."
            ),
            evidence_excerpt=self.representative_excerpt,
            observed_at=self.window_end,
            evidence_refs=self.evidence_refs,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "cluster_ref": self.cluster_ref,
            "signal_ref": self.signal_ref if self.qualifies else None,
            "source_ref": self.source_ref,
            "issue_signature": self.issue_signature,
            "title": self.title,
            "object_type": self.object_type.value,
            "audience_filter": self.audience_filter.to_dict(),
            "feature": self.feature,
            "member_count": self.member_count,
            "minimum_cluster_size": self.minimum_cluster_size,
            "qualifies": self.qualifies,
            "window_start": self.window_start.isoformat(),
            "window_end": self.window_end.isoformat(),
            "evidence_ref_count": len(self.evidence_refs),
            "evidence_refs": [item.to_dict() for item in self.evidence_refs],
            "representative_excerpt": self.representative_excerpt,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class TicketImportPlan:
    source_ref: str
    export_format: TicketExportFormat
    import_digest: str
    minimum_cluster_size: int
    record_count: int
    candidates: tuple[TicketClusterCandidate, ...]

    @property
    def qualifying_candidates(self) -> tuple[TicketClusterCandidate, ...]:
        return tuple(item for item in self.candidates if item.qualifies)

    def to_dict(self) -> dict[str, object]:
        return {
            "contract_version": TICKET_IMPORT_CONTRACT_VERSION,
            "source_ref": self.source_ref,
            "export_format": self.export_format.value,
            "import_digest": self.import_digest,
            "minimum_cluster_size": self.minimum_cluster_size,
            "record_count": self.record_count,
            "candidate_count": len(self.candidates),
            "qualifying_candidate_count": len(self.qualifying_candidates),
            "candidates": [item.to_dict() for item in self.candidates],
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class TicketImportResult:
    plan: TicketImportPlan
    governance_signals: tuple[GovernanceSignal, ...]

    def to_dict(self) -> dict[str, object]:
        payload = self.plan.to_dict()
        payload.update(
            {
                "persisted_signal_count": len(self.governance_signals),
                "persisted_signal_refs": [
                    signal.signal_ref for signal in self.governance_signals
                ],
                "governance_signals": [
                    governance_signal_to_dict(signal)
                    for signal in self.governance_signals
                ],
                "publication_state": "not_published",
                "next_step": "review_qualifying_candidates",
            }
        )
        return payload


def parse_resolved_ticket_export(
    content: bytes,
    *,
    export_format: TicketExportFormat,
) -> tuple[ResolvedTicketRecord, ...]:
    diagnostics = _DiagnosticCollector()
    if len(content) > MAX_IMPORT_BYTES:
        diagnostics.add(
            line=None,
            field=None,
            code="payload_too_large",
            message=f"export must not exceed {MAX_IMPORT_BYTES} bytes",
        )
        diagnostics.raise_if_any()

    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        diagnostics.add(
            line=None,
            field=None,
            code="invalid_encoding",
            message=f"export must be UTF-8: byte offset {exc.start}",
        )
        diagnostics.raise_if_any()
        raise AssertionError("unreachable")

    rows = (
        _csv_rows(text, diagnostics)
        if export_format is TicketExportFormat.CSV
        else _jsonl_rows(text, diagnostics)
    )
    records: list[ResolvedTicketRecord] = []
    seen_ticket_ids: dict[str, int] = {}
    for record_index, (line, payload) in enumerate(rows, start=1):
        if record_index > MAX_IMPORT_RECORDS:
            diagnostics.add(
                line=line,
                field=None,
                code="record_limit_exceeded",
                message=f"export must not contain more than {MAX_IMPORT_RECORDS} records",
            )
            break
        record = _record_from_payload(payload, line=line, diagnostics=diagnostics)
        if record is None:
            continue
        first_line = seen_ticket_ids.get(record.ticket_id)
        if first_line is not None:
            diagnostics.add(
                line=line,
                field="ticket_id",
                code="duplicate_ticket_id",
                message=f"ticket_id duplicates line {first_line}",
            )
            continue
        seen_ticket_ids[record.ticket_id] = line
        records.append(record)

    if not records and diagnostics.total == 0:
        diagnostics.add(
            line=None,
            field=None,
            code="empty_export",
            message="export must contain at least one resolved-ticket record",
        )
    diagnostics.raise_if_any()
    return tuple(records)


def build_ticket_import_plan(
    records: Iterable[ResolvedTicketRecord],
    *,
    source_ref: str,
    export_format: TicketExportFormat,
    minimum_cluster_size: int = 3,
) -> TicketImportPlan:
    normalized_source_ref = _validate_source_ref(source_ref)
    if isinstance(minimum_cluster_size, bool):
        raise ValueError("minimum_cluster_size must be an integer")
    if not 2 <= minimum_cluster_size <= 100:
        raise ValueError("minimum_cluster_size must be between 2 and 100")

    record_tuple = tuple(records)
    if not record_tuple:
        raise ValueError("records must not be empty")
    canonical_records = sorted(
        (item.canonical_dict() for item in record_tuple),
        key=lambda item: (str(item["ticket_id"]), str(item["resolved_at"])),
    )
    import_digest = hashlib.sha256(
        json.dumps(
            canonical_records,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()[:24]
    source_digest = hashlib.sha256(normalized_source_ref.encode("utf-8")).hexdigest()[
        :12
    ]

    grouped: dict[tuple[str, ...], list[ResolvedTicketRecord]] = {}
    for record in record_tuple:
        grouped.setdefault(record.cluster_key, []).append(record)

    candidates = tuple(
        _candidate_from_records(
            grouped[key],
            source_ref=normalized_source_ref,
            source_digest=source_digest,
            import_digest=import_digest,
            minimum_cluster_size=minimum_cluster_size,
        )
        for key in sorted(grouped)
    )
    return TicketImportPlan(
        source_ref=normalized_source_ref,
        export_format=export_format,
        import_digest=import_digest,
        minimum_cluster_size=minimum_cluster_size,
        record_count=len(record_tuple),
        candidates=candidates,
    )


async def import_resolved_ticket_export(
    session: AsyncSession,
    content: bytes,
    *,
    export_format: TicketExportFormat,
    source_ref: str,
    minimum_cluster_size: int,
    created_by_id: uuid.UUID,
) -> TicketImportResult:
    """Validate first, then persist every qualifying cluster in one transaction."""

    records = parse_resolved_ticket_export(content, export_format=export_format)
    plan = build_ticket_import_plan(
        records,
        source_ref=source_ref,
        export_format=export_format,
        minimum_cluster_size=minimum_cluster_size,
    )
    persisted: list[GovernanceSignal] = []
    for candidate in plan.qualifying_candidates:
        persisted.append(
            await create_governance_signal(
                session,
                candidate.to_signal_input(),
                created_by_id=created_by_id,
            )
        )
    return TicketImportResult(plan=plan, governance_signals=tuple(persisted))


def _csv_rows(
    text: str,
    diagnostics: _DiagnosticCollector,
) -> tuple[tuple[int, Mapping[str, object]], ...]:
    try:
        reader = csv.DictReader(io.StringIO(text, newline=""))
        fieldnames = reader.fieldnames
    except csv.Error as exc:
        diagnostics.add(
            line=1,
            field=None,
            code="invalid_csv",
            message=str(exc),
        )
        return ()
    if fieldnames is None:
        diagnostics.add(
            line=1,
            field=None,
            code="missing_header",
            message="CSV must include a header row",
        )
        return ()
    _validate_fields(fieldnames, line=1, diagnostics=diagnostics)
    if diagnostics.total:
        return ()

    rows: list[tuple[int, Mapping[str, object]]] = []
    try:
        for row in reader:
            if None in row:
                diagnostics.add(
                    line=reader.line_num,
                    field=None,
                    code="extra_csv_values",
                    message="row contains more values than the header defines",
                )
                continue
            rows.append((reader.line_num, dict(row)))
    except csv.Error as exc:
        diagnostics.add(
            line=reader.line_num,
            field=None,
            code="invalid_csv",
            message=str(exc),
        )
    return tuple(rows)


def _jsonl_rows(
    text: str,
    diagnostics: _DiagnosticCollector,
) -> tuple[tuple[int, Mapping[str, object]], ...]:
    rows: list[tuple[int, Mapping[str, object]]] = []
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        if not raw_line.strip():
            continue
        try:
            payload: object = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            diagnostics.add(
                line=line_number,
                field=None,
                code="invalid_json",
                message=f"column {exc.colno}: {exc.msg}",
            )
            continue
        if not isinstance(payload, dict):
            diagnostics.add(
                line=line_number,
                field=None,
                code="invalid_record",
                message="each JSONL line must be an object",
            )
            continue
        rows.append((line_number, cast(dict[str, object], payload)))
    return tuple(rows)


def _validate_fields(
    fields: Iterable[str],
    *,
    line: int,
    diagnostics: _DiagnosticCollector,
) -> None:
    field_tuple = tuple(fields)
    if len(set(field_tuple)) != len(field_tuple):
        diagnostics.add(
            line=line,
            field=None,
            code="duplicate_header",
            message="field names must be unique",
        )
    for required in _REQUIRED_FIELDS:
        if required not in field_tuple:
            diagnostics.add(
                line=line,
                field=required,
                code="missing_field",
                message=f"required field {required!r} is missing",
            )
    for unknown in sorted(set(field_tuple) - _ALLOWED_FIELDS):
        diagnostics.add(
            line=line,
            field=unknown or None,
            code="unknown_field",
            message=f"field {unknown!r} is not part of {TICKET_IMPORT_CONTRACT_VERSION}",
        )


def _record_from_payload(
    payload: Mapping[str, object],
    *,
    line: int,
    diagnostics: _DiagnosticCollector,
) -> ResolvedTicketRecord | None:
    starting_error_count = diagnostics.total
    _validate_fields(payload.keys(), line=line, diagnostics=diagnostics)
    ticket_id = _string_value(
        payload,
        "ticket_id",
        line=line,
        max_length=160,
        required=True,
        diagnostics=diagnostics,
    )
    resolved_at_raw = _string_value(
        payload,
        "resolved_at",
        line=line,
        max_length=80,
        required=True,
        diagnostics=diagnostics,
    )
    issue_signature = _string_value(
        payload,
        "issue_signature",
        line=line,
        max_length=160,
        required=True,
        diagnostics=diagnostics,
    )
    title = _string_value(
        payload,
        "title",
        line=line,
        max_length=500,
        required=True,
        diagnostics=diagnostics,
    )
    sanitized_summary = _string_value(
        payload,
        "sanitized_summary",
        line=line,
        max_length=4000,
        required=True,
        diagnostics=diagnostics,
    )
    sanitized_resolution = _string_value(
        payload,
        "sanitized_resolution",
        line=line,
        max_length=4000,
        required=True,
        diagnostics=diagnostics,
    )
    optional_values = {
        field_name: _string_value(
            payload,
            field_name,
            line=line,
            max_length=160,
            required=False,
            diagnostics=diagnostics,
        )
        for field_name in (
            "product_line",
            "feature",
            "plan",
            "region",
            "language",
            "product_version",
        )
    }

    resolved_at: datetime | None = None
    if resolved_at_raw is not None:
        try:
            resolved_at = datetime.fromisoformat(resolved_at_raw.replace("Z", "+00:00"))
        except ValueError:
            diagnostics.add(
                line=line,
                field="resolved_at",
                code="invalid_datetime",
                message="resolved_at must be an ISO-8601 timestamp",
            )
        else:
            if resolved_at.tzinfo is None or resolved_at.utcoffset() is None:
                diagnostics.add(
                    line=line,
                    field="resolved_at",
                    code="timezone_required",
                    message="resolved_at must include a timezone",
                )
            else:
                resolved_at = resolved_at.astimezone(timezone.utc)

    if issue_signature is not None:
        issue_signature = issue_signature.casefold()
        if _ISSUE_SIGNATURE_RE.fullmatch(issue_signature) is None:
            diagnostics.add(
                line=line,
                field="issue_signature",
                code="invalid_issue_signature",
                message=(
                    "issue_signature must contain 2-160 lowercase letters, numbers, "
                    "dots, underscores, or hyphens"
                ),
            )

    object_type_raw = _string_value(
        payload,
        "object_type",
        line=line,
        max_length=80,
        required=False,
        diagnostics=diagnostics,
    )
    object_type = KnowledgeObjectType.TROUBLESHOOTING_FLOW
    if object_type_raw is not None:
        try:
            object_type = KnowledgeObjectType(object_type_raw)
        except ValueError:
            diagnostics.add(
                line=line,
                field="object_type",
                code="invalid_object_type",
                message=(
                    "object_type must be one of "
                    + ", ".join(item.value for item in KnowledgeObjectType)
                ),
            )

    if diagnostics.total != starting_error_count:
        return None
    assert ticket_id is not None
    assert resolved_at is not None
    assert issue_signature is not None
    assert title is not None
    assert sanitized_summary is not None
    assert sanitized_resolution is not None
    return ResolvedTicketRecord(
        ticket_id=ticket_id,
        resolved_at=resolved_at,
        issue_signature=issue_signature,
        title=title,
        sanitized_summary=sanitized_summary,
        sanitized_resolution=sanitized_resolution,
        product_line=optional_values["product_line"],
        feature=optional_values["feature"],
        plan=optional_values["plan"],
        region=optional_values["region"],
        language=optional_values["language"],
        product_version=optional_values["product_version"],
        object_type=object_type,
    )


def _string_value(
    payload: Mapping[str, object],
    field_name: str,
    *,
    line: int,
    max_length: int,
    required: bool,
    diagnostics: _DiagnosticCollector,
) -> str | None:
    if field_name not in payload:
        return None
    raw_value = payload.get(field_name)
    if raw_value is None:
        if required:
            diagnostics.add(
                line=line,
                field=field_name,
                code="missing_value",
                message=f"{field_name} is required",
            )
        return None
    if not isinstance(raw_value, str):
        diagnostics.add(
            line=line,
            field=field_name,
            code="invalid_type",
            message=f"{field_name} must be a string",
        )
        return None
    value = raw_value.strip()
    if not value:
        if required:
            diagnostics.add(
                line=line,
                field=field_name,
                code="blank_value",
                message=f"{field_name} must not be blank",
            )
        return None
    if len(value) > max_length:
        diagnostics.add(
            line=line,
            field=field_name,
            code="value_too_long",
            message=f"{field_name} must not exceed {max_length} characters",
        )
        return None
    return value


def _candidate_from_records(
    records: list[ResolvedTicketRecord],
    *,
    source_ref: str,
    source_digest: str,
    import_digest: str,
    minimum_cluster_size: int,
) -> TicketClusterCandidate:
    ordered = sorted(records, key=lambda item: (item.resolved_at, item.ticket_id))
    representative = ordered[0]
    cluster_payload = json.dumps(
        representative.cluster_key,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    cluster_digest = hashlib.sha256(cluster_payload.encode("utf-8")).hexdigest()[:16]
    signature_slug = representative.issue_signature[:80]
    cluster_ref = f"ticket-cluster:{source_digest}:{signature_slug}:{cluster_digest}"
    signal_ref = f"ticket-import:{source_digest}:{cluster_digest}"
    evidence_refs = tuple(
        _evidence_ref(record, source_ref=source_ref, source_digest=source_digest)
        for record in ordered[:MAX_CLUSTER_EVIDENCE_REFS]
    )
    representative_excerpt = _representative_excerpt(ordered)
    return TicketClusterCandidate(
        cluster_ref=cluster_ref,
        signal_ref=signal_ref,
        source_ref=source_ref,
        issue_signature=representative.issue_signature,
        title=representative.title,
        object_type=representative.object_type,
        audience_filter=AudienceFilter(
            visibility=Visibility.INTERNAL,
            product_lines=(representative.product_line,)
            if representative.product_line
            else (),
            plans=(representative.plan,) if representative.plan else (),
            regions=(representative.region,) if representative.region else (),
            languages=(representative.language,) if representative.language else (),
            product_versions=(representative.product_version,)
            if representative.product_version
            else (),
        ),
        feature=representative.feature,
        member_count=len(ordered),
        minimum_cluster_size=minimum_cluster_size,
        window_start=ordered[0].resolved_at,
        window_end=ordered[-1].resolved_at,
        evidence_refs=evidence_refs,
        import_digest=import_digest,
        representative_excerpt=representative_excerpt,
    )


def _evidence_ref(
    record: ResolvedTicketRecord,
    *,
    source_ref: str,
    source_digest: str,
) -> GovernanceEvidenceRef:
    ticket_digest = hashlib.sha256(record.ticket_id.encode("utf-8")).hexdigest()[:16]
    return GovernanceEvidenceRef(
        evidence_id=f"ev-ticket:{source_digest}:{ticket_digest}",
        source_ref=f"{source_ref}#ticket={quote(record.ticket_id, safe='')}",
        excerpt=_truncate(
            f"{record.sanitized_summary} Resolution: {record.sanitized_resolution}",
            4000,
        ),
        observed_at=record.resolved_at,
    )


def _representative_excerpt(records: list[ResolvedTicketRecord]) -> str:
    excerpts = [
        (
            f"ticket={record.ticket_id}: {record.sanitized_summary} "
            f"Resolution: {record.sanitized_resolution}"
        )
        for record in records[:3]
    ]
    if len(records) > len(excerpts):
        excerpts.append(f"{len(records) - len(excerpts)} additional ticket(s) omitted")
    return _truncate("\n".join(excerpts), 4000)


def _validate_source_ref(source_ref: str) -> str:
    normalized = source_ref.strip()
    if not normalized:
        raise ValueError("source_ref must not be blank")
    if len(normalized) > 300:
        raise ValueError("source_ref must not exceed 300 characters")
    if any(ord(character) < 32 for character in normalized):
        raise ValueError("source_ref must not contain control characters")
    return normalized


def _truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"
