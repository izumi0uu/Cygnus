# Design

## Source of truth
- Status: Active
- Last refreshed: 2026-06-04
- Primary product surfaces:
  - Command Center / Overview
  - Review Queue
  - Knowledge Object Workspace
  - Coverage & Drift
  - Ticket / Queue Insights
  - Sources
  - Publish Rules
  - Copilot Surfaces
- Evidence reviewed:
  - `docs/zh/prd.md`
  - `docs/zh/information-architecture.md`
  - `docs/zh/domain-model.md`
  - `docs/zh/workflows.md`
  - `docs/en/prd.md`
  - `docs/en/information-architecture.md`
  - `docs/en/domain-model.md`
  - `docs/en/workflows.md`
  - `.omx/specs/deep-interview-support-brain-complete-story.md`
  - `.omx/interviews/support-brain-complete-story-20260604T125806Z.md`
  - Repository inspection result: no existing UI source, component library, visual baselines, screenshots, or brand asset files were found in the repo at refresh time.
- Detailed companion docs:
  - `docs/zh/product-story.md` / `docs/en/product-story.md`
  - `docs/zh/frontend-story.md` / `docs/en/frontend-story.md`
  - `docs/zh/visual-language.md` / `docs/en/visual-language.md`
  - `docs/zh/interaction-principles.md` / `docs/en/interaction-principles.md`
  - `docs/zh/page-story-map.md` / `docs/en/page-story-map.md`
  - `docs/zh/screen-spec.md` / `docs/en/screen-spec.md`
  - `docs/zh/wireframe-architecture.md` / `docs/en/wireframe-architecture.md`
  - `docs/zh/state-matrix.md` / `docs/en/state-matrix.md`
  - `docs/zh/command-flows.md` / `docs/en/command-flows.md`
  - `docs/zh/component-taxonomy.md` / `docs/en/component-taxonomy.md`
  - `docs/zh/critical-surface-blueprints.md` / `docs/en/critical-surface-blueprints.md`
  - `docs/zh/core-wireframe-variants.md` / `docs/en/core-wireframe-variants.md`
  - `docs/zh/high-density-hero-blueprints.md` / `docs/en/high-density-hero-blueprints.md`

## Brand
- Personality:
  - Calm authority
  - Operational clarity
  - Command-grade trustworthiness
  - Cross-functional coordination discipline
  - Expert, not performative
- Trust signals:
  - Explicit evidence and source trace
  - Freshness, drift, and publish state always visible
  - Audience scope shown before downstream use
  - Ownership, routing, and impact displayed near every consequential action
  - Change history and propagation status visible without hunting
- Avoid:
  - Chat-first AI assistant aesthetics
  - Generic agent studio / workflow builder framing
  - Marketing-dashboard gloss
  - Playful mascots, gradients, and “AI magic” tropes
  - A frontline support-agent desktop becoming the visual protagonist

## Product goals
- Goals:
  - Help support leaders see where fragmented support operations need coordinated intervention.
  - Turn scattered knowledge, release changes, ticket patterns, and risk signals into governed command surfaces.
  - Let leaders route attention across queues, teams, knowledge objects, and channels.
  - Keep human agents, AI copilot surfaces, and customer-facing answers aligned to one governed knowledge layer.
  - Make downstream answer quality feel managed, not accidental.
- Non-goals:
  - Building another customer-facing support bot
  - Becoming a generic RAG platform or generic agent platform
  - Expanding into admin / billing / pricing backoffice
  - Optimizing primarily for daily ticket handling by frontline agents
  - Making “approve/reject AI suggestions” the whole product posture
- Success signals:
  - Leaders can identify the next highest-leverage intervention quickly.
  - Cross-queue and cross-team coordination feels native, not bolted on.
  - Knowledge drift, audience mismatch, and publish risk become visible before they create repeated wrong answers.
  - Supporting surfaces clearly reflect control-tower decisions.

## Personas and jobs
- Primary personas:
  - Head of Support
  - Support Ops lead
  - Knowledge Manager
- User jobs:
  - Detect where support operations are moving out of alignment.
  - Decide which queue, audience, or knowledge object deserves intervention now.
  - Route review, escalation, publish, and follow-up work across teams.
  - Confirm whether commands changed downstream support behavior.
- Key contexts of use:
  - Before support standup
  - During release week
  - During incidents / known-issue spikes
  - When queue pressure shifts across plans/regions/products
  - During quality-review or audit windows

## Information architecture
- Primary navigation:
  - Command Center
  - Review Queue
  - Knowledge Objects
  - Coverage & Drift
  - Ticket / Queue Insights
  - Sources
  - Publish Rules
  - Copilot Surfaces
- Core routes/screens:
  - Global command overview
  - Queue / topic command board
  - Knowledge review queue
  - Object detail and version history
  - Audience variant comparison
  - Publish impact and propagation view
  - Source health and sync status
  - Copilot feedback / rewrite / escalation feedback loop
- Content hierarchy:
  - Global operational movement first
  - Then queue/topic/audience risk
  - Then object-level evidence and ownership
  - Then downstream channel consequences
  - Then local editing / reviewing detail

## Design principles
- Principle 1:
  - Control tower first. The protagonist is the support leader’s decision surface, not the agent workspace.
- Principle 2:
  - Command before composition. The interface should help users move the system, not merely inspect it.
- Principle 3:
  - Evidence backs every command. Risk, routing, publish, and escalation actions must stay close to source trace and audience impact.
- Principle 4:
  - Downstream surfaces inherit from governed center. Copilot, human support UI, and customer-facing outputs are consumers of decisions made here.
