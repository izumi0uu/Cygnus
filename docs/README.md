# Support Brain for SaaS — Documentation Index

This repository contains the first-pass product documentation package for **Support Brain for SaaS**, an **Arkon-enhanced support knowledge operating system**.

## Positioning
Support Brain is **not** another customer-facing support bot and **not** a generic RAG knowledge base. It is a **knowledge control layer** that compiles, reviews, publishes, and traces support knowledge for both human agents and AI agents.

## Relationship to Arkon
This repo is not documenting a product unrelated to Arkon.

The intended relationship is:
- **Arkon** provides the foundational LLM-wiki / knowledge-compilation / RAG substrate
- **Support Brain for SaaS** is the support-domain product enhancement built on top of that substrate
- **Cygnus** is the repository where that Arkon-enhanced support product is being defined

Current engineering strategy (status as of 2026-08):
- P1/P2/P2.5—the Arkon full-port baseline, runability recovery, and post-P2 internalization/upstream-cutover lane—and the first support-verticalization waves are complete (CYG-6–17, CYG-23, CYG-24, CYG-69–91)
- CYG-92–96 implements a request-scoped governed Nanobot ↔ Cygnus session seam that reloads and revalidates Cygnus truth on every turn without treating session memory as knowledge truth
- CYG-98–105 plus CYG-108/109/111/112/113/114/115/116/117/118/119 provide durable ledger/audit, notifications, ticket/rewrite pressure, release/incident drift, audience bindings/conflicts, review assignments, source impact, publish/propagation, golden-path proof, durable publish and draft/review tools, scoped durable drift alerts, replay-safe consumption feedback with frozen review/refresh route intent, bounded feedback-route execution under worker claim/recovery, truthful source-evidence observation presentation, and a deterministic production-shaped domain eval gate; CYG-118/119 routes execute through `queued/running/completed/blocked/failed` with retryable failures returning to `queued` (at most 3 attempts, 60s lease, 30s base retry) and materialize durable outcome governance signals whose identity is `route_ref=feedback-route:<route UUID>` (the durable route row stores `outcome_signal_id`; responses project `outcome_signal_ref=governance-signal:<signal UUID>` from it) into governed review truth without auto-changing content or publishing; completion proves materialization into governed review truth only, not reviewer action, draft creation, publication, downstream propagation, KPI improvement, or business impact
- CYG-122 adds the bounded resolved-ticket export pilot: admin-only `POST /api/governance/ticket-imports` accepts the shared `resolved-ticket-export/v1` CSV/JSONL contract, validates the whole immutable `source_ref` snapshot before writes, forms deterministic audience-aware candidates, and persists only threshold-qualified clusters as replay-safe governance signals with structured ticket evidence and review assignments. Non-qualifying candidates remain observable in the response; the path never creates, approves, or publishes knowledge automatically. Production-shaped fixtures and local smoke prove the executable contract, not real-data ROI or business impact.
- CYG-123 adds the explicit reviewer-controlled conversion step after the pilot import: admin-only `POST /api/governance-signals/{signal_ref}/commands/promote-draft` locks an eligible active ticket-pressure signal, validates review-assignment version and structured ticket evidence, and atomically creates a durable `WikiPageDraft(status=draft)`, append-only governance event, and replay receipt. Exact command replay returns the same result; payload drift conflicts. A successful receipt means persisted only—not submitted for review, approved, or published.
*|- CYG-125 closes the durable evidence seam for that loop: ticket import now requires an explicit existing `Source(status=ready)` UUID, persists it on every qualifying signal, and carries it through reviewer-controlled promotion and approval into `WikiPage.source_ids`. Exact replay preserves the binding; changing the Source under the same immutable export truth conflicts. This makes the existing approval-backed durable publish gate reachable without weakening evidence or audience-binding policy.
- CYG-130/CYG-128 execution reliability makes worker dispatch and source deletion crash/restart-safe: every source pipeline cycle carries a monotonic `dispatch_generation`; each worker handoff (ingest/post-extraction/map-reduce/refine/plan-regeneration) is recorded as a `SourceDispatchExecution` outbox row with a deterministic ARQ job id, lease token, attempt budget, and a recovery index; the worker sweep re-enqueues pending/expired-lease handoffs, fences superseded generations, and surfaces structured enqueue failures. Source deletion is database-led: `DELETE /sources/{id}` commits a tombstone (`sources.delete_requested_at`) plus a `SourceDeletion` cleanup intent before any object-storage removal; the sweeper deletes the storage prefix idempotently, then detaches wiki pages and removes the source row in one transaction, keeping partial object failures visible (`GET /sources/deletions`) and retrying with a backoff budget.
- CYG-138/CYG-143 close the durable governed-propagation delivery seam. Publish stages one actor-bound outbound delivery per target surface with frozen approved publication/object/binding/source truth, deterministic identity, desired digest, expected versions, bounded attempts, and correlation metadata; the worker sends only to approved HTTPS origins and only a signed acknowledgment can set `synced`. Production now includes a private Cygnus-owned ASGI delivery consumer behind the exact TLS ingress route: it verifies the existing HMAC request, rejects non-canonical or identity-drifted replay, persists metadata-only idempotency receipts in PostgreSQL, and returns the signed canonical acknowledgment. Deploy, rollback, restart, backup/restore, and isolated certification include the consumer. The fake consumer remains a unit-test harness; a real two-turn client session remains separate product evidence.
- the shared session/MCP contract marks twelve governed tools `ready`: four retrieval tools; `list_drift_alerts`; `propose_knowledge_object`, `update_draft_object`, `request_review`, and `read_review_feedback`; `record_feedback_signal`; `validate_publish_policy`; and `publish_knowledge_object`; capabilities reports `not_exposed:[]`
- keep product-shell parity as a deferred non-roadmap lane by default
- classify `auth / admin / wiki` shell candidates before any shell-parity implementation, and keep non-support pages isolated unless they directly unblock support verticalization

