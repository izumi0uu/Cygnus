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
- CYG-98–105 plus CYG-108/109/111/112/113/114 provide durable ledger/audit, notifications, ticket/rewrite pressure, release/incident drift, audience bindings/conflicts, review assignments, source impact, publish/propagation, golden-path proof, durable publish and draft/review tools, and scoped durable drift alerts
- the shared session/MCP contract marks eleven governed tools `ready`: four retrieval tools; `list_drift_alerts`; `propose_knowledge_object`, `update_draft_object`, `request_review`, and `read_review_feedback`; `validate_publish_policy`; and `publish_knowledge_object`
- only `record_feedback_signal` remains explicitly `not_exposed`
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
- [`docs/zh/eval-plan.md`](./zh/eval-plan.md) — Eval Plan（评估、回归门禁、业务指标）
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
- [`docs/en/eval-plan.md`](./en/eval-plan.md) — Eval Plan (evaluation layers, regression gates, business metrics)
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
- request-scoped governed reads whose explicit observation coverage prevents empty risk arrays from being interpreted as healthy truth
- a governed Nanobot ↔ Cygnus session seam that revalidates substrate truth on every turn and never treats session memory as knowledge truth
- a governed Nanobot ↔ Cygnus draft/review and publish seam for the durable draft/review lifecycle, policy validation, and approval-backed publication, with explicit versioning, idempotency, and propagation state

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

CYG-98–105 plus CYG-108/109/111/112/113/114 now provide durable ledger/audit, notifications, ticket/rewrite pressure, release/incident drift, audience bindings/conflicts, review assignments, source impact, publish/propagation, golden-path proof, durable publish and draft/review tools, and scoped durable drift alerts. The shared session/MCP contract marks eleven governed tools `ready`: four retrieval tools; `list_drift_alerts`; `propose_knowledge_object`, `update_draft_object`, `request_review`, and `read_review_feedback`; `validate_publish_policy`; and `publish_knowledge_object`. Only `record_feedback_signal` remains explicitly `not_exposed`.
