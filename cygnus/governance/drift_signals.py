from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from cygnus.domain.audience import AudienceFilter
from cygnus.governance.audience_bindings import (
    AudienceBindingLifecycle,
    audience_filter_from_binding,
    list_audience_bindings,
)
from cygnus.governance.signals import (
    GovernanceSignalStatus,
    governance_signal_to_pressure_record,
    list_governance_signals,
)
from cygnus.review.intake import (
    PressureSignalType,
    compile_pressure_proposal_bundles,
)
from cygnus.review.service import ProposalBundle
from cygnus.runtime.database.models import Employee, GovernanceSignal
from cygnus.runtime.services.permission_engine import build_wiki_scope_clause


DRIFT_SIGNAL_TYPES = (
    PressureSignalType.RELEASE_DELTA,
    PressureSignalType.INCIDENT_DELTA,
)
_DRIFT_COVERAGE = tuple(signal_type.value for signal_type in DRIFT_SIGNAL_TYPES)
_DRIFT_SIGNAL_VALUES = frozenset(_DRIFT_COVERAGE)


@dataclass(frozen=True, slots=True)
class DriftSignalProviderResult:
    """Persisted drift rows plus explicit coverage and relation resolution state."""

    signals: tuple[GovernanceSignal, ...]
    bundles: tuple[ProposalBundle, ...]
    covered_signals: tuple[str, ...] = _DRIFT_COVERAGE
    missing_signals: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        signals = tuple(self.signals)
        bundles = tuple(self.bundles)
        covered_signals = _normalize_coverage(self.covered_signals)
        missing_signals = _normalize_coverage(self.missing_signals)
        if not covered_signals:
            if signals or bundles:
                raise ValueError(
                    "an unavailable drift provider cannot contain signals or bundles"
                )
            if not missing_signals:
                missing_signals = _DRIFT_COVERAGE
        if set(covered_signals).intersection(missing_signals):
            raise ValueError("drift coverage cannot be both covered and missing")
        object.__setattr__(self, "signals", signals)
        object.__setattr__(self, "bundles", bundles)
        object.__setattr__(self, "covered_signals", covered_signals)
        object.__setattr__(self, "missing_signals", missing_signals)


async def load_drift_signal_provider(
    session: AsyncSession,
    *,
    current_user: Employee,
) -> DriftSignalProviderResult:
    """Load ordered drift facts and resolve binding-backed audiences in one batch."""
    signals = await list_governance_signals(
        session,
        current_user=current_user,
        status=GovernanceSignalStatus.ACTIVE,
        signal_types=DRIFT_SIGNAL_TYPES,
    )
    binding_refs = tuple(
        dict.fromkeys(
            signal.audience_binding_ref
            for signal in signals
            if signal.audience_filter is None
            and signal.audience_binding_ref is not None
        )
    )
    bindings_by_key = {}
    if binding_refs:
        bindings = await list_audience_bindings(
            session,
            binding_keys=binding_refs,
            lifecycle_state=AudienceBindingLifecycle.ACTIVE,
            page_scope_clause=build_wiki_scope_clause(current_user),
        )
        bindings_by_key = {binding.binding_key: binding for binding in bindings}

    resolved_signals: list[GovernanceSignal] = []
    audience_filters_by_signal_ref: dict[str, AudienceFilter] = {}
    unresolved_audience_binding = False
    for signal in signals:
        if signal.audience_filter is None:
            binding = bindings_by_key.get(signal.audience_binding_ref or "")
            if (
                binding is None
                or binding.page_id != signal.page_id
                or binding.object_ref != signal.object_ref
            ):
                unresolved_audience_binding = True
                continue
            audience_filters_by_signal_ref[signal.signal_ref] = (
                audience_filter_from_binding(binding)
            )
        resolved_signals.append(signal)

    return DriftSignalProviderResult(
        signals=signals,
        bundles=compile_drift_signal_bundles(
            resolved_signals,
            audience_filters_by_signal_ref=audience_filters_by_signal_ref,
        ),
        missing_signals=(
            ("audience_binding_resolution",) if unresolved_audience_binding else ()
        ),
    )


def compile_drift_signal_bundles(
    signals: Iterable[GovernanceSignal],
    *,
    audience_filters_by_signal_ref: Mapping[str, AudienceFilter] | None = None,
) -> tuple[ProposalBundle, ...]:
    resolved_audiences = audience_filters_by_signal_ref or {}
    records = (
        governance_signal_to_pressure_record(
            signal,
            audience_filter=resolved_audiences.get(signal.signal_ref),
        )
        for signal in signals
        if signal.signal_type in _DRIFT_SIGNAL_VALUES
    )
    return compile_pressure_proposal_bundles(records)


def _normalize_coverage(values: Iterable[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    for raw_value in values:
        value = raw_value.strip()
        if not value:
            raise ValueError("coverage signal values must not be blank")
        if value not in normalized:
            normalized.append(value)
    return tuple(normalized)
