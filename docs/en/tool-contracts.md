# Support Brain for SaaS — Tool Contracts (Nanobot ↔ Cygnus)

## 1. Purpose
This document defines the first **target** tool-contract surface when **Nanobot** acts as the **session layer** and **Cygnus** acts as the **domain control plane**.

It describes the interface shape that should stabilize over time, and should not be auto-read as “the current code already fulfills all of this.”

The goal is not to write SDK code yet. The goal is to settle:
- which capabilities Nanobot consumes
- which capabilities must remain inside the Cygnus domain harness
- the input/output/risk/approval boundary for each tool
- how retrieval, review, publication, and traceability stay domain-native rather than collapsing into generic runtime behavior

## 2. Boundary principles
### 2.1 All high-risk business decisions stay in Cygnus
Nanobot may:
- initiate retrieval
- initiate draft generation
- initiate review requests
- initiate policy validation
- initiate publish requests

Nanobot should **not**:
- mutate business state by bypassing Cygnus
- publish externally by bypassing approvals
- implement audience policy on its own
- own source-of-truth traceability on its own

### 2.2 Tools return structured observations, not free-form side effects
Every tool call must return a structured result, even when denied, timed out, blocked for approval, or missing data.

### 2.3 Draft and commit stay separate
- `propose_knowledge_object`, `update_draft_object`, and `request_review` belong to the draft side
- `publish_knowledge_object` belongs to the commit side

### 2.4 RAG belongs to Cygnus
Object retrieval, evidence retrieval, audience filtering, and traceability should be implemented inside Cygnus.
Nanobot only consumes the result surface.

## 3. Shared context fields
These fields can be reused across tools.

### 3.1 `audience_context`
```json
{
  "brand": "optional-string",
  "product_line": "optional-string",
  "plan_tier": "optional-string",
  "region": "optional-string",
  "language": "optional-string",
  "product_version": "optional-string",
  "visibility": "internal|external"
}
```

### 3.2 `source_ref`
```json
{
  "source_id": "string",
  "source_type": "help_center|ticket|chat|release_note|incident|wiki|other",
  "locator": "string"
}
```

### 3.3 `evidence_ref`
```json
{
  "evidence_id": "string",
  "source_id": "string",
  "excerpt_ref": "string",
  "confidence": 0.0,
  "freshness": "fresh|stale|unknown"
}
```

## 4. Shared result envelope
All tools should ideally share this top-level result shape:

```json
{
  "status": "success|error|denied|approval_required|not_found|conflict",
  "summary": "short human-readable summary",
  "data": {},
  "trace_ref": "optional-trace-or-audit-id",
  "warnings": [],
  "errors": []
}
```

### 4.1 Common error codes
- `invalid_arguments`
- `scope_denied`
- `approval_required`
- `policy_violation`
- `not_found`
- `stale_draft`
- `conflict_detected`
- `trace_unavailable`
- `result_too_large`
- `upstream_timeout`

## 5. Risk classes
### R0 — Read only
Pure read, no side effects.

### R1 — Draft write
Writes drafts, signals, or queues without making externally visible commits.

### R2 — Governance check
Evaluates policy/review/publication readiness without publishing.

### R3 — Commit / publish
Causes real state changes or externally visible publication.

## 6. Tool Group A — Retrieval

## 6.1 `search_knowledge_objects`
### Purpose
Search existing knowledge objects using a query plus audience context.

### Use when
- a support copilot needs directly consumable objects
- a graph must check whether a similar object already exists
- a reviewer needs comparable objects

### Do not use when
- raw evidence is required instead of object-level knowledge
- audience gating would be bypassed by broad search

### Risk class
`R0`

### Input
```json
{
  "query": "string",
  "audience_context": {},
  "object_types": ["answer_card", "troubleshooting_flow", "policy_rule", "known_issue_page", "escalation_route"],
  "limit": 10,
  "include_unpublished": false
}
```

### Output
```json
{
  "status": "success",
  "summary": "3 matching knowledge objects found",
  "data": {
    "results": [
      {
        "object_id": "ko_123",
        "slug": "billing-refund-policy",
        "object_type": "policy_rule",
        "title": "Billing Refund Policy",
        "audience_match": "exact|partial",
        "freshness": "fresh|stale|unknown",
        "publication_status": "published|draft|archived",
        "snippet": "short summary",
        "trace_ref": "trace_abc"
      }
    ]
  }
}
```

