# Support Brain for SaaS — Wireframe Architecture

## 1. What this document solves
`page-story-map.md` defines the page narrative and `screen-spec.md` defines per-screen responsibility.

This document moves one layer lower and defines:
**what those pages should look like at the wireframe level.**

It answers not visual style, but:
- which regions must persist,
- which regions are page-specific primary arenas,
- how the creative objects transform from screen to screen,
- where the eye should land first and next,
- how a command cycle becomes visible in layout.

---

## 2. Core wireframe principles

### Principle 1: show the situation before the object
The UI should not begin by dropping the user into one draft or one document.
The first visual read should establish:
- what the current tension is,
- who is affected,
- why action is warranted now.

### Principle 2: establish the command position before the operation position
On critical screens, command context must appear before local editors and local tables.

### Principle 3: propagation and recovery must earn layout space
Cygnus does not only let a user act. It lets them see whether the act moved through the system.
Every major screen therefore needs room for:
- Consequence Lens
- Propagation Theater
- Recovery signal

### Principle 4: persistent objects should transform across screens, not be reinvented
The same creative object should appear in different densities across the product.
For example:
- `Decision Constellation` can be compressed on the homepage and expanded on the coordination screen
- `Recovery Snapshot` can be a summary on the homepage and become the primary before/after structure in Recovery Window

### Principle 5: desktop is not just “responsive wide”; it is a command field of view
Desktop layout should protect:
- a true difference between strategic and execution regions,
- a true difference between situation, decision, and consequence layers.

---

## 3. Shared frame: Command Frame

All critical screens should share the following macro skeleton.

```text
┌──────────────── Command Horizon ────────────────┐
│ global health / active command / global time    │
├──────────────── Situation Frame ────────────────┤
│ why this matters / affected scope / current risk│
├──── Command Spine Rail ────┬──── Main Field ────┤
│ observe~verify position    │ page-specific arena│
│ active route / owner       │ judgment or action │
├──── Consequence / Evidence Dock ────────────────┤
│ blast radius / citations / audience impact      │
├──────────── Propagation + Recovery Band ────────┤
│ propagation theater / recovery signal / gaps    │
└──────────────── Command Ribbon ─────────────────┘
```

### A. Command Horizon
A thin band at the top.
Its job is to:
- tell the user whether the whole system is stable,
- show whether an active command cycle remains unresolved,
- show the current operating window (release week / incident / postmortem / drift spike).

### B. Situation Frame
The first true reading surface after page entry.
Its job is to:
- turn the screen from “module” into “current operational front,”
- show risk scope, affected audiences, and cost of inaction.

### C. Command Spine Rail
Prefer a persistent left rail, collapsing to a top strip on smaller widths.
Its job is to:
- show whether the user is in Observe / Frame / Route / Change / Propagate / Verify,
- preserve continuity across the current command cycle,
- provide fast return to upstream tension and downstream propagation.

### D. Main Field
The primary stage of the current screen.
Its job is to:
- carry the most important judgment or governance action on the page,
- retain visual authority over supporting panels.

### E. Consequence / Evidence Dock
Prefer a right-side dock that can expand on deep object pages.
Its job is to:
- show consequence before action,
- show evidence confidence during action,
- show affected surfaces and audiences after action.

### F. Propagation + Recovery Band
Prefer near-bottom placement, but it cannot be buried.
Its job is to:
- show whether the move actually propagated,
- show where it stalled if it did not,
- show whether propagation reduced drift / rewrite / escalation.

### G. Command Ribbon
A lightweight cross-screen strip.
Its job is to:
- remind the user they are still inside one command loop,
- surface the most dangerous unresolved cycle,
- provide one-click return to the current cycle.

---

## 4. Persistent zones vs contextual zones

| Zone | Persistence | Default location | Notes |
|---|---|---|---|
| Command Horizon | globally persistent | top | retained on all critical pages |
| Command Ribbon | globally persistent | bottom or floating lower-right strip | retained on all critical pages |
| Situation Frame | page persistent | first screen region | page entry must stay meaningful |
| Command Spine Rail | flow persistent | left | preserved across key command flows |
| Main Field | page-specific | center | each screen gets one primary arena |
| Consequence / Evidence Dock | contextual | right | collapsible, but must be visible before major action |
| Propagation + Recovery Band | flow persistent | lower area | required on command-bearing surfaces |

---

## 5. Transformation rules for creative objects

## 5.1 Situation Frame transformation
- On `Command Center`: a war-room briefing head
- On `Coordination Board`: a justification frame for why the front deserves attention
- On `Object Workspace`: a frame for why the object is not just a document
- On `Recovery Window`: a summary frame for whether the cycle is still worth continuing

## 5.2 Decision Constellation transformation
- On the homepage: a compressed risk cluster map
- On coordination: the primary working field
- On object detail: a reduced relationship view near object gravity

## 5.3 Propagation Theater transformation
- On publish surfaces: immediate post-action feedback
- On Propagation Ledger: the full stage map
- On Recovery Window: a compressed proof layer showing whether propagation became recovery

