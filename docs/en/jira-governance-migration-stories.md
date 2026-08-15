# Cygnus — Jira Governance Migration Story Pack

## 1. Purpose of this document
This document turns the migration-story request for the **CYG Jira board** into a Jira-ready product story pack.

It is meant to support:
- product narrative alignment,
- design alignment,
- downstream execution sequencing.

It is **not** meant to become:
- a backend / schema / worker migration breakdown,
- an agent runtime backlog,
- a generic PM board.

The core thesis of the pack must remain:
**Cygnus is growing, on top of Arkon’s knowledge substrate, into a support knowledge governance center.**

## 2. Scope boundaries
### 2.1 What migration this pack is actually describing
It describes the migration:
- from “knowledge compilation exists”
- to “support leaders actually gain governance control.”

That means every story should explain:
- who gains a new judgment position,
- who gains a new command authority,
- which risk becomes visible earlier,
- which error-propagation point can now be blocked sooner.

### 2.2 What this pack must not become
Do not write it as:
- technical migration layers,
- AI-agent workflow tickets,
- a page-construction checklist,
- prettier process visualization.

### 2.3 Jira usage recommendation
- Create Epics first, then Stories.
- An Epic represents one **governance-loop migration line**.
- A Story represents one **user-visible shift in governance control**.
- If a story cannot explain the new control power, it should not exist.

### 2.4 Suggested labels
- `migration`
- `governance-loop`
- `review-publish`
- `support-brain`
- `cygnus`

## 3. Validation rule for every story
A valid migration story must answer:
1. **Who** gains a new governance position?
2. **What risk** becomes visible earlier for the first time?
3. **What command** can now be issued instead of merely observed?
4. **What propagation consequence** becomes explicitly visible?
5. Why is this a **control migration** rather than a **process visualization**?

If it cannot answer these questions, delete or rewrite it.

## 4. Epic overview and recommended order

| Order | Epic title | Migration thesis | Primary users | Visual north star | Interaction north star |
|---|---|---|---|---|---|
| E1 | Governance Loop Migration — Review Becomes Command Brief | Review stops being a draft list and becomes the first entry into governance command | Support Lead / Support Ops / Knowledge Manager | Situation Frame + Priority Re-stack | Judge first, then review |
| E2 | Governance Loop Migration — Publish Becomes Blast-Radius Control | Publish stops being an approval event and becomes consequence-aware propagation control | Support Ops / Knowledge Manager | Blast Radius Preview + Propagation Theater | See consequences before issuing the command |
| E3 | Governance Loop Migration — Ticket & Drift Become Review Pressure | Ticket, drift, and source signals stop being passive data and become pressure on the review loop | Support Ops / Escalation Lead | Drift Weather Layer + Signal Loss Layer | Move from risk signal directly into governance action |
| E4 | Governance Loop Migration — Propagation Becomes Recovery Proof | Governance actions must not only execute; they must prove the system realigned | Head of Support / Support Lead | Recovery Window + Reality Check | Verify recovery before deciding the next move |

---

## 5. Epic E1 — Review Becomes Command Brief

### Epic definition
- **Issue type:** Epic
- **Epic title:** Governance Loop Migration — Review Becomes Command Brief
- **Epic summary:** Migrate review from a draft-processing workflow into the first command surface of support governance, so leaders can see the most intervention-worthy risk, owner gap, and queue consequence before they descend into object detail.
- **Why this epic must come first:** If review remains a content-approval console, Cygnus collapses back into a document backend instead of becoming mission control.
- **Visual north star:** Morning Command Brief, Situation Frame, Priority Re-stack
- **Interaction north star:** see system tension first, then decide review order and coordination moves