## 6.2 `read_knowledge_object`
### Purpose
Read the full detail of a single knowledge object.

### Risk class
`R0`

### Input
```json
{
  "id_or_slug": "string",
  "include_variants": true,
  "include_trace": true
}
```

### Output highlights
- canonical content
- audience variants
- status / version
- source trace summary
- allowed channels

## 6.3 `search_support_evidence`
### Purpose
Search raw or normalized support evidence rather than final knowledge objects.

### Risk class
`R0`

### Input
```json
{
  "query": "string",
  "filters": {
    "source_type": "optional-string",
    "product_line": "optional-string",
    "region": "optional-string",
    "product_version": "optional-string"
  },
  "limit": 10
}
```

### Output highlights
- evidence excerpt refs
- source refs
- freshness markers
- confidence signals

## 6.4 `get_source_trace`
### Purpose
Return the evidence trace chain for a knowledge object.

### Risk class
`R0`

### Input
```json
{
  "object_id": "string"
}
```

### Output highlights
```json
{
  "status": "success",
  "data": {
    "object_id": "ko_123",
    "version": 4,
    "evidence_refs": [],
    "publication_records": [],
    "review_history_summary": []
  }
}
```

## 7. Tool Group B — Draft / Review

## 7.1 `propose_knowledge_object`
### Purpose
Generate a draft knowledge object from evidence, ticket clusters, or operator input.

### Risk class
`R1`

### Input
```json
{
  "proposed_object_type": "answer_card|troubleshooting_flow|policy_rule|known_issue_page|escalation_route|auto",
  "title": "string",
  "input_summary": "string",
  "audience_context": {},
  "source_refs": [],
  "evidence_refs": [],
  "ticket_cluster_ref": "optional-string"
}
```

### Output highlights
- `draft_id`
- inferred object type
- draft completeness score
- missing evidence warnings
- next recommended step

## 7.2 `update_draft_object`
### Purpose
Update a draft object without publishing it.

### Risk class
`R1`

### Input
```json
{
  "draft_id": "string",
  "patch": {
    "title": "optional-string",
    "content": "optional-string",
    "audience_variants": [],
    "linked_evidence_refs": []
  }
}
```

### Output highlights
- updated draft version
- changed fields summary
- validation warnings

## 7.3 `request_review`
### Purpose
Submit a draft into the review queue.

### Risk class
`R1`

### Input
```json
{
  "draft_id": "string",
  "review_type": "content|policy|compliance|publish_readiness",
  "notes": "optional-string"
}
```

### Output highlights
- review request id
- current queue state
- expected reviewer role

## 7.4 `read_review_feedback`
### Purpose
Read review feedback for a draft.

### Risk class
`R0`

### Input
```json
{
  "draft_id": "string"
}
```

### Output highlights
- review status
- reviewer notes
- blocking issues
- approval state

## 8. Tool Group C — Governance

## 8.1 `validate_publish_policy`
### Purpose
Check audience, visibility, and policy readiness before a real publish.

### Risk class
`R2`

### Input
```json
{
  "draft_id": "string",
  "target_channel": "internal_copilot|internal_mcp|external_help_center|future_customer_answer_engine",
  "audience_context": {}
}
```

### Output highlights
```json
{
  "status": "success|denied|approval_required",
  "data": {
    "allowed": true,
    "policy_checks": [
      {
        "name": "visibility_scope",
        "result": "pass|fail|approval_required",
        "reason": "string"
      }
    ]
  }
}
```

## 8.2 `publish_knowledge_object`
### Purpose
Publish a draft to a target channel.

### Risk class
`R3`

### Current durable input
```json
{
  "draft_id": "string",
  "approval_ref": "string",
  "command_id": "string",
  "action_key": "publish|republish|restrict_publish|hold_external|republish_internal_only",
  "target_channels": ["internal_copilot", "internal_mcp"],
  "expected_version": 7
}
```

`expected_version` is the object-level optimistic-concurrency guard; publish checks it again against the locked current `WikiPage`. A replay with an already committed `command_id` still returns the original publication first.

### Permission rule
- `validate_publish_policy` is a request-scoped read-only check; callers only receive draft/object results inside their governed scope.
- `publish_knowledge_object` is administrator-only and requires a real approval ledger event.
- External and policy/regulated publication remains subject to stricter audience bindings and approval rules; the adapter never widens them.

