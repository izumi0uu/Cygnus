# Support Brain for SaaS — Critical Surface Blueprints

## 1. What this document solves
`wireframe-architecture.md` defines the page macro skeleton.

This document pushes one step closer to execution and defines:
**how the most important screens should actually be directed before low-fi design or frontend implementation starts.**

It is not a high-fidelity visual spec. It is a blueprint layer:
- what the user must see in the first 7 seconds,
- which region is the primary battlefield,
- which components must coexist above the fold,
- how the screen should deform under unstable states,
- which mistakes would pull the product back into an ordinary dashboard.

---

## 2. Blueprint usage rules

Each blueprint includes:
1. where the screen sits in the command cycle,
2. what judgment the user must make there,
3. which components must be present above the fold,
4. the default visual path,
5. how layout changes under abnormal states,
6. which interaction priorities must not be broken.

---

## 3. Blueprint 01 — Command Center / Morning Command Brief

### Command-cycle segment
**See movement → Frame what matters**

### Core decision
Which system movements deserve control-tower intervention today?

### Must appear together above the fold
- Command Horizon
- Situation Frame
- Priority Stack
- Movement Grid
- Recovery Snapshot
- Command Ribbon

### Above-the-fold blueprint
```text
┌──────────────────────────────────────────────────────────────┐
│ Command Horizon                                              │
├──────────────────────────────────────────────────────────────┤
│ Situation Frame                                              │
│ “what is today’s top tension; what happens if nothing moves” │
├───────────────────────┬──────────────────────────────────────┤
│ Priority Stack        │ Movement Grid                        │
│ 1. highest-value move │ queue/topic/audience/channel shifts  │
│ 2. second move        │                                      │
│ 3. third move         │                                      │
├───────────────────────┼──────────────────────────────────────┤
│ Command Queue Preview │ Recovery Snapshot                    │
├──────────────────────────────────────────────────────────────┤
│ Command Ribbon                                               │
└──────────────────────────────────────────────────────────────┘
```

### First-7-seconds visual path
1. the one-sentence tension in Situation Frame
2. the first item in Priority Stack
3. the second and third priority items
4. Movement Grid to judge spread scope
5. Recovery Snapshot to judge whether recent governance worked

### Deformations under abnormal states

#### When `Leadership Intervention Overdue`
- enlarge the top Priority Stack item
- reduce Movement Grid visual weight
- let Situation Frame state the cost of inaction explicitly

#### When `Calm / Stable`
- give Recovery Snapshot more prominence
- compress Priority Stack into lower-noise briefing mode

#### When `Stale but Usable`
- Command Horizon must emphasize freshness gap
- reduce real-time motion and auto-refresh cues

### Absolute mistakes to avoid
- the first screen feels like a BI homepage
- Priority Stack and Movement Grid carry equal weight
- Recovery Snapshot collapses into a small metric badge

---

## 4. Blueprint 02 — Queue / Topic Coordination Board

### Command-cycle segment
**Frame what matters → Issue command**

### Core decision
Who should own this risk front, what should move first, and what class of move is needed?

### Must appear together above the fold
- Situation Frame
- Command Spine
- Decision Constellation
- Intervention Ladder
- Owner & Load Strip
- Consequence Lens
- Command Ribbon

### Above-the-fold blueprint
```text
┌──────────────────────────────────────────────────────────────┐
│ Command Horizon                                              │
├──────────────────────────────────────────────────────────────┤
│ Situation Frame                                              │
│ “why this front deserves action; where inaction spreads”     │
├──────────────┬───────────────────────────────────────────────┤
│ Command Spine│ Decision Constellation                        │
│ phase        │ queue/topic/object/audience/source relations  │
│ current cmd  │                                               │
├──────────────┼───────────────────────────────────────────────┤
│ Owner/Load   │ Intervention Ladder                           │
├──────────────┴───────────────────────────────────────────────┤
│ Consequence Lens                                             │
├──────────────────────────────────────────────────────────────┤
│ Command Ribbon                                               │
└──────────────────────────────────────────────────────────────┘
```

### First-7-seconds visual path
1. risk-front definition in Situation Frame
2. densest cluster inside Decision Constellation
3. responsibility and capacity in Owner & Load Strip
4. action type in Intervention Ladder
5. blast radius in Consequence Lens

### Deformations under abnormal states

#### When `Ambiguous Ownership`
- promote Owner & Load Strip visually
- strengthen route / escalate options in the ladder

#### When `No Safe Route Yet`
- move Consequence Lens upward
- disable unsafe actions explicitly with reasons

#### When `Conflict Across Audiences`
- highlight audience boundaries inside the constellation
- make the page feel more like a boundary-coordination surface than a task board

### Absolute mistakes to avoid
- turning Constellation into decorative graph art
- placing action controls far from the relationship field
- hiding responsibility, load, or consequence behind hover-only reveals

---

## 5. Blueprint 03 — Audience / Publish Command Center

### Command-cycle segment
**Issue command → Watch propagation**

### Core decision
Who should see what, and what is the blast radius of this release move?

### Must appear together above the fold
- Situation Frame
- Audience Scope Summary
- Channel Gate Matrix
- Blast Radius Preview
- Conflict Warnings
- Propagation Theater
- Command Ribbon