### Engineering execution control
- Jira is the sole delivery backlog and workflow-status source of truth for Cygnus.
- Trellis is used in specs-only mode by default: project specs and pre-development/check guidance remain useful, but Jira issues are not mirrored into Trellis task lifecycles.
- Complex work may produce a neutral local plan keyed to its CYG issue; the plan has no independent status authority.
- Git, tests, CI, smoke checks, and review provide implementation evidence, which is written back to Jira before completion.

## Documentation Tracks

### Human-facing docs

#### 中文
- [`docs/zh/prd.md`](./zh/prd.md) — 产品定义 / PRD
- [`docs/zh/information-architecture.md`](./zh/information-architecture.md) — 信息架构 / 页面结构
- [`docs/zh/domain-model.md`](./zh/domain-model.md) — 领域数据模型
- [`docs/zh/workflows.md`](./zh/workflows.md) — 核心工作流 / 生命周期
- [`docs/zh/open-questions.md`](./zh/open-questions.md) — 开放问题与待验证假设
- [`docs/zh/architecture.md`](./zh/architecture.md) — 轻量架构草图
- [`docs/zh/tool-contracts.md`](./zh/tool-contracts.md) — Tool Contracts（Nanobot ↔ Cygnus）
- [`docs/zh/loop-boundaries.md`](./zh/loop-boundaries.md) — Loop Boundaries
- [`docs/zh/agent-harness.md`](./zh/agent-harness.md) — Agent Harness（Cygnus 如何借 agent harness，而不漂成 generic agent framework）
- [`docs/zh/eval-plan.md`](./zh/eval-plan.md) — Eval Plan（CYG-117 确定性领域门禁、评估层、回归门禁与业务指标边界）
- [`docs/zh/rag-strategy.md`](./zh/rag-strategy.md) — RAG Strategy（Arkon-style LLM wiki retrieval substrate 如何服务 support knowledge objects）
- [`docs/zh/product-story.md`](./zh/product-story.md) — 完整产品 Story
- [`docs/zh/frontend-story.md`](./zh/frontend-story.md) — 前端行为 Story
- [`docs/zh/visual-language.md`](./zh/visual-language.md) — 视觉语言方案
- [`docs/zh/interaction-principles.md`](./zh/interaction-principles.md) — 交互原则
- [`docs/zh/page-story-map.md`](./zh/page-story-map.md) — 页面级 Story Map
- [`docs/zh/screen-spec.md`](./zh/screen-spec.md) — Screen Spec
- [`docs/zh/wireframe-architecture.md`](./zh/wireframe-architecture.md) — Wireframe Architecture
- [`docs/zh/state-matrix.md`](./zh/state-matrix.md) — State Matrix
- [`docs/zh/command-flows.md`](./zh/command-flows.md) — Command Flows
- [`docs/zh/component-taxonomy.md`](./zh/component-taxonomy.md) — Component Taxonomy
- [`docs/zh/critical-surface-blueprints.md`](./zh/critical-surface-blueprints.md) — Critical Surface Blueprints
- [`docs/zh/core-wireframe-variants.md`](./zh/core-wireframe-variants.md) — Core Wireframe Variants (3 divergent directions)
- [`docs/zh/high-density-hero-blueprints.md`](./zh/high-density-hero-blueprints.md) — 高密首页 / 协调页 Hero 蓝图（推荐混合方向落地）
- [`docs/zh/jira-governance-migration-stories.md`](./zh/jira-governance-migration-stories.md) — Jira 治理迁移 Story Pack
- [`docs/zh/jira-project-configuration-plan.md`](./zh/jira-project-configuration-plan.md) — Jira 项目配置反向设计方案
- [`docs/zh/story-to-substrate-mapping.md`](./zh/story-to-substrate-mapping.md) — Story 到 Substrate 的映射计划
- [`docs/zh/arkon-full-port-migration-plan.md`](./zh/arkon-full-port-migration-plan.md) — Arkon 全量迁移基线计划
- [`docs/zh/arkon-internalization-plan.md`](./zh/arkon-internalization-plan.md) — Arkon 内化与上游切断计划
- [`docs/zh/backup-restore-runbook.md`](./zh/backup-restore-runbook.md) — 备份 / 恢复 / 演练 Runbook（CYG-132 运维恢复）
- [`docs/zh/cygnus-telemetry-runbook.md`](./zh/cygnus-telemetry-runbook.md) — 遥测 / 告警 Runbook（CYG-142 可观测性）