### Output highlights
- `persisted:true`, `rehearsal:false`
- publication record id, ledger event id, approval ref, and command id
- published object/version and effective bindings
- explicit propagation state for every target surface

### Current persistence boundary
- Only an approved `WikiPageDraft` materialized as a typed support object, with every evidence source in `ready`, may enter durable publish.
- `command_id` is the idempotency key: replay of the same request returns the original publication, while reuse with a different payload is rejected.
- The durable transaction writes the append-only governance event, immutable publication record, and one propagation row per target surface together.
- Propagation must begin as `pending`; only an explicit later update with `expected_version` may record `synced`, `failed`, or `manual_action_required`.
- Fixture-backed calls that provide only `object_ref` remain rehearsals and must return `persisted:false`, `rehearsal:true`; they are not production publication.
- Durable write/read HTTP surfaces remain admin-gated in the current slice; broader scoped write permissions are not inferred here.

## 8.3 `list_drift_alerts`
### Purpose
Read freshness and drift alerts.

### Risk class
`R0`

### Input
```json
{
  "filters": {
    "object_type": "optional-string",
    "severity": "optional-string",
    "channel": "optional-string"
  },
  "limit": 20
}
```

### Output highlights
- object refs
- drift reason
- affected audience
- suggested next action

## 8.4 `record_feedback_signal`
### Purpose
Write back consumption feedback so the system can improve knowledge objects.

### Risk class
`R1`

### Input
```json
{
  "signal_type": "answer_accepted|human_rewrite|escalated|low_rating|unsupported_answer|stale_answer",
  "object_id": "optional-string",
  "draft_id": "optional-string",
  "audience_context": {},
  "notes": "optional-string",
  "source_context_ref": "optional-string"
}
```

### Output highlights
- signal id
- whether refresh/review was queued
- linked object or draft refs

## 8.5 Governance audit read surface
### Purpose
Read durable review, approval, publish, and recovery transitions from append-only `GovernanceLedgerEvent` truth so human governance workbenches and controlled clients can trace one change.

### Risk class
`R0`

### Current HTTP surface
- `GET /api/governance/audit`
- `GET /api/governance/audit/{event_id}`
- The list accepts `phase`, `event_type`, `draft_id`, `page_id`, and `actor_id` filters plus `page` / `page_size` pagination; `page_size` is capped at `100`.
- This slice is an authenticated HTTP read surface. It does not automatically expand the four approved R0 retrieval tools exposed by runtime MCP.

### Output highlights
- `event_id` and stable `trace_ref=governance-event:{event_id}`
- `phase` (`review|approval|publish|recovery`) and the original ledger `event_type`
- `from_state` / `to_state`, actor, draft/page/object references, scope, reason, and timestamps
- event-type allowlisted `details` only; never the complete ledger payload, request fingerprints, or internal execution results
- list `total`, pagination fields, and `SurfaceObservation`

### Permission and truth boundary
- Filter in SQL inside the current user's Wiki read scope before projection: admin / `wiki:read:all` may read all rows, while `wiki:read:own_dept` sees only global and member-department truth.
- A create draft without a materialized page uses `suggested_metadata.scope_type/scope_id` for the same scope decision; a user without Wiki read permission receives an empty result.
- A missing or out-of-scope detail uses the same `404`, preventing hidden-ID disclosure.
- Data comes only from the durable governance ledger; never fall back to runtime `AuditLog`, `sample_*` fixtures, or session memory.
- `persisted:true` / `rehearsal:false` on an audit item or list proves that the ledger event itself is durable. It does not claim the knowledge object is published or propagation is complete.
- No matching in-scope events still yields a `ready` observation with `observed_count:0`; this is a truthful empty query, not `unavailable`.
## 8.6 Durable recipient notification inbox
### Purpose
Read in-app notifications produced by governance lifecycles and advance unread → read state inside the current recipient scope.

### Current HTTP surface
- `GET /api/notifications?lifecycle_state=unread|read`: paginated durable records for the current user.
- `GET /api/notifications/unread-count`: the current user's durable unread count.
- `POST /api/notifications/{notification_id}/read`: idempotently advances a record owned by the current user to `read`.
- `POST /api/notifications/read-all`: advances only the current user's unread records.