### Above-the-fold blueprint
```text
┌──────────────────────────────────────────────────────────────┐
│ Command Horizon                                              │
├──────────────────────────────────────────────────────────────┤
│ Situation Frame                                              │
│ “what boundary is being opened or tightened by this move”    │
├──────────────┬───────────────────────────────────────────────┤
│ Audience     │ Channel Gate Matrix                           │
│ Scope        │ channels × audiences × current gate state     │
├──────────────┴───────────────────────────────────────────────┤
│ Blast Radius Preview + Conflict Warnings                     │
├──────────────────────────────────────────────────────────────┤
│ Propagation Theater                                          │
├──────────────────────────────────────────────────────────────┤
│ Command Ribbon                                               │
└──────────────────────────────────────────────────────────────┘
```

### First-7-seconds visual path
1. boundary action in Situation Frame
2. current truth scope in Audience Scope Summary
3. current gate state in Channel Gate Matrix
4. move consequence in Blast Radius Preview
5. landing state in Propagation Theater

### Deformations under abnormal states

#### When `Conflict Risk`
- let Blast Radius Preview take more space
- keep action controls directly adjacent to warnings

#### When `Partial Rollout`
- enlarge Propagation Theater
- show landed vs not-landed regions side by side in the matrix

#### When `Split-Brain Publish`
- internal and external truth planes must be clearly separated visually

### Absolute mistakes to avoid
- the page feels like a permissions settings backend
- the user clicks publish before seeing consequence
- internal/external boundary is explained only through small labels

---

## 6. Blueprint 04 — Propagation Ledger

### Command-cycle segment
**Watch propagation**

### Core decision
Where is the command blocked, and what follow-up move is needed now?

### Must appear together above the fold
- Situation Frame
- Command Spine
- Command Timeline
- Propagation Theater
- Blocked Stage Column
- Follow-up Command Strip
- Command Ribbon

### Above-the-fold blueprint
```text
┌──────────────────────────────────────────────────────────────┐
│ Command Horizon                                              │
├──────────────────────────────────────────────────────────────┤
│ Situation Frame                                              │
│ “why the current cycle is not yet closed; which stage stalls”│
├──────────────┬───────────────────────────────────────────────┤
│ Command Spine│ Command Timeline                              │
│ current cycle│                                               │
├──────────────┼───────────────────────────────────────────────┤
│ Blocked Stage│ Propagation Theater                           │
│ Column       │                                               │
├──────────────┴───────────────────────────────────────────────┤
│ Follow-up Command Strip                                      │
├──────────────────────────────────────────────────────────────┤
│ Command Ribbon                                               │
└──────────────────────────────────────────────────────────────┘
```

### First-7-seconds visual path
1. unresolved cause in Situation Frame
2. current command position in Timeline
3. blockage in Blocked Stage Column
4. affected surfaces in Propagation Theater
5. immediate next move in Follow-up Command Strip

### Deformations under abnormal states

#### When `Propagation Blocked`
- promote Blocked Stage Column into the primary read target
- keep Follow-up Command Strip pinned and visible

#### When `Secondary Conflict`
- let Theater show second-order conflict markers
- Situation Frame should explicitly say this is command side-effect, not only command failure

### Absolute mistakes to avoid
- the page center turns into a log list
- follow-up actions sit far from the blocked stage
- propagation becomes a binary success/failure readout

---

## 7. Blueprint 05 — Recovery Window

### Command-cycle segment
**Verify recovery**

### Core decision
Is this cycle ready to close, or did it only improve temporarily?

### Must appear together above the fold
- Situation Frame
- Before / After Alignment View
- Drift Delta
- Rewrite Delta
- Escalation Delta
- Closure Judge
- Command Ribbon

### Above-the-fold blueprint
```text
┌──────────────────────────────────────────────────────────────┐
│ Command Horizon                                              │
├──────────────────────────────────────────────────────────────┤
│ Situation Frame                                              │
│ “how much alignment did this cycle actually restore?”        │
├──────────────────────────────────────────────────────────────┤
│ Before / After Alignment View                                │
├───────────────────────┬──────────────────────────────────────┤
│ Drift / Rewrite /     │ Closure Judge                        │
│ Escalation Deltas     │ close / continue / monitor           │
├──────────────────────────────────────────────────────────────┤
│ Command Ribbon                                               │
└──────────────────────────────────────────────────────────────┘
```

### First-7-seconds visual path
1. recovery judgment in Situation Frame
2. structural change in Before / After view
3. delta region to identify what improved only partially
4. Closure Judge for the next move

### Deformations under abnormal states

#### When `Recovery Incomplete`
- Closure Judge should bias toward continue
- delta region should emphasize remaining mismatch

#### When `Recovery Confirmed`
- before/after remains readable but stops dominating
- closure rationale must remain reviewable

#### When `False Recovery`
- the page must actively block the “looks prettier, close it” path
- Situation Frame should name the truth plane that remains unresolved

### Absolute mistakes to avoid
- turning it into a victory page
- not providing a clear continue path
- letting the user see only a total score and not residual mismatch

---

## 8. Continuity rules across blueprints

These five critical screens must preserve continuity:
1. moving from homepage to coordination should still feel like the same command chain,
2. moving from publish to ledger should feel like the same command continuing,
3. moving from ledger to recovery must not sever propagation from recovery,
4. moving from recovery back to homepage should settle into “recent governance outcome,” not erase the history.

---

## 9. Usage rules
If the team moves into Figma, Excalidraw, or frontend implementation, these five blueprints should be the first surfaces implemented.

Together they determine the most important thing about Cygnus:
**does it actually feel like a support leader’s mission-control, or just a content backend or agent workstation?**
