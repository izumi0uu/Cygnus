# Support Brain for SaaS — Component Taxonomy

## 1. What this document solves
The earlier docs already define:
- what the product is,
- how pages are organized,
- how states behave,
- how command flows move.

This document moves one layer closer to implementation:
**Cygnus should not become a generic dashboard component library. It needs a component taxonomy with control-tower semantics.**

It defines:
- which components are the backbone of the product,
- which components are for observation, command, propagation, and recovery,
- which component classes deserve priority on a page,
- which design moves would slide the product back into “BI platform” or “agent workflow tool.”

---

## 2. Component taxonomy principles

### Principle 1: components must carry role, not just data
Every critical component should answer one role question:
- does it help the user see the situation?
- make a judgment?
- issue a command?
- inspect propagation?
- judge recovery?

### Principle 2: components should not be neutral enough for any admin console
If a component could be dropped unchanged into a CRM, ticketing tool, or generic analytics product, it is probably not yet Cygnus enough.

### Principle 3: control tower outranks editor
Most Cygnus components should prioritize system judgment, propagation governance, and responsibility coordination before content writing.

### Principle 4: components may repeat across pages, but their semantics cannot drift
For example:
- `Situation Frame` exists on many screens, but always answers “why should you stay here now?”
- `Propagation Theater` can vary in density, but always answers “which layers did the move pass through?”

### Principle 5: components should respect command order
Components are not a flat gallery. They should naturally align to:
**Observe → Frame → Route → Change → Propagate → Verify**

---

## 3. Component Gravity Model

To stop screens from becoming “many cards competing for attention,” define four layers of component gravity:

| Gravity tier | Meaning | Typical components | Page role |
|---|---|---|---|
| G0 command anchors | establish page role and command context | Situation Frame, Command Spine, Command Ribbon | must be visible |
| G1 primary battlefields | carry the screen’s core judgment | Priority Stack, Decision Constellation, Drift Weather Layer, Propagation Theater | one primary arena per page |
| G2 command & governance | carry actions and routing | Intervention Ladder, Decision Footer, Command Actions Strip, Closure Judge | must sit adjacent to G1 |
| G3 evidence & echo | carry blast radius, evidence, recovery, affected surfaces | Consequence Lens, Evidence Drawer, Recovery Snapshot | secondary but not hidden |

### Usage rules
- A page should have at most **one G1 battlefield**.
- G2 must stay close to G1 to avoid “understand first, hunt for action later.”
- G3 may collapse, but must surface automatically or remain visible before and after consequential actions.

---

## 4. Component families

## 4.1 Command Continuity Family
These components make the product feel like one continuing command cycle rather than a set of modules.

### 1. Command Horizon
**Role:** shows global health, current operating window, and active command cycles.

- Default location: very top
- Key inputs: global health, active cycle, freshness, incident/release context
- Required states: stable / elevated / critical / stale
- Must not become: a plain nav bar with KPI pills

### 2. Situation Frame
**Role:** answers “why am I here?” in one sentence plus an operational frame.

- Default location: first content block on every major screen
- Key inputs: risk scope, cost of inaction, affected audiences, owner gap
- Required states: calm / emerging / overdue / blocked / recovery-incomplete
- Must not become: explanatory prose or a marketing hero

### 3. Command Spine
**Role:** tells the user whether they are in Observe / Frame / Route / Change / Propagate / Verify.

- Default location: left rail or top flow strip
- Key inputs: current phase, command origin, next unresolved phase
- Must not become: a generic stepper or breadcrumb

### 4. Command Ribbon
**Role:** preserves continuity of unresolved command work while the user moves across pages.

- Default location: bottom strip or lower-right floating rail
- Key inputs: active command shadow, highest-risk unresolved issue, return target
- Must not become: a command palette or notification center

---

## 4.2 Situation Intelligence Family
These components reveal where the support system is moving.

### 1. Priority Stack
**Role:** compresses “the most intervention-worthy movements” into a clear order.

- Typical screen: Command Center
- Core question: which 3 things deserve action today?
- Required states: stable / emerging / incident-linked / overdue
- Must not become: a generic card list

### 2. Movement Grid
**Role:** shows queue / topic / audience / channel movement across dimensions.

- Typical screen: Command Center
- Core question: is change local or spreading across surfaces?
- Must not become: a static reporting matrix

### 3. Decision Constellation
**Role:** reveals the relationship cluster among objects, queues, audiences, sources, and owners.

- Typical screen: Coordination Board
- Core question: why does this risk zone deserve tower intervention?
- Required states: ambiguous ownership / cross-team / audience conflict / blocked propagation
- Must not become: decorative network art

### 4. Drift Weather Layer
**Role:** makes drift feel like an approaching front instead of disconnected red dots.

- Typical screen: Coverage & Drift
- Core question: where is trouble forming next?
- Must not become: a heatmap effect layer

### 5. Reality Check Strip
**Role:** translates downstream rewrite / reject / escalate into readable control-tower feedback.

- Typical screen: Copilot / Downstream Reality Check
- Core question: did upstream governance actually change frontline reality?
- Must not become: an agent-performance strip

### 6. Signal Loss Layer
**Role:** translates source failure into the feeling of system blindness.

- Typical screen: Source Integrity
- Core question: what can the system no longer see clearly?
- Must not become: a technical incident panel

---

## 4.3 Governance Action Family
These components turn observation into governance action.

### 1. Intervention Ladder
**Role:** helps the user choose among route / assign / escalate / hold / review / constrain.

- Typical screen: Coordination Board
- Core question: what class of governance move fits this situation?
- Must not become: a row of equal-weight buttons

