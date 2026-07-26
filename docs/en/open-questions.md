# Support Brain for SaaS — Open Questions & Validation Hypotheses

## 1. Purpose
This document captures what the first-pass package intentionally leaves unresolved so later research, validation, and architecture work can use it as a boundary map.

## 2. Product hypotheses to validate
### H1. Internal-copilot-first will prove ROI faster than customer-facing-first
Why it matters:
- lower answer-risk surface
- easier to avoid high-cost public mistakes
- easier to measure value from ticket patterns and human rewrites

Validation signals:
- support-agent acceptance rate
- rewrite-rate reduction
- escalation-rate change
- knowledge-suggestion acceptance rate

### H2. Ticket cluster -> knowledge suggestion is a core differentiator
Why it matters:
- doc-only ingest risks collapsing the product into a generic knowledge layer
- stable cluster-to-object conversion demonstrates support-native intelligence

Validation signals:
- cluster-to-draft usefulness rate
- reviewer acceptance rate
- time from cluster to published object

### H3. Audience-aware publishing is a stronger moat than raw answer correctness alone
Why it matters:
- support errors often come from entitlement, region, and version mismatch
- audience mismatch can be more costly than generic text error

Validation signals:
- variant coverage ratio
- audience-related answer failures
- plan/version-specific rewrite frequency

## 3. Decisions still open
1. Should the first audience layer only include plan / region / version?
2. Should internal-only and external-approved be modeled as first-class permission layers?
3. What is the minimum evidence threshold for ticket-cluster-generated drafts?
4. When should a Known Issue Page automatically differ from or convert into an Answer Card?
5. Should Escalation Route remain a standalone object or attach to other objects?
6. What is the minimum useful metric set for the Coverage & Drift Dashboard?
7. Frontend product language, Phase 2: the domain-generated narrative (`title` / `why_now_summary` / `primary_tension` / `headline`) is currently hard-coded English; the backend should instead expose structured fields (enum + params) and let the frontend compose the sentence in zh/en — this also undoes the "UI copy coupled into the domain layer" issue. Phase 1 (frontend enum/identifier vocabulary `frontend/src/lib/vocab.ts`) is done; Phase 2 awaits backend scheduling.
8. In the P2.5 internalization lane, which cut should come first — **identity, assembly, namespace, or deletion-readiness** — so Cygnus avoids both “secretly rewriting P1” and “blocking early P3”?
9. Should optional product-shell parity remain a deferred / non-roadmap lane permanently, rather than becoming a formal roadmap item?
   - Current frozen boundary: `auth / admin / wiki` shells must be classified first; non-support pages remain isolated in the future parity lane unless they directly unblock support verticalization.

## 4. Integration questions
- which source connectors should be first priority?
- are release notes and incident records structured enough to support freshness loops?
- will cross-helpdesk data-model differences distort the unified object layer?
- what is the minimum MCP / internal AI tool surface needed for consumption?
- what additional runtime constraints are still needed to keep Nanobot session behavior separate from Cygnus typed-domain control?

## 5. Risk list
### R1. Generic RAG drift
Risk: the product gets interpreted as “another search layer over knowledge”
Mitigation: keep support-native objects as the primary noun in all docs and designs

### R2. Scope expansion too early
Risk: customer bot, action layer, and commercial narrative all expand at once
Mitigation: keep internal-copilot-first and product-core-first boundaries intact

### R3. Freshness without governance
Risk: ingest exists but review/publish/traceability do not
Mitigation: keep review and publishing as central product surfaces

### R4. Audience modeling remains under-specified
Risk: an answer appears correct but is shown to the wrong audience
Mitigation: treat audience variant as an object-layer concern, not a post-processing trick

### R5. Full-port drift without boundary discipline
Risk: full-port work starts mixing import parity, runability recovery, and support verticalization back into one vague “done” state
Mitigation: keep Jira and docs aligned to P0/P1/P2/P2.5/P3/P4 and refuse fuzzy completion language

### R6. Optional shell parity steals the current roadmap
Risk: product-shell or admin-shell parity begins consuming bandwidth meant for P1/P2/P3
Mitigation: treat shell parity as deferred / non-roadmap by default unless it directly unblocks support verticalization

## 6. Future topics intentionally deferred
- detailed technical architecture
- permissions and compliance model
- action layer
- customer-facing bot UX
- GTM / pricing / packaging
