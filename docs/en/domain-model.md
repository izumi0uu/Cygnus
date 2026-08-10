# Support Brain for SaaS — Domain Data Model

## 1. Modeling goal
This model serves product definition and knowledge governance, not physical database design. It defines:
- what the core support-knowledge objects are
- what states, relationships, evidence, and publication logic they carry
- why those objects are more product-correct than anonymous chunks

## 2. Core objects

## 2.1 Source Connector
Represents a knowledge input source.

Examples:
- Help Center
- Zendesk articles
- Intercom articles
- Confluence / Notion
- resolved tickets / chats
- release notes
- incident updates

Key attributes:
- source type
- owner
- sync status
- auth scope
- last synced at
- parsing health

## 2.2 Support Evidence
Represents normalized raw evidence that supports a knowledge object. It is not the final answer unit.

Key attributes:
- source connector
- source URL / record ID
- extracted text / metadata
- product / feature tags
- plan / region / version tags
- confidence / freshness markers

## 2.3 Answer Card
A standard customer-facing answer object.

Key attributes:
- question / intent
- canonical answer
- constraints / caveats
- audience variants
- linked evidence
- publish targets
- status

## 2.4 Troubleshooting Flow
A structured object for resolving multi-step problems.

Key attributes:
- problem statement
- prerequisites
- ordered steps
- branching conditions
- stop / escalate conditions
- linked evidence
- supported audiences

## 2.5 Policy Rule
Represents a support policy.

Key attributes:
- rule domain (refund / cancel / SLA / access / ...)
- effective conditions
- exceptions
- audience / entitlement scope
- source of authority
- human override notes

## 2.6 Known Issue Page
Represents a known issue.

Key attributes:
- issue summary
- affected product / version / region
- status
- workaround
- expected next update
- linked incident / release notes

## 2.7 Escalation Route
Defines when standard knowledge should give way to escalation.

Key attributes:
- trigger conditions
- destination team
- severity / urgency hints
- information required before escalation
- blocked domains

## 2.8 Audience Variant
Not a standalone business page but a cross-cutting variant layer attached to other knowledge objects.

Example dimensions:
- brand
- product line
- plan / tier
- region
- language
- product version
- internal vs external visibility

## 2.9 Ticket Cluster
An abstraction of repeated support patterns that becomes candidate knowledge input.

Key attributes:
- cluster summary
- recurring intent
- volume / frequency
- representative examples
- suggested object type
- acceptance status

## 2.10 Publication Record
Represents when and where a knowledge object is published.

Key attributes:
- target channel
- visibility
- audience filter
- published version
- published by
- published at

## 2.11 Feedback Signal
Represents consumption feedback flowing back into the knowledge system.

Examples:
- copilot answer accepted
- human rewrite
- escalation after suggestion
- poor rating
- unresolved conversation

Durable form (CYG-118/119):
- the accepted types are fixed to `answer_accepted`, `human_rewrite`, `escalated`, `low_rating`, `unsupported_answer`, and `stale_answer`
- `low_rating` and `stale_answer` create a durable feedback route that a bounded worker executes through `queued / running / completed / blocked / failed` (retryable failures requeue at most 3 times; missing, draft-only, or ineligible targets end `blocked` without guessing)
- a completed route materializes a durable outcome `GovernanceSignal` whose identity is `route_ref=feedback-route:<route UUID>` (the durable route row stores `outcome_signal_id`; responses project `outcome_signal_ref=governance-signal:<signal UUID>` from that ID): `low_rating` → review pressure (`ticket_pressure`, unknown freshness), `stale_answer` → suspected freshness/drift review (`drift`, stale freshness)
- execution never auto-changes content or publishes; completion proves materialization into governed review truth only

## 3. Object relationships
- Source Connector produces Support Evidence
- Support Evidence supports Answer Card / Troubleshooting Flow / Policy Rule / Known Issue Page
- Ticket Cluster can suggest creating or updating knowledge objects
- Audience Variant applies to multiple knowledge objects
- Publication Record binds objects to channels
- Feedback Signal feeds coverage / drift and update prioritization
- Escalation Route can be referenced by Answer Card or Troubleshooting Flow

## 4. Unified state machine (abstract)
Applicable to most knowledge objects:
- Draft
- In Review
- Approved
- Published
- Superseded
- Archived

State principles:
- new knowledge should not default to Published
- published objects must retain traceability and version history
- superseded objects remain historically visible

## 5. Why chunk is not the core product object
Chunks may exist in the technical substrate, but they should not be the product's core noun because they:
- do not match the support team's mental unit of work
- poorly express policy, troubleshooting, and escalation semantics
- do not naturally support audience-aware publishing
- do not align with review, ownership, and lifecycle control

So chunks may exist underneath, but the product layer should wrap them in support-native objects.

## 6. Minimum V1 object set
V1 should explicitly support:
- Answer Card
- Troubleshooting Flow
- Policy Rule
- Known Issue Page
- Escalation Route
- Audience Variant
- Source Connector
- Support Evidence
- Ticket Cluster
- Feedback Signal

## 7. Review & governance state vocabulary
The following are controlled state vocabularies attached to review items, evidence, and publish actions. They are not standalone objects but first-class value types referenced across modules, and are already settled in the implementation (see `cygnus/review`, `cygnus/evidence`, `cygnus/publish`).

### 7.1 Review Risk Type — why a review item represents a system-level risk
Used to re-rank the review entry by governance risk rather than creation time:
- `audience_mismatch` — audience / version mismatch
- `drift` — knowledge drift triggered by a release / incident
- `source_blindness` — "governance blindness" caused by source failure, not a mere sync error
- `ticket_pressure` — review pressure from repeated tickets / repeated human rewrites
- `policy_conflict` — policy conflict across audiences
- `owner_gap` — missing owner

Durable consumption-feedback routes materialize into these risk types (CYG-118/119): `low_rating` → `ticket_pressure` with unknown freshness, `stale_answer` → `drift` with stale freshness.

### 7.2 Owner State
- `assigned` / `unassigned` / `escalated`

### 7.3 Evidence Freshness
- `fresh` / `stale` / `unknown`

### 7.4 Evidence Sufficiency
- `insufficient` / `partial` / `sufficient`

### 7.5 Evidence Source Type
- `help_center` / `internal_sop` / `resolved_ticket` / `release_note` / `incident_update` / `chat_transcript` / `consumption_feedback`