### Story E1-S1 — The review entry shows “today’s most intervention-worthy governance risk” first
- **Primary user:** Support Lead / Support Ops
- **User story:** As a support leader, I want the Review surface to open on the governance risks that deserve intervention today rather than on a static draft list, so I can decide where the organization should focus first.
- **User behavior:** Enter review, scan the day’s tension, and identify which drafts / topics / audience conflicts deserve first action.
- **Expected system behavior:** Rank the entry by governance risk, blast radius, speed of wrong-answer spread, and owner gap rather than by creation time.
- **Visual effect:** The first screen feels like a morning command brief; the top is a Situation Frame and the middle is a risk-ranked Priority Stack instead of a standard table.
- **Interaction effect:** The user can jump straight from a high-priority item into route, assign, or urgent review without opening full content first.
- **Why this migration matters:** It moves the user’s first judgment position from “read drafts” to “command priorities.”
- **Acceptance signals:**
  - The default review entry shows system-level risk ranking instead of recent drafts.
  - Each priority item displays impacted audience, downstream surface, and current owner state.
  - The user can issue coordination moves directly from this view.
- **Critical boundary:** This is not a skin update for the review page; it changes the subject of review from “content” to “governance risk.”

### Story E1-S2 — Every review item explains “why it matters now” before content detail
- **Primary user:** Knowledge Manager / Support Ops
- **User story:** As a knowledge owner, I want every review item to explain why it matters now before I read the body, so I do not accidentally treat a system-level risk like a normal content revision.
- **User behavior:** Before opening a draft, judge whether it is linked to a release, incident, policy collision, or audience mismatch.
- **Expected system behavior:** Present the risk frame, evidence strength, impacted audience, and downstream contamination before the body diff.
- **Visual effect:** Each review item feels like a governance packet with a Command-origin Tag, Evidence Strength, and Audience Impact rather than only a title and timestamp.
- **Interaction effect:** The user can move through understand-importance → inspect detail → return to global ranking without losing context.
- **Why this migration matters:** It prevents review from collapsing back into “approve AI suggestions one by one.”
- **Acceptance signals:**
  - Risk context appears before body diff when a review item is opened.
  - The user can see which system tension this change is addressing.
  - The user can understand why the item is high priority without external context.

### Story E1-S3 — Review order can be re-stacked, re-routed, or escalated without losing the upstream command chain
- **Primary user:** Support Lead / Knowledge Manager
- **User story:** As a support leader, I want review work to be re-stacked, re-routed, or escalated in response to changing system pressure while preserving the context of which command triggered it, so execution teams do not lose the reason this work rose to the top.
- **User behavior:** Re-define what gets handled first, who takes it, and what needs urgent intervention.
- **Expected system behavior:** Allow batch re-stack, reroute, and urgent review while preserving linkage between each task and the upstream risk event.
- **Visual effect:** The queue contains a clear Priority Re-stack Lane and Command-origin Tag so the reordering itself becomes visible.
- **Interaction effect:** After order changes, the system immediately reflects impacted owners, execution pressure, and downstream waiting relationships.
- **Why this migration matters:** Without it, Review remains a static work queue rather than a command-driven governance execution surface.
- **Acceptance signals:**
  - The user can reprioritize from the queue layer without editing each item individually.
  - Every task can be traced back to its originating risk or command.
  - Order changes reflect back into owner and dependency state.

---

## 6. Epic E2 — Publish Becomes Blast-Radius Control

### Epic definition
- **Issue type:** Epic
- **Epic title:** Governance Loop Migration — Publish Becomes Blast-Radius Control
- **Epic summary:** Migrate publish from a pass/fail checkpoint into a consequence-aware propagation control action so the team sees audience, channel, and downstream impact before it releases knowledge.
- **Why this is half of the main axis:** Review answers “should we move?” Publish answers “who gets affected if we move?”
- **Visual north star:** Audience Scope Summary, Channel Gate Matrix, Blast Radius Preview, Propagation Theater
- **Interaction north star:** understand consequences first, then issue the command, then observe propagation