- Tradeoffs:
  - Choose explicit state over decorative minimalism.
  - Choose operational hierarchy over “friendly AI” softness.
  - Choose cross-surface coordination clarity over single-screen simplicity.
  - Allow deep drill-downs, but never let drill-down replace command posture.

## Visual language
- Color:
  - Neutral, technical base colors that can support dense information.
  - Blue for governed action / trusted control.
  - Amber for coordination risk / pending intervention.
  - Red for urgent drift / blocked publish / incident-linked instability.
  - Green only for confirmed alignment, not for decorative positivity.
- Typography:
  - Strong sans-serif base with disciplined hierarchy.
  - Tabular numerals for metrics, queue movement, and timestamps.
  - No playful display typography.
- Spacing/layout rhythm:
  - Dense but breathable operational grid.
  - Persistent macro-to-micro hierarchy: global -> queue -> object -> evidence.
  - Panels should feel composable, not card-gallery-like.
- Shape/radius/elevation:
  - Low-to-moderate radius.
  - Restraint in shadow and blur.
  - Separation should come from hierarchy and edges, not decoration.
- Motion:
  - Fast, deliberate, consequence-oriented.
  - Motion should clarify system state propagation, not entertain.
- Imagery/iconography:
  - Schematic, symbolic, directional.
  - Queue, route, publish, and propagation metaphors are preferred over chat metaphors.

## Components
- Existing components to reuse:
  - None yet in repository code. Reuse pressure currently applies to concepts, vocabulary, and object model from product docs rather than code components.
- New/changed components:
  - Global command header
  - Situation Frame
  - Command Spine
  - Command Ribbon
  - Priority / intervention board
  - Decision Constellation
  - Drift Weather Layer
  - Knowledge object health card
  - Object Gravity Panel
  - Audience variant comparison panel
  - Blast Radius Preview / Consequence Lens
  - Propagation Theater
  - Propagation Ledger
  - Recovery Window
  - Evidence drawer / trace panel
  - Supporting-surface status mirror
- Variants and states:
  - Severity: normal / elevated / critical
  - Coordination: unassigned / routed / blocked / awaiting review / executed
  - Object lifecycle: draft / review / approved / published / superseded / archived
  - Audience coverage: complete / partial / unknown / conflicted
- Token/component ownership:
  - Until UI code exists, `DESIGN.md` and the companion design docs are the design-token and component-intent source of truth.

## Accessibility
- Target standard:
  - WCAG 2.2 AA minimum
- Keyboard/focus behavior:
  - All command actions must be reachable and understandable by keyboard.
  - Focus order must preserve operational hierarchy.
- Contrast/readability:
  - Dense dashboards still need AA contrast in all semantic states.
  - Status cannot depend on color alone.
- Screen-reader semantics:
  - Queue movement, risk level, publish status, and downstream impact need explicit names.
- Reduced motion and sensory considerations:
  - Motion should be reducible without losing command meaning.
  - Alerts should never rely on constant flashing or animation.

## Responsive behavior
- Supported breakpoints/devices:
  - Desktop-first experience is the design priority.
  - Laptop support is required.
  - Tablet can support observational and limited coordination tasks.
  - Mobile should not be the primary control surface.
- Layout adaptations:
  - Smaller widths should preserve hierarchy rather than merely stacking everything.
  - Global movement and priorities remain above object detail.
  - Command Spine and Situation Frame should remain visible or collapsible without losing page context.
- Touch/hover differences:
  - Command-critical actions cannot depend on hover-only disclosure.

## Interaction states
- Loading:
  - Prefer last-known operational state plus explicit refresh/loading indicators.
- Empty:
  - Empty states should explain what absence means operationally and what signal would populate the view.
- Error:
  - Error states must say what command or observation is blocked and what remains trustworthy.
- Success:
  - Success states should confirm propagation scope, not just that a button was pressed.
- Disabled:
  - Disabled actions must expose why the user cannot command the system yet.
- Offline/slow network, if applicable:
  - Preserve last-known truth, mark staleness clearly, and prevent false confidence.

## Content voice
- Tone:
  - Decisive, precise, operational, non-performative
- Terminology:
  - Prefer: command, route, publish, drift, evidence, audience, coverage, propagation, escalation
  - Avoid: chatty assistant phrasing, anthropomorphic AI language, vague “optimize” language
- Microcopy rules:
  - State what changed, who/what is affected, and what the next consequential move is.
  - Favor active operational verbs.
  - Never hide scope or uncertainty in soft language.

## Implementation constraints
- Framework/styling system:
  - No frontend framework or styling system is present in the repo yet. Design decisions must stay implementation-neutral until stack selection is explicit.
- Design-token constraints:
  - Tokens should emerge from documented semantic roles, not from arbitrary palette exploration.
- Performance constraints:
  - Initial command surfaces should prioritize fast signal rendering and restrained motion.
- Compatibility constraints:
  - Must support modern desktop browsers without assuming hover or ultra-wide monitors as the only viable context.
- Test/screenshot expectations:
  - Once UI implementation exists, establish screenshot baselines for command center, queue coordination, propagation ledger, recovery window, review queue, object detail, and publish impact states.

## Open questions
- [ ] Should the eventual visual system default to dark mode, dual theme, or a daylight operational theme first? / owner: product-design / impact: high
- [ ] How much command authority should be executable directly from overview surfaces versus drill-down surfaces? / owner: product / impact: high
- [ ] Which coordination actions require explicit confirmation or approval gates in the first implementation pass? / owner: product + ops / impact: high
- [ ] Should tablet support be read-only, limited-action, or full-command for incident scenarios? / owner: product-design / impact: medium
- [ ] What semantic scale best expresses queue movement and cross-team load without becoming BI-noise? / owner: design / impact: medium
