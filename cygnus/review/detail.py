from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from cygnus.review.fixtures import sample_review_bundles
from cygnus.review.item import ReviewItemDetailSurface, build_review_item_detail_surface
from cygnus.review.service import ProposalBundle, build_review_risk_item


@dataclass(frozen=True, slots=True, kw_only=True)
class ReviewItemQuery:
    object_ref: str

    def __post_init__(self) -> None:
        if not self.object_ref.strip():
            raise ValueError("object_ref must not be blank")



def get_review_item_detail(
    query: ReviewItemQuery,
    *,
    bundles: Iterable[ProposalBundle] | None = None,
) -> ReviewItemDetailSurface:
    source_bundles = tuple(bundles) if bundles is not None else sample_review_bundles()
    for bundle in source_bundles:
        if bundle.proposal.proposal_id != query.object_ref:
            continue
        item = build_review_risk_item(bundle)
        return build_review_item_detail_surface(
            item=item,
            evidence=bundle.evidence,
            evidence_sufficiency=bundle.proposal.evidence_sufficiency,
        )
    raise ValueError(f"review item detail not found for object_ref={query.object_ref}")