## 5.4 Recovery signal transformation
- On homepage: `Recovery Snapshot`
- On Ledger: a still-open vs closing indicator
- On Recovery Window: the primary before/after comparison structure

---

## 6. Per-screen wireframe architecture

## Screen 01 — Command Center / Morning Command Brief

### Visual order
1. today’s tension
2. the 3 most intervention-worthy movements
3. active command cycles already in motion
4. whether recent recovery worked

### Recommended skeleton
```text
┌ Command Horizon ─────────────────────────────────────────────┐
├ Situation Frame: top support-system tension + affected scope ┤
├ Left: Priority Stack ────────┬ Right: Movement Grid ────────┤
│ top 3 interventions          │ queue/topic/audience shifts  │
├ Left: Command Queue Preview ─┼ Right: Recovery Snapshot ────┤
├ Propagation/Recovery Band: recent cycle closure state ──────┤
└ Command Ribbon ─────────────────────────────────────────────┘
```

### Layout rules
- `Priority Stack` must grab attention before `Movement Grid`.
- `Recovery Snapshot` cannot become a buried stat tile; it is the first readback of whether governance recently worked.

---

## Screen 02 — Queue / Topic Coordination Board

### Visual order
1. current risk front definition
2. Decision Constellation
3. available Intervention Ladder
4. owner / load / consequence

### Recommended skeleton
```text
┌ Command Horizon ─────────────────────────────────────────────┐
├ Situation Frame: risk-front definition + cost of inaction ──┤
├ Spine Rail ─┬ Main Field: Decision Constellation ───────────┤
│ stage       │ queue/topic/object/audience/source map         │
│ owner state │                                               │
├ Spine Rail ─┼ Intervention Ladder + Owner/Load Strip ───────┤
├ Consequence Dock: blast radius / affected owners / channels ┤
├ Propagation Band: issued moves / next moves / blocked routes┤
└ Command Ribbon ─────────────────────────────────────────────┘
```

### Layout rules
- `Decision Constellation` must own the stage; it cannot be demoted to side-chart status.
- `Intervention Ladder` should sit directly adjacent so action follows understanding immediately.

---

## Screen 03 — Coverage & Drift Radar

### Visual order
1. where drift is advancing from
2. whether the problem is coverage gap or freshness drift
3. whether intervention belongs at source, object, or publish level

### Recommended skeleton
```text
┌ Command Horizon ─────────────────────────────────────────────┐
├ Situation Frame: current drift front + highest-risk audience┤
├ Main Field Top: Drift Weather Layer ────────────────────────┤
├ Left: Coverage Gap Matrix ───┬ Right: Source vs Object Panel┤
├ Left: Audience Risk Strip ───┼ Right: Suggested Intervention│
├ Recovery Band: whether past action reduced drift ───────────┤
└ Command Ribbon ─────────────────────────────────────────────┘
```

### Layout rules
- `Drift Weather Layer` should stretch across the top main zone to create the sense of an advancing front.
- `Suggested Intervention` must not feel like a recommendation widget; it is a next-command entry point.

---

## Screen 04 — Knowledge Review Queue

### Visual order
1. which command produced this queue
2. which work items were moved to the front
3. where evidence or ownership is weak
4. how approval / rejection / rerouting happens fast

### Recommended skeleton
```text
┌ Command Horizon ─────────────────────────────────────────────┐
├ Situation Frame: which system risk this queue is answering ──┤
├ Spine Rail ─┬ Main Field: Priority Re-stack Lane ───────────┤
│ upstream    │ reordered review items                         │
│ command     │                                               │
├ Spine Rail ─┼ Table: evidence / audience impact / owner ────┤
├ Decision Footer Strip: approve / reject / request / reroute ┤
├ Propagation Band: which surfaces synchronize after approval ┤
└ Command Ribbon ─────────────────────────────────────────────┘
```

### Layout rules
- The first meaningful column should surface `command-origin`, not only title.
- Decision Footer must remain reachable during multi-select / bulk action.

---

## Screen 05 — Knowledge Object Workspace / Control Room

### Visual order
1. which risks and surfaces the object currently attracts
2. current lifecycle and version state
3. whether audience variants conflict
4. then the actual content or structure editing

### Recommended skeleton
```text
┌ Command Horizon ─────────────────────────────────────────────┐
├ Situation Frame: the object’s current role in the system ───┤
├ Spine Rail ─┬ Main Field Top: Object Gravity Panel ─────────┤
│ lifecycle   │                                               │
│ nav         ├ Main Field Bottom: content / structure editor │
├ Spine Rail ─┼ Right Dock: audience variant + evidence drawer│
├ Command Actions Strip: revise / split / restrict / escalate ┤
├ Propagation/Recovery Band: downstream alignment of object ──┤
└ Command Ribbon ─────────────────────────────────────────────┘
```

### Layout rules
- The editor must not own the entire first screen.
- `Object Gravity Panel` must appear first so the surface never feels like a plain content backend.

---

## Screen 06 — Audience / Publish Command Center

### Visual order
1. who currently sees it
2. what surfaces a move will affect
3. where audience or channel conflict exists
4. whether propagation closes after publish