#### English
- [`docs/en/prd.md`](./en/prd.md) — Product Definition / PRD
- [`docs/en/information-architecture.md`](./en/information-architecture.md) — Information Architecture / Page Structure
- [`docs/en/domain-model.md`](./en/domain-model.md) — Domain Data Model
- [`docs/en/workflows.md`](./en/workflows.md) — Core Workflows / Lifecycle
- [`docs/en/open-questions.md`](./en/open-questions.md) — Open Questions & Validation Hypotheses
- [`docs/en/architecture.md`](./en/architecture.md) — Lightweight Architecture Sketch
- [`docs/en/tool-contracts.md`](./en/tool-contracts.md) — Tool Contracts (Nanobot ↔ Cygnus)
- [`docs/en/loop-boundaries.md`](./en/loop-boundaries.md) — Loop Boundaries
- [`docs/en/agent-harness.md`](./en/agent-harness.md) — Agent Harness (how Cygnus borrows harness discipline without becoming a generic agent framework)
- [`docs/en/eval-plan.md`](./en/eval-plan.md) — Eval Plan (CYG-117 deterministic domain gate, evaluation layers, regression gates, and business-metric boundaries)
- [`docs/en/rag-strategy.md`](./en/rag-strategy.md) — RAG Strategy (how the Arkon-style LLM-wiki retrieval substrate serves support knowledge objects)
- [`docs/en/product-story.md`](./en/product-story.md) — Complete Product Story
- [`docs/en/frontend-story.md`](./en/frontend-story.md) — Frontend Behavior Story
- [`docs/en/visual-language.md`](./en/visual-language.md) — Visual Language
- [`docs/en/interaction-principles.md`](./en/interaction-principles.md) — Interaction Principles
- [`docs/en/page-story-map.md`](./en/page-story-map.md) — Page-Level Story Map
- [`docs/en/screen-spec.md`](./en/screen-spec.md) — Screen Spec
- [`docs/en/wireframe-architecture.md`](./en/wireframe-architecture.md) — Wireframe Architecture
- [`docs/en/state-matrix.md`](./en/state-matrix.md) — State Matrix
- [`docs/en/command-flows.md`](./en/command-flows.md) — Command Flows
- [`docs/en/component-taxonomy.md`](./en/component-taxonomy.md) — Component Taxonomy
- [`docs/en/critical-surface-blueprints.md`](./en/critical-surface-blueprints.md) — Critical Surface Blueprints
- [`docs/en/core-wireframe-variants.md`](./en/core-wireframe-variants.md) — Core Wireframe Variants (3 divergent directions)
- [`docs/en/high-density-hero-blueprints.md`](./en/high-density-hero-blueprints.md) — High-density homepage / coordination hero blueprints for the recommended mixed direction
- [`docs/en/jira-governance-migration-stories.md`](./en/jira-governance-migration-stories.md) — Jira governance migration story pack
- [`docs/en/jira-project-configuration-plan.md`](./en/jira-project-configuration-plan.md) — Jira project configuration reverse plan
- [`docs/en/story-to-substrate-mapping.md`](./en/story-to-substrate-mapping.md) — Story-to-substrate mapping plan
- [`docs/en/arkon-full-port-migration-plan.md`](./en/arkon-full-port-migration-plan.md) — Arkon full-port baseline migration plan
- [`docs/en/arkon-internalization-plan.md`](./en/arkon-internalization-plan.md) — Arkon internalization & upstream cutover plan
- [`docs/en/backup-restore-runbook.md`](./en/backup-restore-runbook.md) — Backup / restore / recovery drill runbook (CYG-132 operator recovery)
- [`docs/en/cygnus-telemetry-runbook.md`](./en/cygnus-telemetry-runbook.md) — Telemetry / alerting runbook (CYG-142 observability)

