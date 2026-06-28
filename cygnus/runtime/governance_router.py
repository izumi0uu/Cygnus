from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from cygnus.runtime.services.auth_service import get_current_user, require_admin
from cygnus.domain.objects import TroubleshootingFlow
from cygnus.publish import (
    apply_pressure_intake_publish_action,
    get_pressure_intake_publish_preview_surface,
    get_pressure_intake_publish_propagation_surface,
    get_pressure_intake_recovery_proof_surface,
    projection_store,
)
from cygnus.recovery import (
    DownstreamRealityCheckQuery,
    GovernanceOverviewQuery,
    RecoveryWindowQuery,
    get_downstream_reality_check_surface,
    get_governance_overview_surface,
    get_recovery_window_surface,
    sample_recovery_command_refs,
)
from cygnus.retrieval import (
    SourceTraceResolver,
    sample_knowledge_objects,
    sample_support_evidence,
)
from cygnus.review import (
    OwnerState,
    ReviewHomeQuery,
    build_pressure_intake_surfaces,
    get_pressure_intake_review_queue_drilldown,
    get_review_home_surface,
    sample_pressure_intake_records,
)
from cygnus.review.drift import get_drift_governance_surface
from cygnus.review.source_blindness import get_source_blindness_surface

router = APIRouter(tags=["governance"])


class PublishApplyRequest(BaseModel):
    object_ref: str | None = None
    action_key: str
    reason: str | None = None


@router.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/api/command-center")
def command_center(_current_user=Depends(get_current_user)) -> dict[str, object]:
    """Risk-ranked morning command brief for the Command Center surface."""
    return get_review_home_surface().to_dict()


@router.get("/api/drift")
def drift(_current_user=Depends(get_current_user)) -> dict[str, object]:
    """Release/incident drift governance surface — freshness loss forcing a governance path."""
    return get_drift_governance_surface().to_dict()


@router.get("/api/source-blindness")
def source_blindness(_current_user=Depends(get_current_user)) -> dict[str, object]:
    """Source-blindness governance surface — sync loss expressed as governance loss, not noise."""
    return get_source_blindness_surface().to_dict()


@router.get("/api/review-intake")
def review_intake(_current_user=Depends(get_current_user)) -> dict[str, object]:
    """Surface-ready review intake compiled from support pressure and source-loss signals."""
    return build_pressure_intake_surfaces(sample_pressure_intake_records()).to_dict()


@router.get("/api/review-queue/{object_ref}")
def review_queue_item(
    object_ref: str,
    owner_state: str | None = None,
    _current_user=Depends(get_current_user),
) -> dict[str, object]:
    """Queue-preserving governance drilldown compiled from the pressure intake bundle set."""
    review_query = (
        ReviewHomeQuery(owner_state=OwnerState(owner_state))
        if owner_state is not None
        else None
    )
    return get_pressure_intake_review_queue_drilldown(
        object_ref,
        records=sample_pressure_intake_records(),
        review_query=review_query,
    ).to_dict()


@router.get("/api/publish-preview")
def publish_preview(
    object_ref: str | None = None,
    action_key: str | None = None,
    _current_user=Depends(get_current_user),
) -> dict[str, object]:
    """Blast-radius-first publish surface compiled from the same pressure intake bundle set."""
    return get_pressure_intake_publish_preview_surface(
        selected_object_ref=object_ref,
        records=sample_pressure_intake_records(),
        action_key=action_key,
    ).to_dict()


