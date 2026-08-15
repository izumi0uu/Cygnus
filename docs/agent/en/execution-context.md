# Support Brain for SaaS — Agent Execution Context

## 1. Purpose
This file gives downstream agents a stable, compact, execution-ready product context so future implementation or expansion does not drift away from the intended product.

## 2. Source-of-truth priority
1. `docs/zh/prd.md` / `docs/en/prd.md`
2. `docs/zh/domain-model.md` / `docs/en/domain-model.md`
3. `docs/zh/workflows.md` / `docs/en/workflows.md`
4. `docs/zh/information-architecture.md` / `docs/en/information-architecture.md`
5. `docs/zh/architecture.md` / `docs/en/architecture.md`
6. `docs/zh/tool-contracts.md` / `docs/en/tool-contracts.md`
7. `docs/zh/loop-boundaries.md` / `docs/en/loop-boundaries.md`
8. `docs/zh/open-questions.md` / `docs/en/open-questions.md`
9. `docs/zh/agent-harness.md` / `docs/en/agent-harness.md`
10. `docs/zh/eval-plan.md` / `docs/en/eval-plan.md`
11. `docs/zh/rag-strategy.md` / `docs/en/rag-strategy.md`
12. `docs/zh/arkon-full-port-migration-plan.md` / `docs/en/arkon-full-port-migration-plan.md`
13. `.omx/plans/ralplan-cygnus-arkon-full-port-baseline-consensus.md`

If files conflict:
- product positioning in the PRD wins
- domain naming in the domain model constrains object vocabulary
- lifecycle logic in workflows constrains system behavior
- unresolved items listed in open questions must not be silently treated as decided
- harness / eval docs are implementation guidance and must not override the higher-order product and boundary docs
- the full-port migration plan constrains the current engineering order and must not silently revert into selective extraction truth

## 3. Core positioning invariants
Any future implementation, expansion, page design, or technical proposal must preserve:
- this is a **support knowledge operating system**
- this is an **Arkon-enhanced** support product, not an Arkon-independent reinvention
- it is **not** a generic RAG product
- it is **not** another customer-facing support bot
- phase one prioritizes internal copilot + knowledge compiler
- review / publish / traceability are central, not optional add-ons
- Nanobot is the only general-purpose session loop
- Cygnus internal workflow orchestration belongs only in selected governance workflows, not as a second roaming runtime
- LangGraph is not part of the current Cygnus mainline; any residue should be treated only as transitive dependency fallout or archived planning context

## 4. Current migration discipline
Cygnus is not currently designing a net-new system from scratch. It is executing:

1. **P0 — Migration Manifest & Boundary Freeze**
2. **P1 — Arkon full-port source parity import**
3. **P2 — repair / runability recovery**
4. **P2.5 — Arkon internalization / upstream cutover**
5. **P3 — Cygnus support verticalization**
6. **P4 — optional product-shell parity**

Agents must preserve these rules:
- do not misread `CYG-6 ~ CYG-17` as the current first engineering entry point
- the current engineering mainline is `CYG-23+`
- `CYG-18 ~ CYG-22` are bootstrap history, not current migration truth
- do not merge import parity, runability recovered, internalization completed, and verticalization completed into one fuzzy done-state
- preserve upstream Arkon topology first; renaming/refactor comes later and is not the default action during import
- if the goal is to fully absorb Arkon and eventually delete the separate upstream codebase, agents must enter a dedicated P2.5 internalization lane rather than misreporting that work as P1 import behavior

### 4.1 Status-language contract
Downstream agents must follow this contract in Jira comments, handoffs, logs, and completion notes:

- **P1** may only be described as mirrored/imported/parity-established, never as already runnable
- **P2** may only be described as wiring restored / boot regained / runability recovered, never as product-complete
- **P2.5** may only be described as `internalized substrate` / `upstream cutover started` / `Cygnus-owned runtime identity established`, never as support verticalization complete
- **P3** is the first lane allowed to claim support verticalization implemented / governance surface established
- without a phase qualifier, agents should avoid using a vague standalone “done” to describe migration state
- parent-lane tickets like `CYG-23 ~ CYG-25` must not be reported as complete just because one child ticket closed
- the new internalization parent lane must not be misreported as “shell parity decided” or “P3 already started”

