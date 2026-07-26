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

### Input
```json
{
  "draft_id": "string",
  "target_channel": "internal_copilot|internal_mcp|external_help_center|future_customer_answer_engine",
  "approval_ref": "optional-string"
}
```

### Permission rule
- low-risk internal publication may be auto-allowed by policy
- external publication should default to `approval_required`
- policy-rule or regulated-topic publication should require stricter approval

### Output highlights
- publication record id
- published object id / version
- effective visibility
- audit trace ref

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
This section reconciles the current implementation in `cygnus/integrations/nanobot_tools.py` and explicitly separates:
- the **target contract**
- the **currently callable interface**
- the **governance semantics not yet fulfilled**

The goal is to avoid reading the target contract above as if the code were already complete.

### 13.1 Capabilities actually fulfilled today
- **Group A — Retrieval (4/4):** `search_knowledge_objects` / `read_knowledge_object` / `search_support_evidence` / `get_source_trace`, wired to real indexes (`object_index` / `evidence_index` / `source_trace`). This is the part closest to real product semantics today.
- **Group B — Draft/Review (2/4):** only `propose_knowledge_object` and `request_review` are callable, and both are currently **placeholder stubs** (correct return shape, but no persistence and no queue insertion). So they fulfill interface shape, not durable governance-state changes.
- **Group C — Governance (3/4):** `validate_publish_policy` and `publish_knowledge_object` are callable but still **placeholder stubs** (approval = an internal/external check on the `target_channel` string); `list_drift_alerts` is wired to the real drift governance surface.

### 13.2 Target interfaces not yet fulfilled
- `update_draft_object` (Group B, R1)
- `read_review_feedback` (Group B, R0)
- `record_feedback_signal` (Group C, R1)

These names are already part of the target contract, but the current code does not yet implement them.

### 13.3 Key gap: the governance kernel and the tool contract are still disconnected
Capabilities implemented in the Cygnus domain layer but **not yet exposed as tools**:
- blast-radius preview (`cygnus/publish/preview.py`)
- publish governance actions (`cygnus/publish/actions.py`: `publish` / `restrict` / `split_variant` / `hold_external` / `republish_internal_only`)
- propagation status (`cygnus/publish/propagation.py`: `synced` / `pending` / `failed` / `manual_action_required`)

The current `publish_knowledge_object` write path does **not** call this governance kernel.
That means the externally callable publish contract does not yet equal the real blast-radius / propagation / governance-action path.

### 13.4 Boundary reminder
§2.1 requires approval truth to live in Cygnus, but approval is currently decided only by the `target_channel` string, with **no real approval-record store** yet. Until that store exists, approval truth is not yet substantiated by code.

So the accurate current statement is not “Cygnus has finished approval governance,” but rather:
- the contract says approval should belong to Cygnus
- the code has not yet fully substantiated that governance truth