### Story E2-S1 — Publish previews blast radius across audiences and channels before action
- **Primary user:** Knowledge Manager / Support Ops
- **User story:** As a governance owner, I want to see which audiences and channels will be affected before I publish, so a locally correct answer does not spread to the wrong people.
- **User behavior:** Before publish, republish, or restrict, confirm the effect across free / enterprise / region / version / internal-external audiences.
- **Expected system behavior:** Provide a clear Blast Radius Preview that shows which surfaces will gain, continue, lose, or conflict on exposure.
- **Visual effect:** The publish surface looks like a gate-control panel; the Blast Radius Preview is visually more dominant than the submit action.
- **Interaction effect:** The user can expand each audience/channel consequence before issuing the command and can quickly compare internal vs external effects.
- **Why this migration matters:** It moves Publish from “approval” to “propagation judgment.”
- **Acceptance signals:**
  - Audience scope and channel impact appear before the command is confirmed.
  - The user can distinguish new exposure, continued exposure, stopped exposure, and conflict.
  - The user does not have to rely on memory to understand the blast radius.

### Story E2-S2 — Publish can open, narrow, split, or pause exposure instead of only approve/reject
- **Primary user:** Support Ops / Knowledge Manager
- **User story:** As a governance owner, I want publish actions to include open, restrict, delay, or split-by-audience options rather than only approve/reject, so I can control propagation when an answer is only partially safe.
- **User behavior:** Decide that a partially correct object should be internal-only, limited to part of the audience, or temporarily blocked externally.
- **Expected system behavior:** Express publish as governance actions such as publish, restrict, split variant, hold external, or republish internal only.
- **Visual effect:** The publish surface feels like a control zone with gates and routing paths rather than a single confirmation box.
- **Interaction effect:** As the user changes the action, the consequence lens updates immediately, making limited publication a natural move instead of an advanced setting.
- **Why this migration matters:** It gives Publish the granularity expected from support governance rather than document-backend go-live logic.
- **Acceptance signals:**
  - The publish layer supports more than approve/reject.
  - One action can address both internal/external scope and audience-variant differences.
  - Partial release and partial restriction are treated as normal governance paths.

### Story E2-S3 — After publish, the system shows where propagation succeeded and where it stalled
- **Primary user:** Support Lead / Support Ops
- **User story:** As a support leader, I want the system to tell me which supporting surfaces synced and which are still blocked after publish, so I can judge whether the command actually changed the support system.
- **User behavior:** After publish / restrict / republish, inspect whether internal copilot, review queue, external surfaces, and feedback surfaces updated.
- **Expected system behavior:** Provide a Propagation Theater / Ledger that shows propagated, pending, failed, or manual-follow-up states.
- **Visual effect:** Publish success is not just a toast; it becomes a visible propagation path and state ribbon.
- **Interaction effect:** The user can jump directly from propagation status into the blocked point that needs intervention.
- **Why this migration matters:** Without propagation feedback, Publish remains a button event rather than a system command.
- **Acceptance signals:**
  - Post-publish status is visible across supporting surfaces.
  - The system clearly distinguishes propagated, pending, failed, and manual-action-needed states.
  - The user can continue governance actions from the propagation result.

---

## 7. Epic E3 — Ticket & Drift Become Review Pressure

### Epic definition
- **Issue type:** Epic
- **Epic title:** Governance Loop Migration — Ticket & Drift Become Review Pressure
- **Epic summary:** Migrate ticket clusters, frontline rewrites, release/incident drift, and source failures from passive observation signals into active pressure on the review loop.
- **Why this epic matters:** If Review and Publish only consume manually created drafts, Cygnus loses the dynamic entry point of the support system itself.
- **Visual north star:** Drift Weather Layer, Decision Constellation, Signal Loss Layer
- **Interaction north star:** move directly from risk signal into governance action