### 4.1.1 Governed observation truth
- Governance reads must query inside the permission scope before projection; runtime results must not be filled from `sample_*` fixtures or session memory.
- `ready`, `partial`, and `unavailable` describe detector coverage, not swallowed failures. Empty arrays under `partial` or `unavailable` must never be summarized as “no risk.”
- A `SourceFailureObservation` remains a source-failure fact. CYG-108 permits `impact_state="mapped|unmapped"`, `audience_impacts`, and `propagation_impacts` only when projected from permission-visible `WikiPage.source_ids`, active audience bindings, and the latest durable publication/propagation. `unmapped` means no governed Wiki impact is mapped in the current permission scope—not that there is no business impact—and a raw source row still cannot imply a risk, owner, or executable command.
- Sources Evidence must render the returned failure facts, complete-risk contexts, and durable mapping fields directly. It must not calculate watched or healthy counts by subtracting unrelated collections, or treat `unmapped` or an incomplete empty result as healthy.
- `/api/recovery/overview`, `/api/recovery/window/{command_id}`, and the downstream reality check read permission-scoped persisted publication / propagation truth and return `persisted:true, rehearsal:false`; missing durable recovery truth must remain unavailable rather than falling back to fixtures.
- `persisted:true` on a publish response or publish projection is valid only when an approved typed `WikiPageDraft`, ready evidence, explicit channels, and durable IDs commit in one transaction; the fixture `object_ref` path must remain `persisted:false`, `rehearsal:true`.
- `persisted:true` on a governance audit record proves only that the append-only ledger event committed; it does not claim publication or completed propagation. Audit reads must filter in SQL inside Wiki read scope and return the same `404` for missing and hidden events.
- `/api/notifications` is a durable recipient-scoped inbox: `read_at` projects only to `unread|read`, and every read/transition query is SQL-scoped to the current recipient; the frontend must not derive notifications from command-center fixtures or localStorage.
- Notification external fan-out may reload only committed IDs; a staged record from a rolled-back transaction must not be sent.

- New propagation is always `pending`; a successful publish request never implies downstream `synced`, which requires an explicit version-checked update.