### Truth and lifecycle
- The `Notification` table is migration-owned by Alembic revision `20260809_01`; local `create_all` is only a compatibility aid for an already-existing development schema.
- `read_at IS NULL` projects to `lifecycle_state=unread`; a non-null value projects to `read`. This slice has no implicit dismiss or unread reversal.
- Every response includes `trace_ref=notification:{id}` and `persisted:true`. That proves the notification record is durable, not that external email/webhook delivery succeeded.
- External fan-out must run after the response transaction commits and reload the still-existing notification IDs in a fresh session; rolled-back records must not be sent.
- Every list / count / transition query includes `recipient_id=current_user.id`; absent and another-user records share `404`, preventing cross-user ID disclosure.
- This is a runtime HTTP inbox and does not expand Nanobot's four current R0 governed retrieval tools.



## 9. First-pass approval and permission matrix (target-state guidance, not proof of full implementation)
| Tool | Risk | Default policy |
|---|---:|---|
| `search_knowledge_objects` | R0 | auto-allow in scope |
| `read_knowledge_object` | R0 | auto-allow in scope |
| `search_support_evidence` | R0 | auto-allow in scope |
| `get_source_trace` | R0 | auto-allow in scope |
| `propose_knowledge_object` | R1 | auto-allow into draft scope |
| `update_draft_object` | R1 | auto-allow with audit |
| `request_review` | R1 | auto-allow |
| `read_review_feedback` | R0 | auto-allow in scope |
| `validate_publish_policy` | R2 | auto-allow |
| `publish_knowledge_object` | R3 | low-risk internal may pass; external defaults to approval |
| `list_drift_alerts` | R0 | auto-allow |
| `record_feedback_signal` | R1 | auto-allow with audit |

## 10. Result-size and timeout guidance
### Result size
- retrieval results should default to summaries
- large content should be re-read via ids or trace refs
- do not push full large objects into live session context by default

### Timeouts
- retrieval: 5-10s
- draft/review queue writes: 10-15s
- publish validation: 10s
- publish commit: 15-30s

## 11. Relationship to internal workflow orchestration
These tools are the stable interface between the **Nanobot session runtime** and the **Cygnus domain control plane**.

Internal workflow orchestration should not replace these tools. Instead, any future Cygnus governance orchestration should run across the same business phases, such as:
- creation workflow: `propose_knowledge_object` -> `request_review` -> `validate_publish_policy` -> `publish_knowledge_object`
- freshness workflow: `list_drift_alerts` -> `search_support_evidence` -> `update_draft_object` -> `request_review`

## 12. First-pass success criteria
This contract succeeds first as a **boundary definition**, not as proof that every write path is already product-complete.

It is successful if:
- the Nanobot–Cygnus boundary is stable
- draft, review, and publish are clearly separated
- RAG remains inside Cygnus
- high-risk publication is still expected to remain under Cygnus domain rules
- later workflow orchestration, eval, and UI work can grow on top of the same contract surface

## 13. Current implementation status (reconciled with code)
This section reconciles the current implementations in `cygnus/integrations/nanobot_tools.py` and `cygnus/integrations/governed_publish_tools.py` and explicitly separates:
- the **target contract**
- the **currently callable interface**
- the **governance semantics not yet fulfilled**

The goal is to avoid reading the target contract above as if the code were already complete.

### 13.1 Capabilities actually fulfilled today
- **Group A — Retrieval (4/4):** `search_knowledge_objects`, `read_knowledge_object`, `search_support_evidence`, and `get_source_trace` use the substrate-backed, request-scoped governed retrieval surface.
- **Group B — Draft/Review (2/4):** `propose_knowledge_object` and `request_review` still provide interface shape only; real draft/review writes are not exposed through the governed session seam.
- **Group C — Governance (3/4):** `validate_publish_policy` and `publish_knowledge_object` now use `cygnus/integrations/governed_publish_tools.py` and the durable draft, approval, audience-binding, and publication services; `list_drift_alerts` remains the existing drift read surface; `record_feedback_signal` is not wired.

### 13.2 Target interfaces not yet fulfilled
- `update_draft_object` (Group B, R1)
- `read_review_feedback` (Group B, R0)
- `record_feedback_signal` (Group C, R1)

These names are part of the target contract, but the current code does not provide a governed session adapter for them.

