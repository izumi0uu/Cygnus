"""Governance control-plane publish modules for Cygnus.

Ownership:
- publish preview, blast radius, propagation, and projection live here
- this package owns publish governance semantics, not runtime app-shell wiring
"""

from importlib import import_module
from typing import TYPE_CHECKING


from cygnus.publish.actions import (
    PublishGovernanceAction,
    PublishGovernanceActionType,
    PublishGovernanceResult,
    apply_publish_governance_actions,
)
from cygnus.publish.durable import (
    DurablePublishCommand,
    DurablePublishConflict,
    DurablePublishDenied,
    DurablePublishNotFound,
    PropagationUpdateCommand,
    apply_durable_publish,
    durable_publish_command_for_signal,
    persisted_publish_candidate_for_signal,
    durable_publication_result,
    get_publication,
    list_draft_publications,
    latest_publication_for_object,
    list_publication_propagations,
    publication_to_dict,
    propagation_summary,
    propagation_to_dict,
    update_propagation,
)
from cygnus.publish.delivery import (
    DeliveryAckConflict,
    DeliveryPolicyError,
    DeliveryReceiptNotFound,
    DeliveryStatus,
    DeliveryVerificationError,
    acknowledge_propagation_delivery,
    delivery_to_dict,
    list_propagation_deliveries,
    reset_delivery_circuit,
)
from cygnus.publish.propagation import (
    PropagationLedgerSummary,
    PropagationStatus,
    PublishPropagationLedger,
    SurfacePropagationRecord,
    SurfacePropagationUpdate,
    build_publish_propagation_ledger,
)
from cygnus.publish.preview import (
    AudienceScopeSummary,
    BlastRadiusEffect,
    BlastRadiusImpact,
    BlastRadiusPreview,
    ChannelGateSummary,
    PublishActionType,
    PublishBinding,
    PublishConflict,
    PublishPreviewCandidate,
    build_publish_blast_radius_preview,
    build_publish_preview_candidate,
)

if TYPE_CHECKING:
    from cygnus.publish.surface import (
        PublishActionEcho,
        PublishActionPreset,
        PublishPropagationSurface,
        PublishPreviewSurface,
        PublishSituationFrame,
        PropagationStatusLane,
        apply_pressure_intake_publish_action,
        get_pressure_intake_publish_propagation_surface,
        get_pressure_intake_publish_preview_surface,
    )
from cygnus.publish.session_projection import (
    clear_publish_projections,
    get_publish_projection,
    PublishProjectionSnapshot,
    PublishProjectionStore,
    projection_store,
    remember_publish_projection,
)

_SURFACE_EXPORTS = {
    "PublishActionEcho",
    "PublishActionPreset",
    "PublishPropagationSurface",
    "PublishPreviewSurface",
    "PublishSituationFrame",
    "PropagationStatusLane",
    "apply_pressure_intake_publish_action",
    "get_pressure_intake_publish_propagation_surface",
    "get_pressure_intake_publish_preview_surface",
}


def __getattr__(name: str):
    if name not in _SURFACE_EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module("cygnus.publish.surface"), name)
    globals()[name] = value
    return value


__all__ = [
    "AudienceScopeSummary",
    "BlastRadiusEffect",
    "BlastRadiusImpact",
    "BlastRadiusPreview",
    "ChannelGateSummary",
    "DurablePublishCommand",
    "DurablePublishConflict",
    "DurablePublishDenied",
    "DurablePublishNotFound",
    "DeliveryAckConflict",
    "DeliveryPolicyError",
    "DeliveryReceiptNotFound",
    "DeliveryStatus",
    "DeliveryVerificationError",
    "PropagationLedgerSummary",
    "PropagationStatus",
    "PublishActionType",
    "PublishGovernanceAction",
    "PublishGovernanceActionType",
    "PublishGovernanceResult",
    "PublishBinding",
    "PublishConflict",
    "PublishPropagationLedger",
    "PublishPreviewCandidate",
    "PublishActionEcho",
    "PublishActionPreset",
    "PublishPropagationSurface",
    "PublishProjectionSnapshot",
    "PublishProjectionStore",
    "PublishPreviewSurface",
    "PublishSituationFrame",
    "PropagationStatusLane",
    "PropagationUpdateCommand",
    "SurfacePropagationRecord",
    "SurfacePropagationUpdate",
    "apply_publish_governance_actions",
    "apply_durable_publish",
    "acknowledge_propagation_delivery",
    "delivery_to_dict",
    "list_propagation_deliveries",
    "reset_delivery_circuit",
    "build_publish_blast_radius_preview",
    "build_publish_preview_candidate",
    "build_publish_propagation_ledger",
    "get_pressure_intake_publish_propagation_surface",
    "get_pressure_intake_publish_preview_surface",
    "projection_store",
    "remember_publish_projection",
    "get_publish_projection",
    "clear_publish_projections",
    "durable_publish_command_for_signal",
    "persisted_publish_candidate_for_signal",
    "durable_publication_result",
    "get_publication",
    "latest_publication_for_object",
    "list_publication_propagations",
    "list_draft_publications",
    "publication_to_dict",
    "propagation_summary",
    "propagation_to_dict",
    "update_propagation",
    "apply_pressure_intake_publish_action",
]
