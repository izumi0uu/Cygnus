# Cygnus — Story-to-Substrate Mapping Plan

> **Status: still useful as mapping reference; the phase ledger is closed (2026-07).** P1/P2/P2.5 and all three P3 waves of CYG-6–17 are closed; the "current engineering entry" conclusion in §9 is outdated. The current mainline is the session seam (CYG-92–96), whose engineering prerequisite is switching the governed plane from sample fixtures to internalized substrate truth; see `docs/README.md`.

## 1. Purpose
This document realigns **the Jira governance-product stories** with the **Arkon → Cygnus engineering migration phases**.

It does not answer “what is the product?” and it does not answer “how is a module implemented?”
It answers:

**when does a governance story become genuinely worth building, and which Arkon substrate phase must exist before that happens.**

## 2. Why this document had to change
Cygnus changed its engineering mainline:

- old mainline: `domain-first selective extraction`
- new mainline: **Arkon full-port baseline → runability recovery → support verticalization**

So this mapping document can no longer treat `CYG-6 ~ CYG-17` as the current first-wave engineering track.

The correct structure is now:
- `CYG-23+` = current engineering mainline
- `CYG-6 ~ CYG-17` = future **P3 support verticalization** governance surfaces
- `CYG-18 ~ CYG-22` = preserved bootstrap history, not current migration truth

## 3. The two order lines must stay separate

### 3.1 Product order line
This is the order users should eventually feel as governance migration:
1. Review becomes Command Brief
2. Publish becomes Blast-Radius Control
3. Ticket / Drift becomes Review Pressure
4. Propagation becomes Recovery Proof

### 3.2 Engineering order line
This is the order Cygnus must now follow:
1. **P0 — Migration Manifest & Boundary Freeze**
2. **P1 — Source Parity Import**
3. **P2 — Repair / Runability Recovery**
4. **P2.5 — Internalization & Upstream Cutover**
5. **P3 — Support Verticalization**
6. **P4 — Optional Product-Shell Parity**

### 3.3 Correct interpretation
So the correct relationship is not:
- `CYG-6` appears early in Jira, so build that page first

It is:
- `CYG-6 ~ CYG-17` are the future product mainline for support verticalization
- but they only become truly buildable after **P1/P2 import and reconnection are materially in place**

## 4. What each phase contributes to the mapping

### P0 — Migration Manifest & Boundary Freeze
Provides:
- migration-scope definition
- non-migration-scope definition
- boundary definitions between import / runability / verticalization

Without it, Jira easily mixes:
- product stories
- full-port tasks
- runability repair tasks

into one indistinct backlog.

### P1 — Source Parity Import
Provides:
- the Arkon backend/runtime/worker source topology
- provider-neutral protocol and provider adapters
- upstream MRP pipeline, wiki/compiler/retrieval, routers/mcp/services/database topology

Without it, any governance UI risks collapsing into:
- fake command surfaces
- fake propagation feedback
- fake pressure intake

### P2 — Repair / Runability Recovery
Provides:
- reconnected dependency/config/storage/queue/db wiring
- minimally bootable API/worker/MRP resume behavior

Without it, P3 stories still remain mostly:
- fixtures
- static frontends
- control surfaces with no recoverable runtime truth underneath

### P2.5 — Internalization & Upstream Cutover
Provides:
- runtime identity residue cleanup
- app assembly convergence
- namespace / ownership freeze
- docs/tests/handoff truth sync
- a concrete cutover surface before deleting the separate Arkon codebase

Without it, the team easily remains stuck in:
- dual entrypoints / dual truth surfaces
- runtime residue still exposing `arkon` identity
- the false assumption that “full-port completed” already means “Cygnus fully owns the substrate”

### P3 — Support Verticalization
Provides:
- support-native object subject matter
- governance surfaces for review/publish/recovery
- Cygnus’s own support-domain control plane

Existing `CYG-6 ~ CYG-17` belong here.

### P4 — Optional Product-Shell Parity
Provides:
- later decision space for Arkon shell parity

It is not a prerequisite for the current P1/P2/P3 path.

## 5. Overall story-to-phase mapping