### Story E3-S1 — Repeated rewrites and repeated tickets rise into review pressure instead of staying as analytics
- **Primary user:** Support Ops / Escalation Lead
- **User story:** As a support-operations lead, I want repeated human rewrites and recurring ticket patterns to rise directly into governance pressure instead of staying on an insight page, so the issues wasting real team effort enter the review loop sooner.
- **User behavior:** See a repeatedly rewritten answer or recurring ticket pattern and decide whether it should trigger a draft, urgent review, or ownership reroute.
- **Expected system behavior:** Turn rewrite clusters and recurring ticket patterns into review pressure with suggested object type and blast radius.
- **Visual effect:** These signals appear like rising pressure lines, not chart-only statistics.
- **Interaction effect:** The user can go directly from a cluster or rewrite signal into route to review, assign owner, or mark urgent.
- **Why this migration matters:** It turns frontline friction into governance intake rather than post-hoc analysis.
- **Acceptance signals:**
  - Rewrite and recurring-ticket signals can enter the review queue directly.
  - The system shows object suggestions and blast radius alongside the signal.
  - The user does not need to create a knowledge task manually before governance can begin.

### Story E3-S2 — Release and incident drift can force an urgent review path
- **Primary user:** Support Lead / Knowledge Manager
- **User story:** As a support leader, I want release- or incident-driven drift to force an urgent review path, so wrong answers do not spread across downstream surfaces before documentation catches up.
- **User behavior:** During release week or an incident, identify which objects and audiences are drifting and choose urgent refresh or urgent review.
- **Expected system behavior:** Elevate drift from “staleness notice” to a commandable governance state: open urgent review, freeze external publish, or force audience recheck.
- **Visual effect:** Coverage & Drift feels like a weather front pressing toward specific topics and audiences rather than a page of freshness badges.
- **Interaction effect:** When the user enters the command path from a drift warning, the release/incident context persists through review and publish.
- **Why this migration matters:** It turns “Freshness matters” into an actual product action rather than an observational metric.
- **Acceptance signals:**
  - Drift warnings can directly trigger governance actions.
  - Release and incident context persist into downstream review/publish steps.
  - The urgent path supports “restrict first, repair content next.”

### Story E3-S3 — Source failure is understood as governance blindness, not just sync failure
- **Primary user:** Support Ops / Knowledge Manager
- **User story:** As a knowledge-governance owner, I want source failure to explain which objects and judgments are losing trust, so I can decide whether to repair the source first or restrict propagation first instead of seeing only a technical error.
- **User behavior:** See a parse failure, sync interruption, or source anomaly and judge which objects, publish decisions, and downstream surfaces are now compromised.
- **Expected system behavior:** Translate source failure into affected objects, affected audiences, and risky publish decisions, then offer governance actions such as repair source, restrict propagation, or route for manual review.
- **Visual effect:** The source-health surface includes a Signal Loss Layer so parts of the system feel “blind,” not merely red.
- **Interaction effect:** The user can move directly from a source issue into object or publish control rather than bouncing between logs and business surfaces.
- **Why this migration matters:** It reframes substrate failure as decision failure and protects the credibility of the control tower.
- **Acceptance signals:**
  - Source failure maps to concrete objects and propagation risk.
  - Governance actions can be issued directly from the source surface.
  - The system presents business consequence, not only technical status.

---

## 8. Epic E4 — Propagation Becomes Recovery Proof

### Epic definition
- **Issue type:** Epic
- **Epic title:** Governance Loop Migration — Propagation Becomes Recovery Proof
- **Epic summary:** Migrate governance actions from “executed” to “proven to have re-aligned the system,” so leadership decides the next move using recovery evidence rather than completed-task lists.
- **Why this closes the loop:** If the product cannot prove whether its commands changed the system, it remains a command illusion.
- **Visual north star:** Recovery Window, Reality Check, Recovery Snapshot
- **Interaction north star:** verify recovery first, then decide the next action

