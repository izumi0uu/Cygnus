from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from cygnus.domain.objects import TroubleshootingFlow
from cygnus.publish import projection_store
from cygnus.retrieval import SourceTraceResolver, sample_knowledge_objects, sample_support_evidence
from cygnus.runtime.services.auth_service import get_current_user

router = APIRouter()


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