### 4.1.2 Governed session seam
- `/api/session-bridge/query` must reload substrate truth inside the current user permission scope; a prior `governance_context` is only continuity input and never answer truth.
- `session_memory_used_as_truth` must remain `false`. An audience/object/version/trace/freshness change returns `invalidated`; an unchanged context may return `revalidated` only after retrieval runs again.
- Runtime MCP and session capabilities share exactly twelve `ready` adapter definitions with `not_exposed:[]`: `search_knowledge_objects`, `read_knowledge_object`, `search_support_evidence`, `get_source_trace`, `list_drift_alerts`, `propose_knowledge_object`, `update_draft_object`, `request_review`, `read_review_feedback`, `record_feedback_signal`, `validate_publish_policy`, and `publish_knowledge_object`.
- `list_drift_alerts` reloads scoped durable signal truth in the request DB session. Authenticated R1 `record_feedback_signal` accepts only the six fixed feedback types and requires a nonblank `command_id` of at most 220 characters. `GovernanceFeedbackSignal.command_id` is globally unique and has a 64-character `request_fingerprint` over normalized payload and authenticated actor; exact replay returns the existing signal/route without writes, reuse with a changed normalized payload or actor returns structured `conflict` without writes, and a new command ID remains distinct feedback. Exact replay preserves the same signal/route identity and projects the route's current durable lifecycle — never a frozen byte-for-byte snapshot — so a later replay may truthfully show `completed`, `blocked`, or `failed` without creating duplicate truth.
- A new feedback call stages the original `GovernanceFeedbackSignal`, its mapped `GovernanceFeedbackRoute` when applicable, and exactly one runtime mutation `AuditLog` in the same caller-owned transaction; the persistence owner only flushes, and exact replay creates no duplicate audit. Feedback preserves `actor_id`, `page_id`, and `draft_id` as `RESTRICT` foreign-key links; `object_id` and `source_context_ref` are stored context, and the source context is not a `Source` foreign key. A provided `object_id` must be the canonical immutable `ko-page-<WikiPage UUID>` returned by governed retrieval: resolution parses the UUID, applies the actor's SQL read scope to `WikiPage.id`, and never falls back to a mutable slug. Draft resolution is also SQL-scoped; hidden or absent object/draft refs, and noncanonical object refs, share `not_found`, while conflicting refs return non-disclosing `conflict` without writes. Every state-changing adapter re-checks identity, scope, and resource authority server-side.
- `GovernanceFeedbackRoute` is the only durable queue truth, unique on `(feedback_signal_id, route_kind)`, with `route_kind` `review|refresh` and `lifecycle_state` advancing through `queued / running / completed / blocked / failed`. The mapping is frozen: `low_rating` → `review`, `stale_answer` → `refresh`, and all other accepted types → `recorded_only` with no route. `low_rating` materializes as review pressure (`ticket_pressure`, unknown freshness); `stale_answer` materializes as suspected freshness/drift review (`drift`, stale freshness).
- Routed responses expose `route_id`, `route_ref=feedback-route:{uuid}`, `route_kind`, `route_state` across the lifecycle (`queued|running|completed|blocked|failed`), and `routing_state` as `<route_kind>_<route_state>` (`review_queued|review_running|review_completed|review_blocked|review_failed` or the `refresh_*` equivalents); exactly one of `review_queued` and `refresh_queued` is true only while the route state is `queued`, and both queue flags are false for `running`/`completed`/`blocked`/`failed`. Non-routed responses expose null route fields, `routing_state:"recorded_only"`, and both queue flags false.
- CYG-119's bounded worker claims and executes routes through `queued / running / completed / blocked / failed`: up to `limit=25` routes per claim under a 60s lease, retryable failures requeue at most 3 attempts with a 30s base retry, and route rows carry `attempt_count`, `next_attempt_at`, `lease_token`, `lease_expires_at`, `outcome_signal_id`, `terminal_reason`, `last_error`, and `completed_at`. Every mutation only flushes and the caller commits; the worker commits the claim, then each execution or failure in its own transaction. A completed route materializes a durable outcome `GovernanceSignal` whose identity is `route_ref=feedback-route:<route UUID>` on the `feedback`/`review_queue` surfaces; the durable route row stores `outcome_signal_id`, from which responses project `outcome_signal_ref=governance-signal:<signal UUID>` (a response projection, not a stored column). Deriving these outcomes is worker-owned: feedback-derived types cannot be created through the admin write endpoint, while the admin read endpoint can observe worker-created rows. Route execution does not log raw `source_context` or `notes`. Missing, draft-only, or ineligible targets end `blocked` without guessing; execution never auto-changes content or publishes. Completion proves materialization into governed review truth only — not reviewer action, draft creation, publication, downstream propagation, KPI improvement, or business impact.
- CYG-120 requires `GET /api/governance/feedback-routes` and `/{route_id}` to constrain routes by Wiki page/draft read scope in SQL before summaries or drilldowns; hidden and absent IDs share `404`. Reads must not expose `last_error`, feedback `notes`, or `source_context_ref`. Worker events allow only event, route ID/kind, transition, attempt, duration, outcome ref, stable terminal reason, and exception class—never exception text or customer/source payload. Operational completion/outcome events are not reviewer action, publication, propagation, or a business KPI.
- CYG-122's `resolved-ticket-export/v1` accepts already-sanitized CSV/JSONL only, and `source_ref` must identify an immutable snapshot. The importer validates the whole payload before deterministic audience-aware clustering; candidates below threshold must not write review truth, while qualifying candidates persist structured evidence refs only through the existing `GovernanceSignal` plus review-assignment owner. Exact replay preserves the same signal, changed facts under the same `source_ref` must conflict, and a successful import never implies draft creation, completed review, or publication.
- CYG-125 requires every resolved-ticket import to bind an explicit existing `Source` UUID in `ready` state; `source_ref` remains immutable export identity, while `source_id` is the durable Source Connector/evidence link. Qualifying signals must persist that ID and promotion/approval must carry it unchanged into `WikiPage.source_ids`; the same binding replays exactly, while changing the Source under the same export truth conflicts. Never auto-create the Source or bypass durable publish's ready-evidence and active audience-binding gates.
- No match, pending review, audience mismatch, stale/unknown evidence, and source blindness must return structured `fallback`, `restricted`, or `escalate` states rather than a fabricated answer.

### 4.1.3 Engineering execution control
- Jira is the only delivery backlog and workflow-status source of truth; CYG issues own priority, owner, blockers, progress, and completion.
- Code-changing or multi-session delivery must bind to one CYG issue before implementation; a one-turn read-only investigation may remain untracked.
- Trellis defaults to specs-only mode: `.trellis/spec/`, `trellis-before-dev`, `trellis-check`, and `trellis-update-spec` remain available, but agents must not create a second task lifecycle by default.
- Complex or high-risk work may produce a neutral local plan keyed to the CYG issue; the plan constrains implementation but owns no status and cannot override Jira.
- Completion evidence comes from Git, tests, CI, smoke checks, and review; write concise evidence back before transitioning the Jira issue.

## 4.2 Package owner contract
Current package interpretation must remain consistent:

- `cygnus/runtime/*` = imported runtime/app shell/reference topology
  - source execution-state transitions and source-ingest orchestration may live under `cygnus.runtime`
- `cygnus/substrate/*` = Cygnus-owned substrate contracts
  - `source_outline` / `source_images` / `source_text` now all belong to the substrate owner boundary
  - agents must not push these source-compilation primitives back into `cygnus.runtime.services`
- `cygnus/domain/*` = support-domain contracts / object vocabulary
- `cygnus/evidence/*` = evidence normalization and record layer
- `cygnus/retrieval/*` = object/evidence retrieval and source-trace query layer
  - semantic embedding persistence also belongs to this owner boundary
- `cygnus/review/*` / `cygnus/publish/*` / `cygnus/recovery/*` = governance control-plane modules
- `cygnus/integrations/*` = external/session-facing integration adapters
- `cygnus/workflows/*` = workflow composition layer, not generic runtime shell
- `cygnus/api/*` = removed legacy package; no Python modules should remain

Current import policy must also remain consistent:
- `cygnus.runtime.main` is the canonical app owner
- `cygnus.api.*` must not become the default internal entrypoint
- `cygnus.api.auth` / `cygnus.api.config` / `cygnus.api.governance_router` / `cygnus.api.app` must not regain internal callers
- agents must not reintroduce the old `app.*` namespace

Current deletion-readiness gate must also remain consistent:
- before `scripts/upstream_cutover_gate.py` passes, do not claim the repo is ready to safely delete the separate Arkon codebase
- agents must not describe cutover as shell parity or P3 support verticalization
- only after the gate passes may Jira / handoff / completion notes claim deletion-readiness is satisfied
- if a standalone external checkout still exists, agents should preserve local ahead history, dirty worktree state, and untracked files with `scripts/external_checkout_preserve.py` before any destructive deletion proposal
- `scripts/external_checkout_audit.py --fail-if-found` remains the physical-deletion proof, not merely the preserve step

Execution constraints:
- do not treat `runtime` as the only naming truth for the whole product backend
- do not default new governance/knowledge capabilities into `cygnus/api/*`
- only architecture-convergence stories may further reorganize `runtime` or split it into other long-term structures
- during any further package convergence, preserve ownership interpretation and import policy first

## 5. Key vocabulary
- **Answer Card** — standard answer object
- **Troubleshooting Flow** — troubleshooting object
- **Policy Rule** — support policy object
- **Known Issue Page** — known-issue object
- **Escalation Route** — escalation-path object
- **Audience Variant** — audience-difference layer
- **Support Evidence** — supporting evidence
- **Ticket Cluster** — repeated-ticket pattern input

Governance-state vocabulary (**Review Risk Type** / **Owner State** / **Propagation Status**, etc.): see `domain-model.md` §7 and `workflows.md`; likewise do not weaken these into generic nouns.

Unless explicitly requested by a human, do not rename these objects into weaker nouns like generic article, chunk, or snippet.

## 6. Documentation maintenance rules
- Chinese and English files should stay structurally aligned
- small wording differences are acceptable; boundary drift is not
- when adding docs, first decide whether they are human-facing or agent-facing
- if new content is still a hypothesis, write it into open questions before promoting it into the PRD

## 7. Expansion constraints
### Safe expansion directions
- MVP plan
- deeper permission model
- MCP tool surface
- lightweight technical architecture sketch
- dashboard metrics model
- agent harness contract
- eval plan and fixture design
- RAG strategy and retrieval-policy design

### Do not expand by default
- GTM / pricing
- full customer-bot conversation design
- deep infra design
- detailed action-layer flows

## 8. Heuristics for future implementation
A proposal is more likely correct if it:
- strengthens knowledge objects rather than search fragments
- strengthens human review rather than bypassing it
- shortens the path to traceability
- makes audience-aware publishing more explicit
- makes ticket-to-knowledge part of the core loop
- grounds Cygnus governance surfaces in Arkon substrate truth rather than page-only narrative

A proposal is more likely wrong if it:
- moves the product center into a chat window
- degrades the object layer into paragraph retrieval
- bypasses review and directly promotes new knowledge
- pushes internal/external or audience differences into vague post-processing
- treats full-port migration as immediate justification for a total support-native rewrite

## 9. Handoff guidance
If the project moves into planning or implementation mode, the recommended order is:
1. plan from these docs
2. confirm whether the current lane is P1, P2, P2.5, or P3
3. define the MVP scope and milestones
4. only then move into architecture and development