### Story E4-S1 — Supporting surfaces report whether governance commands actually changed frontline behavior
- **Primary user:** Head of Support / Support Lead
- **User story:** As a support leader, I want copilot and human-support surfaces to report whether governance commands actually changed frontline behavior, so I can tell whether the system is realigning or whether only backend state changed.
- **User behavior:** After review / publish / restrict, inspect whether frontline suggestions, rewrites, and escalations changed.
- **Expected system behavior:** Feed usage changes from copilot and downstream surfaces back as governance results rather than isolated events.
- **Visual effect:** The Downstream Reality Check acts like a mirror for the control layer, showing real frontline consequences.
- **Interaction effect:** The user can open the downstream response directly from a specific governance command.
- **Why this migration matters:** It makes supporting surfaces result mirrors instead of alternative product centers.
- **Acceptance signals:**
  - Downstream behavior can be viewed per governance command.
  - Rewrite, reject, and escalate events are grouped as governance feedback.
  - The user can see whether frontline behavior converged toward the latest governed state.

### Story E4-S2 — The Recovery Window answers whether the system became more aligned because of this action
- **Primary user:** Head of Support / Support Ops
- **User story:** As a support leader, I want a Recovery Window that clearly tells me whether the system became safer, clearer, and less error-prone because of this action, so I can judge whether the command actually worked.
- **User behavior:** After a key command, review changes in rewrites, escalations, coverage gaps, drift, and publish conflicts.
- **Expected system behavior:** Reflect recovery signals around a governance action, showing what converged, what remains risky, and what still needs intervention.
- **Visual effect:** The Recovery Window presents before/after change plus unresolved gaps rather than a generic activity log.
- **Interaction effect:** The user can continue directly from the recovery view into the next command without losing context.
- **Why this migration matters:** Without recovery proof, the command center becomes a busy illusion that cannot distinguish action from effectiveness.
- **Acceptance signals:**
  - The system can show recovery results for a specific governance action.
  - The view includes both improvements and unresolved items.
  - The user can launch follow-up governance work from the Recovery Window.

### Story E4-S3 — Leadership can compare open governance loops and decide the next highest-leverage move
- **Primary user:** Head of Support / Support Lead
- **User story:** As a support leader, I want the system to compare multiple still-open governance loops and help me choose the next highest-leverage command, so I do not have to return to a raw dashboard and manually reconstruct the state of the system.
- **User behavior:** After one intervention cycle, compare which loops converged, which are still spreading, and where leadership should intervene next.
- **Expected system behavior:** The Command Center summarizes open loops, residual risk, pending propagation, and recovery proof so the next prioritization decision is obvious.
- **Visual effect:** The homepage feels like a live governance war room rather than a dashboard that restarts from zero every time.
- **Interaction effect:** The user can move from recovery state back into a new command brief, preserving the full Observe → Frame → Route → Change → Propagate → Verify rhythm.
- **Why this migration matters:** It lifts Cygnus from “a place where governance actions were performed” to “a console that continuously commands the support system.”
- **Acceptance signals:**
  - Leadership can compare multiple open loops in one place.
  - The next highest-leverage action can be chosen from that same view.
  - The system does not require a return to raw data pages to rebuild the situation.

---

## 9. Jira entry template
Use this template when copying an individual story into Jira.

```md
Title: <Story title>
Issue Type: Story
Parent Epic: <Epic title>
Labels: migration, governance-loop, review-publish, support-brain, cygnus

Primary user:
User story:
User behavior:
Expected system behavior:
Visual effect:
Interaction effect:
Why this migration matters:
Acceptance signals:
- ...
- ...
- ...
Critical boundary (optional):
```

## 10. Final check before board entry
Before creating the Jira issue, confirm:
- Does this ticket describe Cygnus as a support governance center rather than an agent tool?
- Does it grant some role a new judgment position or command authority?
- Does it make risk visibility, propagation consequence, or recovery proof explicit?
- Did it accidentally degrade into a page-construction task or technical task?

If the full pack reads more like:
- a process diagram,
- an approval-console upgrade list,
- a generic dashboard backlog,

then the migration alignment is still incomplete.
