# Support Brain for SaaS — Three Core Wireframe Variants

## 1. What this document is
This document turns `Command Center` and `Queue / Topic Coordination Board` into **three structurally different** low-fi wireframe directions.

These are not three minor layout tweaks. They are three different organizing logics:
- **Variant A — Briefing Stack**
- **Variant B — Command Corridor**
- **Variant C — Risk Atlas**

Diagram files:
- `docs/diagrams/cygnus-core-variant-briefing-stack.excalidraw`
- `docs/diagrams/cygnus-core-variant-command-corridor.excalidraw`
- `docs/diagrams/cygnus-core-variant-risk-atlas.excalidraw`

---

## 2. The core difference among the three

| Variant | Structural protagonist | Best for | Risk | My read |
|---|---|---|---|---|
| Briefing Stack | morning briefing hierarchy | daily leadership scan, operational rhythm | can drift toward a smart dashboard | safest baseline |
| Command Corridor | single command runway | command-cycle continuity, governance sequencing | can feel too process-centric | strongest command posture |
| Risk Atlas | risk terrain / battle map | incident, drift, spread reasoning | higher cognitive load | most differentiated |

---

## 3. Variant A — Briefing Stack

### Core idea
Make the homepage a true morning support briefing.
The user sees the 3 highest-value interventions first, then spread scope and recovery state.

### Strengths
- easiest to understand
- best fit for daily support-lead use
- hardest to execute badly

### Risk
- if visually too conservative, it will gradually become a premium BI homepage

### What is worth keeping
- the homepage Priority Stack hierarchy
- the coordination page’s “relation left / consequence right” structure

---

## 4. Variant B — Command Corridor

### Core idea
Make the core surfaces feel like one continuous command runway.
The user is not browsing modules; they are moving along a command lane.

### Strengths
- strongest Observe → Frame → Route → Change continuity
- least like a normal dashboard
- aligns naturally with future command history and propagation views

### Risk
- if pushed too far, it may look like a workflow orchestrator
- weaker than Variant C for terrain-style risk reasoning

### What is worth keeping
- the central command runway
- left/right sidecars for evidence, recovery, and ownership

---

## 5. Variant C — Risk Atlas

### Core idea
Make the geography of support-system imbalance the protagonist.
Instead of reading lists first, the user reads the terrain first.

### Strengths
- strongest mission-control identity
- best fit for release drift, incident spread, and audience-conflict situations
- least likely to be mistaken for a CMS or review-queue product

### Risk
- highest design difficulty
- higher first-time learning cost
- if the abstraction is weak, it could feel flashy rather than useful

### What is worth keeping
- the atlas + floating command islands on the homepage
- the battlefield + authority dock on coordination

---

## 6. My recommendation
If this is moving toward the real product, my recommendation is:

### Recommended blend
- **Command Center: mix Variant A + Variant C**
  - keep A’s briefing hierarchy
  - borrow C’s atlas feeling without letting it overpower readability

- **Coordination Board: mix Variant B + Variant C**
  - keep B’s command continuity
  - borrow C’s battlefield feel and authority dock

### I would not ship any one variant untouched
Because:
- A alone is safe but may be under-differentiated
- B alone is powerful but may be misread as orchestration software
- C alone is distinctive but highest-risk for a first implementation

---

## 7. Suggested next move
If you pick one direction or a blend, the next highest-value step is:
1. compress the chosen direction into a **single-page detailed blueprint**
2. create a **denser Excalidraw pass** for the hero region (especially the homepage)
3. only then move into frontend component contracts