| Jira | Story summary | Earliest start | Truly matures in | Main dependencies |
|---|---|---:|---:|---|
| CYG-6 | Review opens on governance risk first | P3 (late-early) | P3 | review substrate, risk ranking, retrieval trace, command surface |
| CYG-7 | Every review item explains why-now first | P3 (late-early) | P3 | evidence context, source trace, lifecycle context |
| CYG-8 | Review order can be restacked/rerouted/escalated | P3 (late) | P3 / P4 | review queue semantics, command chain, residual trace |
| CYG-9 | Publish previews blast radius before action | P3 | P3 / P4 | audience model, publish policy, propagation surfaces |
| CYG-10 | Publish is more than approve/reject | P3 | P3 / P4 | action granularity, variant routing, governance commands |
| CYG-11 | Publish shows propagation success/stall | P3 | P3 / P4 | publish ledger, propagation state, supporting surfaces |
| CYG-12 | Rewrites/tickets rise into review pressure | P3 (early) | P3 | evidence clustering, object proposal, pressure intake |
| CYG-13 | Drift can force an urgent review path | P3 | P3 / P4 | drift model, freeze/restrict path, refresh governance |
| CYG-14 | Source failure becomes governance blindness | P3 (early) | P3 | source trace, evidence health, object impact mapping |
| CYG-15 | Supporting surfaces report behavior change | P3 (mid-late) | P3 / P4 | downstream trace, feedback ingestion, command-result linkage |
| CYG-16 | Recovery Window answers whether the system became more aligned | P3 (late) | P4 | workflow trace, metrics, before/after recovery signals |
| CYG-17 | Compare multiple open loops to choose the next move | P3 (late) | P4 | multi-loop state, residual risk comparison, governance overview |

## 6. Engineering prerequisite mapping

### 6.1 Capabilities directly unlocked by P1
After P1 full-port import, Cygnus should at least contain:
- main/config/worker topology
- database / services / routers / mcp baseline
- ai/providers/agent protocol baseline
- ai/mrp pipeline baseline
- wiki/compiler/retrieval/source trace baseline

This is not for immediate runability.
It is to prevent P3 from being hollow.

### 6.2 Capabilities directly unlocked by P2
After P2 runability repair, Cygnus begins to regain:
- smoke-runnable API/worker behavior
- minimally reconnectable queue / storage / db behavior
- runtime validation for pipeline phase / resume truth

That means:
- P3 command surfaces can start pointing at real state
- P3 propagation / recovery can gradually move beyond static expression

### 6.3 Capabilities directly unlocked by P2.5
After P2.5 internalization, Cygnus begins to regain:
- substrate ownership under `Cygnus`'s own engineering identity
- less runtime identity residue and clearer public-entry boundaries
- a verifiable cutover readiness surface before deleting the separate Arkon codebase

That means:
- later P3 work no longer sits on the transitional truth of “still depends on external Arkon identity”
- any support-native refactor can stand on a more stable Cygnus-owned substrate

## 7. Recommended build waves for `CYG-6 ~ CYG-17`

### First batch (P3 early wave)
1. **CYG-12** — ticket / rewrite becomes review pressure
2. **CYG-14** — source failure = governance blindness
3. **CYG-6** — review command brief
4. **CYG-7** — why-now frame

Why:
- these four best express Cygnus as a support governance center grown from the Arkon substrate
- they emphasize intake / trace / review before the most complex recovery orchestration

### Second batch (P3 middle wave)
5. **CYG-9**
6. **CYG-10**
7. **CYG-11**
8. **CYG-15**

Why:
- this batch begins to require real publish consequences and downstream result linkage
- it benefits from P1/P2 having already given publish / propagation a real baseline

### Third batch (P3 late / P4-ready wave)
9. **CYG-13**
10. **CYG-16**
11. **CYG-17**
12. **CYG-8**

Why:
- these are closest to durable governance orchestration
- they are easiest to fake early as dashboards or pseudo-command centers
- they fit better once P3 matures and, if needed, later absorbs P4 shell/orchestration support

## 8. Relationship between `CYG-23+` and `CYG-6~17`

### `CYG-23`
Represents:
- the parent lane for **P1 full-port baseline**

### `CYG-24`
Represents:
- the parent lane for **P2 repair/runability**

### `CYG-25`
Represents:
- the deferred parent lane for **P4 optional shell parity**

### `CYG-6 ~ CYG-17`
Represent:
- **P3 support verticalization / governance surfaces**

So the current execution order should be:
- first advance the migration tasks linked to `CYG-23/24`
- if the goal is to fully absorb Arkon and delete the separate upstream codebase, enter the P2.5 internalization lane next
- only then start treating `CYG-6~17` as the main project implementation line

## 9. One-sentence conclusion
**The governance stories still matter, but they are no longer the first engineering entry point; the current engineering entry path is Arkon full-port baseline import → runability recovery → (when full absorption is the goal) internalization.**