### Agent-facing docs

#### 中文
- [`docs/agent/zh/execution-context.md`](./agent/zh/execution-context.md) — Agent 执行上下文

#### English
- [`docs/agent/en/execution-context.md`](./agent/en/execution-context.md) — Agent Execution Context

## Documentation Reading Note
The docs below are **implementation-guidance docs**, not product-repositioning docs:
- `agent-harness.md`
- `eval-plan.md`
- `rag-strategy.md`
- `wireframe-architecture.md`
- `state-matrix.md`
- `command-flows.md`
- `component-taxonomy.md`
- `critical-surface-blueprints.md`
- `core-wireframe-variants.md`
- `high-density-hero-blueprints.md`

Rendered Excalidraw artifacts for the three variant directions and the two high-density hero blueprints live under `docs/diagrams/`.

Recommended mixed-direction hero renders:
- `docs/diagrams/cygnus-command-center-hero-briefing-atlas.png`
- `docs/diagrams/cygnus-coordination-hero-battle-corridor.png`

They should refine implementation choices while remaining subordinate to:
- PRD
- architecture
- tool contracts
- loop boundaries
- open questions

## Current Boundary
This package is intentionally focused on:
- product definition alignment
- support-native knowledge objects
- review + publish + audience-aware distribution
- governance command framing (risk-ranked review, blast-radius publish, propagation + recovery)
- human/AI shared source of truth
- request-scoped governed reads whose explicit observation coverage and scoped source-impact facts prevent empty arrays, `unmapped` sources, or client-side arithmetic from being interpreted as healthy truth
- a governed Nanobot ↔ Cygnus session seam that revalidates substrate truth on every turn and never treats session memory as knowledge truth
- a governed Nanobot ↔ Cygnus draft/review and publish seam for the durable draft/review lifecycle, policy validation, and approval-backed publication, with explicit versioning, idempotency, and propagation state
- an authenticated R1 consumption-feedback seam with required `command_id`, exact replay/conflict semantics, and one caller transaction for `GovernanceFeedbackSignal`, a mapped `GovernanceFeedbackRoute` when applicable (the only queue truth), and `AuditLog`; CYG-118 froze `low_rating` → review and `stale_answer` → refresh as durable queued intent, and CYG-119 adds bounded worker claim/recovery executing routes through `queued / running / completed / blocked / failed` (retryable failures return to `queued`, at most 3 attempts, 60s lease, 30s base retry) into durable outcome governance signals whose identity is `route_ref=feedback-route:<route UUID>` (the durable route row stores `outcome_signal_id`; responses project `outcome_signal_ref=governance-signal:<signal UUID>` from it); `low_rating` materializes as review pressure (`ticket_pressure`, unknown freshness), `stale_answer` as suspected freshness/drift review (`drift`, stale freshness), missing/draft-only/ineligible targets are blocked without guessing, and execution never auto-changes content or publishes — completion proves materialization into governed review truth only, not reviewer action, draft creation, publication, downstream propagation, KPI improvement, or business impact; command replay preserves the same signal/route identity but projects the route's current durable lifecycle (never a frozen byte-for-byte snapshot), so a later exact replay may truthfully show `completed`/`blocked`/`failed` without creating duplicate truth
- a deterministic, offline CYG-117 domain eval gate, run with `uv run python scripts/domain_eval_gate.py`, whose stable JSON report and process status cover retrieval, audience, trace/citation, freshness, unsupported/escalation, approval, and publish-policy checks without using live providers, fallback fixtures, or session memory as truth