@router.post("/api/publish/apply")
def publish_apply(
    body: PublishApplyRequest,
    _current_user=Depends(require_admin),
) -> dict[str, object]:
    """Execute a real publish governance command and return the full result."""
    try:
        result = apply_pressure_intake_publish_action(
            selected_object_ref=body.object_ref,
            action_key=body.action_key,
            records=sample_pressure_intake_records(),
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    payload = result.to_dict()
    payload["rehearsal"] = True
    payload["persisted"] = False
    payload["selected_action"] = body.action_key
    projection_store.remember(
        payload["updated_candidate"]["object_id"],
        selected_action=body.action_key,
        result=result,
    )
    return payload


@router.get("/api/publish-propagation")
def publish_propagation(
    object_ref: str | None = None,
    action_key: str | None = None,
    _current_user=Depends(get_current_user),
) -> dict[str, object]:
    """Supporting-surface propagation theater compiled from the current publish command rehearsal."""
    return get_pressure_intake_publish_propagation_surface(
        selected_object_ref=object_ref,
        records=sample_pressure_intake_records(),
        action_key=action_key,
    ).to_dict()


@router.get("/api/recovery-proof")
def recovery_proof(
    object_ref: str | None = None,
    action_key: str | None = None,
    _current_user=Depends(get_current_user),
) -> dict[str, object]:
    """Frontline reality-check surface proving whether a governance command changed support behavior."""
    return get_pressure_intake_recovery_proof_surface(
        selected_object_ref=object_ref,
        records=sample_pressure_intake_records(),
        action_key=action_key,
    ).to_dict()


@router.get("/api/recovery/downstream-reality-check/{command_id}")
def downstream_reality_check(
    command_id: str,
    _current_user=Depends(get_current_user),
) -> dict[str, object]:
    """Frontline recovery feedback for a specific governance command."""
    return get_downstream_reality_check_surface(
        DownstreamRealityCheckQuery(command_id=command_id)
    ).to_dict()


@router.get("/api/recovery/window/{command_id}")
def recovery_window(
    command_id: str,
    _current_user=Depends(get_current_user),
) -> dict[str, object]:
    """Before/after recovery proof for a specific governance command."""
    return get_recovery_window_surface(
        RecoveryWindowQuery(command_id=command_id)
    ).to_dict()


@router.get("/api/recovery/overview")
def governance_overview(_current_user=Depends(get_current_user)) -> dict[str, object]:
    """Compare open loops to choose the next highest-leverage command."""
    return get_governance_overview_surface(
        GovernanceOverviewQuery(
            command_ids=tuple(ref.command_id for ref in sample_recovery_command_refs())
        )
    ).to_dict()


@router.get("/api/knowledge-graph")
def knowledge_graph(_current_user=Depends(get_current_user)) -> dict[str, object]:
    """Typed knowledge objects, evidence, and audiences as a relationship graph."""
    objects = sample_knowledge_objects()
    evidence = sample_support_evidence()
    evidence_by_id = {e.evidence_id: e for e in evidence}

    nodes: list[dict[str, object]] = []
    edges: list[dict[str, object]] = []
    seen_edges: set[tuple[str, str, str]] = set()

    def _add_edge(source: str, target: str, kind: str) -> None:
        key = (source, target, kind)
        if key in seen_edges:
            return
        seen_edges.add(key)
        edges.append({"source": source, "target": target, "kind": kind})

    audience_node_ids: dict[str, str] = {}

    def _audience_node_id(audience_dict: dict[str, object]) -> str:
        parts = [str(audience_dict["visibility"])]
        for facet in (
            "brands",
            "product_lines",
            "plans",
            "regions",
            "languages",
            "product_versions",
        ):
            parts.extend(str(v) for v in audience_dict.get(facet, []))
        key = ":".join(parts) if parts else "global"
        if key not in audience_node_ids:
            audience_node_ids[key] = f"aud:{len(audience_node_ids)}"
            nodes.append(
                {
                    "id": audience_node_ids[key],
                    "kind": "audience",
                    "label": key,
                    "visibility": audience_dict["visibility"],
                    "is_global": audience_dict.get("is_global", False),
                }
            )
        return audience_node_ids[key]

    for obj in objects:
        object_dict = obj.to_dict()
        nodes.append(
            {
                "id": obj.object_id,
                "kind": "object",
                "label": obj.title,
                "object_type": obj.object_type.value,
                "lifecycle_state": object_dict["lifecycle_state"],
                "summary": obj.summary,
            }
        )

        for evidence_id in obj.evidence_ids:
            if evidence_id in evidence_by_id:
                _add_edge(obj.object_id, evidence_id, "cites")

        for audience in obj.supported_audiences:
            audience_dict = audience.to_dict()
            _add_edge(obj.object_id, _audience_node_id(audience_dict), "serves")

        if isinstance(obj, TroubleshootingFlow) and obj.escalation_route_id:
            _add_edge(obj.object_id, obj.escalation_route_id, "escalates_to")

    for ev in evidence:
        nodes.append(
            {
                "id": ev.evidence_id,
                "kind": "evidence",
                "label": ev.title,
                "source_type": ev.source_type.value,
                "freshness": ev.freshness_state.value,
                "source_ref": ev.source_ref,
            }
        )

    return {
        "nodes": nodes,
        "edges": edges,
        "stats": {
            "objects": sum(1 for n in nodes if n["kind"] == "object"),
            "evidence": sum(1 for n in nodes if n["kind"] == "evidence"),
            "audiences": len(audience_node_ids),
            "edges": len(edges),
        },
    }


@router.get("/api/traceability/{object_id}")
def traceability(
    object_id: str,
    _current_user=Depends(get_current_user),
) -> dict[str, object]:
    """Full evidence→source→freshness traceability chain for one knowledge object."""
    objects = sample_knowledge_objects()
    evidence = sample_support_evidence()
    resolver = SourceTraceResolver(objects=objects, evidence=evidence)

    selected = resolver.find_object(object_id)
    if selected is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"unknown knowledge object: {object_id}",
        )

    trace = resolver.build_trace_for_object(selected)
    object_dict = selected.to_dict()
    return {
        "surface_id": "traceability-chain",
        "object": {
            "object_id": selected.object_id,
            "object_type": object_dict["object_type"],
            "title": selected.title,
            "summary": selected.summary,
            "lifecycle_state": object_dict["lifecycle_state"],
            "supported_audiences": object_dict.get("supported_audiences", []),
            "publish_targets": object_dict.get("publish_targets", []),
        },
        "trace": trace.to_dict(),
        "projection": (
            (
                snapshot.result.to_dict()
                | {
                    "selected_action": snapshot.selected_action,
                    "persisted": False,
                    "rehearsal": True,
                }
            )
            if (snapshot := projection_store.get(selected.object_id)) is not None
            else None
        ),
    }
