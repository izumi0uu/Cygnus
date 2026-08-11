# Support Brain for SaaS — Core Workflows / Lifecycle

## 1. Goal
This document defines the product-level lifecycle that must exist for Support Brain. It is not a low-level job orchestration spec.

## 2. Main workflow overview
1. **Ingest**
2. **Normalize**
3. **Map / Reduce**
4. **Plan**
5. **Review**
6. **Publish**
7. **Feedback Loop**

## 3. Stage definitions

### 3.1 Ingest
Inputs come from:
- Help Center / docs
- helpdesk articles
- internal SOP / wiki
- resolved tickets / chat transcripts
- release notes
- incidents / known issues

Outputs:
- parsable source records
- sync status and failure status

### 3.2 Normalize
Unifies fragmented sources into support semantics.

Key normalization dimensions:
- product / feature
- plan / tier
- region
- language
- product version
- issue type
- visibility (internal / external)

Outputs:
- normalized support evidence
- tags / metadata / confidence / freshness markers

### 3.3 Map / Reduce
Extracts support patterns that can become knowledge objects.

Key extractions:
- recurring questions
- rules and exceptions
- troubleshooting sequences
- known-issue patterns
- escalation triggers
- audience-specific differences

Outputs:
- candidate answer shapes
- ticket clusters
- draft object suggestions

### 3.4 Plan
Decides what objects should be created or updated rather than directly generating final answers.

Planning dimensions:
- object type
- evidence sufficiency
- urgency / freshness
- audience coverage gap
- risk of wrong answer

Outputs:
- create / update proposals
- suggested priority
- routed reviewer ownership

### 3.5 Review
Human or controlled-AI review layer.

Review questions:
- is the evidence sufficient?
- is the object type correct?
- are audience variants complete?
- should the object be internal-only?
- are there policy or compliance risks?

Outputs:
- approved draft
- rejected draft
- needs-more-evidence draft

### 3.6 Publish
Ships approved objects to target channels.

Example channels:
- internal support copilot
- internal AI assistant / MCP
- external help center
- customer-facing answer engine (later)

Publication controls:
- audience filters
- internal/external visibility
- versioning
- publish history

Publish actions (beyond approve / reject):
- `publish` / `restrict` / `split_variant` / `hold_external` / `republish_internal_only`

Pre-publish blast-radius preview (consequence per audience × channel):
- `new_exposure` / `continuing_exposure` / `stopped_exposure` / `conflict`

Post-publish propagation status (whether each downstream surface has synced):
- `synced` / `pending` / `failed` / `manual_action_required`

### 3.7 Feedback Loop
Uses consumption results to expose knowledge gaps.

Example signals:
- unresolved conversation
- low rating
- human rewrite
- escalation after suggestion
- stale answer after release or incident change

Outputs:
- drift alert
- coverage gap
- refresh candidate
- object deprecation/update queue
- durable feedback-route lifecycle truth (`queued` → `running` → `completed`; `blocked` for missing/draft-only/ineligible targets; failures requeue with bounded backoff up to 3 attempts, then end `failed`), whose completion materializes into governed review truth without auto-changing content or publishing

## 4. Key loops
### Loop A: Ticket-to-Knowledge
Repeated tickets -> cluster -> draft object -> review -> publish

CYG-122 freezes Loop A's input boundary as a bounded pilot: an administrator submits an already-sanitized `resolved-ticket-export/v1` CSV/JSONL snapshot through `POST /api/governance/ticket-imports`; `source_ref` is the immutable export identity, and the whole payload must validate before deterministic grouping by `issue_signature + audience/product/version/language + object_type`. Clusters below the configurable threshold remain observable response candidates only; qualifying clusters reuse the existing `GovernanceSignal` and review-assignment truth with structured ticket evidence refs. Exact replay returns the same signal, while changed facts under the same `source_ref` conflict; import never auto-creates a draft, approves, or publishes.

### Loop B: Freshness Recovery
Release/incident change -> drift alert -> revision draft -> review -> republish

### Loop C: Consumption-to-Improvement
Copilot answer -> rewrite/reject/escalate -> feedback signal -> coverage fix

### From signal to governance command (signal → review pressure → command)
Drift / ticket / source signals are not just observations; they are governance commands that can be issued directly. The command types are already settled in the implementation:
- drift → `open_urgent_review` / `freeze_external_publish` / `force_audience_recheck`
- ticket / rewrite pressure (`ticket_pressure`) → `route_to_review` / `assign_owner` / `mark_urgent`
- source blindness → `repair_source` / `restrict_propagation` / `route_to_human_review`
- review-queue re-stacking → `restack` / `reroute` / `escalate`
- consumption feedback routes (CYG-118/119): `low_rating` materializes as review pressure (`ticket_pressure`, unknown freshness) and `stale_answer` as suspected freshness/drift review (`drift`, stale freshness); route execution only materializes durable governed review truth and never auto-changes content or publishes
- CYG-120 operations observation: `GovernanceFeedbackRoute` remains the only queue truth; permission-scoped SQL summaries/drilldowns and structured worker-outcome events distinguish backlog, due age, lease expiry, retries, blocked/failed outcomes, and outcome/review traces, but this operational evidence is not reviewer action, publication, propagation, or a business KPI

## 5. Lifecycle principles
1. **New knowledge defaults to draft**
2. **No publication without traceable evidence**
3. **Audience fit is part of correctness**
4. **Feedback is a first-class product input**
5. **Refresh is continuous, not an afterthought**

## 6. V1 workflow boundary
V1 must clearly explain:
- how internal copilot consumes published knowledge
- how ticket patterns become knowledge suggestions
- how publication is controlled by audience and visibility
- how bad answers feed back into knowledge updates

V1 does not need to fully define:
- action-layer orchestration
- fully autonomous customer-bot loops
- fine-grained infra jobs / queues / schedulers