This package intentionally does **not** expand into:
- GTM / pricing / sales collateral
- deep technical implementation lock-in
- full customer-facing bot conversation design
- action-layer automation design beyond future references

## Current repo stage
Cygnus is no longer only a documentation package. It now combines:
- product and planning docs
- Arkon full-port substrate import work
- runability recovery work
- Arkon internalization / upstream-cutover planning
- durable governance/control-plane implementation surfaces

So downstream readers should not treat this repo as docs-only, and should not assume the visual/product-story pack is the current engineering entry point. P1/P2/P2.5 and the first support-verticalization waves are complete; CYG-92–96 provides a request-scoped governed session seam that revalidates Cygnus truth.

CYG-98–105 plus CYG-108/109/111/112/113/114/115/116/117/118/119 now provide durable ledger/audit, notifications, ticket/rewrite pressure, release/incident drift, audience bindings/conflicts, review assignments, source impact, publish/propagation, golden-path proof, durable publish and draft/review tools, scoped durable drift alerts, replay-safe consumption feedback with frozen review/refresh route intents, bounded feedback-route execution that materializes durable outcome governance signals into governed review truth, truthful source-evidence observation presentation, and the deterministic production-shaped domain eval gate. Route completion proves materialization into governed review truth only — not reviewer action, draft creation, publication, downstream propagation, KPI improvement, or business impact — and execution never auto-changes knowledge content or publishes. The eval command is `uv run python scripts/domain_eval_gate.py`; its exit status is merge-blocking evidence for the deterministic checks only, not evidence of downstream feedback-route worker execution or business KPI instrumentation. The shared session/MCP contract marks twelve governed tools `ready`: four retrieval tools; `list_drift_alerts`; `propose_knowledge_object`, `update_draft_object`, `request_review`, and `read_review_feedback`; `record_feedback_signal`; `validate_publish_policy`; and `publish_knowledge_object`; capabilities reports `not_exposed:[]`.

CYG-122 further provides the bounded `resolved-ticket-export/v1` pilot from sanitized CSV/JSONL records to deterministic cluster candidates and durable review-bound ticket-pressure truth. Its exact-replay/conflict boundary treats `source_ref` as an immutable export identity; only threshold-qualified clusters persist, and neither a successful import nor review assignment implies draft creation, approval, publication, KPI improvement, or validated real-data ROI.

CYG-123 now closes the next deterministic step with an explicit, admin-gated signal-to-draft command and authenticated Review Queue workflow. The result remains intentionally bounded: persisted draft truth is separate from review submission, approval, and publication, and synthetic smoke evidence is not real-data product validation.

CYG-125 binds that bounded import to explicit ready Source truth. The binding survives signal creation, reviewer-controlled draft promotion, approval, and restart-durable publication; the importer still never creates a Source, submits a draft, approves, or publishes automatically, and fixture proof still does not establish business impact.