### Recommended skeleton
```text
┌ Command Horizon ─────────────────────────────────────────────┐
├ Situation Frame: current exposure boundary and risk ─────────┤
├ Spine Rail ─┬ Main Field Left: Audience Scope Summary ──────┤
│ publish     ├ Main Field Right: Channel Gate Matrix         │
│ state       │                                               │
├ Consequence Dock: Blast Radius Preview + Conflict Warnings ┤
├ Propagation Theater: rollout / blocked / partial / mismatch │
└ Command Ribbon ─────────────────────────────────────────────┘
```

### Layout rules
- `Blast Radius Preview` must be visible by default before a release command.
- Publish actions cannot be visually distant from the consequence region.

---

## Screen 07 — Source Integrity / Evidence Health

### Visual order
1. which sources are blind
2. which objects and surfaces the blindness affects
3. whether to repair or contain first

### Recommended skeleton
```text
┌ Command Horizon ─────────────────────────────────────────────┐
├ Situation Frame: governance impact of current source blindness┤
├ Main Field Top: Signal Loss Layer ──────────────────────────┤
├ Left: Source Health Table ─────┬ Right: Affected Objects    │
├ Left: Repair Actions ──────────┼ Right: Affected Surfaces   │
├ Recovery Band: whether trust recovers after repair ─────────┤
└ Command Ribbon ─────────────────────────────────────────────┘
```

### Layout rules
- Failure cannot appear merely as a sync-error message.
- Blindness must be translated immediately into downstream governance cost.

---

## Screen 08 — Copilot / Downstream Reality Check

### Visual order
1. where downstream is still rewriting / rejecting / escalating
2. whether the mismatch concentrates in one audience or object
3. whether this must escalate back into the tower

### Recommended skeleton
```text
┌ Command Horizon ─────────────────────────────────────────────┐
├ Situation Frame: gap between downstream reality and control ┤
├ Main Field Top: Reality Check Strip ────────────────────────┤
├ Left: Rewrite/Reject/Escalate Feed ─┬ Right: Mismatch View  │
├ Left: Upstream Object Links ────────┼ Right: Send Back Cmd  │
├ Recovery Band: whether alignment is returning ──────────────┤
└ Command Ribbon ─────────────────────────────────────────────┘
```

### Layout rules
- This is not a frontline support desktop; it is a listening surface for the control layer.
- The user should be able to elevate a local anomaly into a system issue in one move.

---

## Screen 09 — Propagation Ledger

### Visual order
1. where the cycle started
2. which stages it passed through
3. where it is blocked
4. which follow-up move is needed

### Recommended skeleton
```text
┌ Command Horizon ─────────────────────────────────────────────┐
├ Situation Frame: why the command chain is not yet closed ───┤
├ Spine Rail ─┬ Main Field Top: Command Timeline ─────────────┤
│ cycle map   ├ Main Field Main: Propagation Theater          │
│ stage nav   │                                               │
├ Spine Rail ─┼ Right Dock: blocked stages + affected surface │
├ Follow-up Command Strip: reroute / republish / contain ─────┤
└ Command Ribbon ─────────────────────────────────────────────┘
```

### Layout rules
- The center of the page must be propagation itself, not a log table.
- Blocked stages should sit near follow-up actions to shorten the distance from insight to next command.

---

## Screen 10 — Recovery Window

### Visual order
1. what changed before vs after
2. whether drift / rewrite / escalation truly reduced
3. whether the issue is closed or only suppressed
4. whether another cycle should begin

### Recommended skeleton
```text
┌ Command Horizon ─────────────────────────────────────────────┐
├ Situation Frame: recovery judgment for the current cycle ───┤
├ Main Field Top: Before / After Alignment View ──────────────┤
├ Left: Drift/Rewrite/Escalation Delta ─┬ Right: Closure Judge│
├ Continue or Close Decision Area ────────────────────────────┤
└ Command Ribbon ─────────────────────────────────────────────┘
```

### Layout rules
- This is not a success page.
- It must explicitly support the state “improved, but not yet restored.”

---

## 7. Cross-screen visual gravity rules

### Rule 1: each screen gets only one primary battlefield
Do not let two peer arenas compete for first attention.

### Rule 2: the right dock serves judgment, not information dumping
Consequence, evidence, and blockers should reduce decision distance.

### Rule 3: the bottom band carries the system’s echo
The lower band is not miscellaneous UI. It is the place where the system answers the move.

### Rule 4: persistent objects should create orientation memory
- top = system layer
- left = process layer
- center = judgment/governance layer
- right = impact/evidence layer
- bottom = propagation/recovery layer

---

## 8. Usage rules
Before moving into finer screen design, prototype, or frontend implementation, every page must answer:
1. Where is this page’s real battlefield?
2. Does Situation Frame truly explain why the user should stay here now?
3. Can the user see situation, move, and consequence within one visual pass?
4. Do propagation and recovery occupy explicit layout space?
5. Does the page still keep the support-lead control-tower view as the protagonist?

If these cannot be answered clearly, the wireframe is not yet Cygnus enough.