### 2. Decision Footer
**Role:** carries approve / reject / request evidence / reroute inside review context.

- Typical screen: Review Queue
- Core question: what should happen to this batch now?
- Must not become: a generic table toolbar

### 3. Command Actions Strip
**Role:** carries revise / split / restrict / escalate / send to review on object detail.

- Typical screen: Object Workspace
- Core question: should I change content, boundary, or variant logic?
- Must not become: a CMS editor toolbar

### 4. Channel Gate Matrix
**Role:** exposes publish / unpublish / restrict / partial-rollout boundaries by channel and audience.

- Typical screen: Audience / Publish Command Center
- Core question: who is allowed to see what?
- Must not become: a permissions settings form

### 5. Closure Judge
**Role:** helps the user decide whether the command cycle should close or continue.

- Typical screen: Recovery Window
- Core question: did this improvement actually earn closure?
- Must not become: a success-confirmation modal

---

## 4.4 Evidence Trust Family
These components bind action to evidence and prevent false confidence.

### 1. Consequence Lens / Blast Radius Preview
**Role:** shows scope, affected audiences, downstream surfaces, and ownership change before action.

- Common location: right dock or pre-action focus zone
- Must not become: a post-action summary card

### 2. Source Evidence Drawer
**Role:** exposes source trace, timestamp, confidence, and conflicts behind an object.

- Typical screen: Object Workspace
- Must not become: a buried attachments panel

### 3. Command-origin Tag
**Role:** marks which command produced this review item, propagation path, or recovery thread.

- Typical screens: Review Queue, Ledger
- Must not become: a weak metadata badge

### 4. Audience Scope Summary
**Role:** states “for whom is this truth currently valid?”

- Typical screens: Publish Command Center, Object Workspace
- Must not become: a filter summary

### 5. Owner & Load Strip
**Role:** makes responsibility and available capacity explicit before governance action.

- Typical screen: Coordination Board
- Must not become: a pure utilization graph

---

## 4.5 Propagation & Recovery Family
These components are where Cygnus most strongly differs from a normal knowledge backend.

### 1. Propagation Theater
**Role:** shows how a command crosses review, publish, copilot, and external surfaces.

- Typical screens: Publish, Propagation Ledger
- Core question: did the move actually pass through?
- Must not become: a toast plus activity feed

### 2. Command Timeline
**Role:** organizes the phases and turning points of one command cycle.

- Typical screen: Propagation Ledger
- Must not become: an audit-log timeline

### 3. Blocked Stage Column
**Role:** names where propagation stalled and why.

- Typical screen: Propagation Ledger
- Must not become: an error list

### 4. Recovery Snapshot
**Role:** compresses whether recent commands worked.

- Typical screen: Command Center
- Must not become: positive/negative KPI bricks

### 5. Before / After Alignment View
**Role:** compares drift, rewrite, escalation, and conflict deltas in Recovery Window.

- Typical screen: Recovery Window
- Must not become: a polished completion page

---

## 4.6 Supporting Mirror Family
These components let the user see downstream reality, affected planes, and residual mismatch.

### 1. Mismatch by Audience View
**Role:** separates error or rewrite by audience layer.

### 2. Affected Surfaces Preview
**Role:** shows which surfaces are touched: internal copilot, human support UI, external help center, and others.

### 3. Supporting-surface Status Mirror
**Role:** reflects whether downstream surfaces are truly synchronized.

These components should support the primary battlefield rather than become the protagonist.

---

## 5. Component implementation priority

| Priority | Meaning | First-batch components |
|---|---|---|
| P0 | without these, it is not Cygnus | Situation Frame, Command Spine, Priority Stack, Decision Constellation, Consequence Lens, Propagation Theater, Recovery Snapshot / Recovery Window |
| P1 | without these, tower judgment weakens | Command Ribbon, Intervention Ladder, Channel Gate Matrix, Owner & Load Strip, Reality Check Strip |
| P2 | the product still works, but identity and efficiency drop | Signal Loss Layer, Blocked Stage Column, Audience Scope Summary, Supporting-surface Status Mirror |

---

## 6. Semantic token axes for future design tokens

Before real color/spacing tokens are chosen, lock semantic axes first rather than color values first.

### Token Axis A — Severity
- stable
- emerging
- elevated
- critical

### Token Axis B — Propagation
- local
- routed
- partial
- blocked
- landed

### Token Axis C — Confidence
- confirmed
- usable-with-caution
- degraded
- blind

### Token Axis D — Lifecycle
- draft
- review
- approved
- published
- superseded
- archived

### Token Axis E — Authority
- observe-only
- route-ready
- command-ready
- confirmation-required
- locked

These axes will shape the product language earlier than “blue 500 / red 600” ever should.

---

## 7. Anti-pattern checklist

The design is drifting away from Cygnus if:

1. multiple G1 battlefields compete on one screen,
2. all action controls become equal-weight small buttons,
3. propagation is represented only as a toast or activity feed,
4. audience is treated as a filter instead of a truth boundary,
5. recovery is treated as a success celebration instead of a governance judgment,
6. copilot / downstream screens look like the primary frontline desktop,
7. source integrity looks like pure technical monitoring.

---

## 8. Usage rules
Before designing or implementing any page, answer:
1. what is the page’s G1 battlefield component?
2. is the G2 action component sitting close enough to it?
3. do G3 evidence / propagation / recovery components have explicit space?
4. would this component still feel correct inside a generic admin console? If yes, it is not yet Cygnus enough.

If a component does not clearly serve at least one of observation, command, propagation, or recovery, it should not enter the first Cygnus design system pass.