### 13.3 Implemented durable publish seam
- `validate_publish_policy` is a request-scoped read adapter. It reloads the current draft, typed object, approval ledger, ready sources, active audience bindings, and optional audience/version conditions; out-of-scope objects are returned as structured `not_found`.
- `publish_knowledge_object` only constructs `DurablePublishCommand` and delegates to `cygnus/publish/durable.py`; the existing governance kernel remains authoritative for admin and approval gates, source readiness, bindings, locks, idempotency, ledger, publication, and propagation.
- Success and replay preserve `persisted:true`, `rehearsal:false`, publication/ledger/approval/command IDs, and propagation records. Publish success never implies downstream sync; initial propagation remains `pending`.
- `expected_version` is checked in both the adapter and the locked durable core to prevent stale writes. Reusing a `command_id` returns the original publication; changing the payload returns a conflict.

### 13.4 Boundary reminder
This slice substantiates the durable publish boundary for approval truth without turning Cygnus into a second session loop. Nanobot still owns the session and general tool loop; Cygnus exposes typed domain adapters only. Unimplemented draft/review/feedback interfaces must not be described as ready.

### 13.5 Implemented governed-observation boundary (CYG-97, CYG-101–104, CYG-108)
`/api/command-center`, `/api/review-intake`, `/api/drift`, and `/api/source-blindness` now read from a request-scoped, permission-filtered `GovernanceReadSnapshot`; those runtime paths must not implicitly call `sample_*` fixtures.

- Every governance-risk surface returns `observation`: `ready` means complete coverage, `partial` names both covered and missing detectors, and `unavailable` means a detector is not connected—not that there is no risk. Reasons and signals are machine codes rendered through client i18n.
- Without a complete proposal bundle, Review Queue, drift, and source-blindness contexts must be empty and offer no governance command. Ordinary `WikiPageDraft` rows must not be projected into an owner, audience, surface, or risk.
- A `Source.status="error"` row remains a source-failure fact, but the CYG-108 provider now projects impact inside the same request permission scope through visible `WikiPage.source_ids`, active audience bindings, and each object's latest durable publication and propagation. `impact_state="mapped"` means at least one visible Wiki relationship exists; `unmapped` means no governed Wiki impact is mapped in the current scope, not that there is no business impact. `audience_impacts` and `propagation_impacts` may come only from those persisted records; a raw source row cannot imply an owner, risk rank, or executable command.
- `/api/recovery/overview`, `/api/recovery/window/{command_id}`, and `/api/recovery/downstream-reality-check/{command_id}` read permission-scoped persisted publication / propagation truth and return `persisted: true, rehearsal: false`; they do not fall back to rehearsal fixtures.

CYG-101–104 and CYG-108 connect ticket/rewrite pressure, release/incident drift, audience conflict, review assignment, and source impact to persisted or persistently derived providers. A surface may return `ready` only after its detectors run completely with no unresolved relationship; an unresolved audience binding still requires `partial`, and provider failures must surface as `5xx` rather than an empty array or green UI.

### 13.6 Implemented governed session seam (CYG-92–96)
Nanobot can now hand `request_ref`, optional `session_ref`, the support query, `audience_context`, and an optional prior `governance_context` to Cygnus through `POST /api/session-bridge/query`. Cygnus reloads the substrate-backed knowledge snapshot inside the request permission scope and returns one envelope containing `answer`, `source_trace`, `tool_trace`, `governance`, `continuity`, and the next portable `governance_context`.

- `GET /api/session-bridge/capabilities` now marks six fulfilled governed tools as ready: the four R0 retrieval tools plus request-scoped read-only `validate_publish_policy` and the administrator/approval-gated `publish_knowledge_object`; remaining draft/review/feedback tools stay `not_exposed`.
- Runtime MCP registers the same durable publish adapter contract. `publish_knowledge_object` is hidden from non-admins by the visibility gate, while its server-side permission check remains authoritative. It must not fall back to generic chat history, sample fixtures, or an unscoped global index.
- Audience mismatch, pending review, stale or unknown freshness, source blindness, and no match all return structured governance states. They converge to `restricted`, `escalate`, or `fallback` rather than fabricating an externally usable answer.
- Continuity re-queries Cygnus truth on every turn. An audience, object, version, trace, or freshness change invalidates the prior context; an unchanged context is only `revalidated`, and the response always carries `session_memory_used_as_truth:false`.

This seam adds no second session loop or memory store inside Cygnus. Nanobot still owns the session; Cygnus owns knowledge, retrieval, and governance decisions.
