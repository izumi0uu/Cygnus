# Cygnus — Arkon Full-Port Baseline Migration Plan

> **Status: ✅ Completed (closed 2026-07).** P1 full-port, P2 runability recovery, and P2.5 internalization / upstream cutover are all closed (Jira CYG-23, CYG-24, CYG-69–91); the stop-line is enforced by the guard-test suite and `scripts/upstream_cutover_gate.py`. Kept as a migration-era decision record — it no longer describes the current mainline; see `docs/README.md` (session seam, CYG-92–96).

## 1. Purpose
This document freezes the engineering truth that has now changed:

**Cygnus no longer uses `domain-first selective extraction` as the current migration mainline. It now first establishes an Arkon full-port baseline.**

It answers:
- which Arkon code must now be migrated
- what is intentionally not in the current lane
- how import, runability, and support-verticalization remain separate phases

It does not answer:
- whether the final product is still a support knowledge operating system
- whether Nanobot remains the session layer

Those product boundaries have not changed.

## 2. Current settled decision
The current settled decision is:

1. **first migrate Arkon backend / runtime / worker / AI pipeline / retrieval / protocol into Cygnus**
2. **preserve upstream topology as much as possible during import**
3. **do not require Arkon product shell / admin shell / non-support pages in the current lane**
4. **separate runability recovery from source parity import**
5. **preserve existing `CYG-6 ~ CYG-17` as support verticalization stories**
6. **if the goal is to fully absorb Arkon into Cygnus and eventually delete the separate upstream codebase, open a dedicated internalization lane after P2**

## 3. Current mandatory scope
### 3.1 Layers that must enter the baseline
Corresponding Arkon paths:

- `app/main.py`
- `app/config.py`
- `app/worker.py`
- `app/database/*`
- `app/services/*`
- `app/ai/*`
- `app/ai/mrp/*`
- `app/ai/providers/*`
- `app/routers/*`
- `app/mcp/*`
- `app/utils/*`

### 3.2 Not mandatory in the current lane
- Arkon product shell
- admin shell
- non-support-first page layers
- any UI parity work added only to make the migration “look more complete”

## 4. Current phase model
### P0 — Migration Manifest & Boundary Freeze
Freeze:
- migration scope
- non-migration scope
- completion-state definitions

before Jira and docs drift again.

### P1 — Source Parity Import
First mirror Arkon’s code topology into Cygnus.

Completion here does **not** mean:
- the system is runnable
- dependencies are repaired
- business behavior is support-verticalized

It only means:
- the baseline entered the repo
- upstream topology now has a stable comparison surface

### P2 — Repair / Runability Recovery
Reconnect:
- dependency wiring
- config wiring
- storage / queue / db wiring
- API / worker / MRP resume path

Completion here does **not** mean:
- the Cygnus product is done

It only means:
- the baseline begins to regain minimum runnable behavior

### P2.5 — Internalization & Upstream Cutover
If Cygnus intends to keep Arkon only as internal substrate while deleting the separate Arkon codebase, it must additionally advance after P2:
- runtime identity residue cleanup
- app assembly convergence
- namespace / ownership freeze
- docs/tests/handoff truth sync
- deletion-readiness gate

Completion of this phase does not mean:
- support verticalization is complete
- optional shell parity is complete

It only means:
- Cygnus has started taking ownership of the substrate under its own engineering identity and entrypoint boundaries

### P3 — Support Verticalization
On top of P1 / P2 / P2.5, then execute:
- support knowledge objects
- governance surfaces
- support-domain review / publish / recovery

Existing `CYG-6 ~ CYG-17` belong here.

### P4 — Optional Product-Shell Parity
Only later, if truly needed, decide:
- which Arkon shell layers deserve parity
- which should remain backend-only references

#### Current P4 candidate classes
The current action is **classification first**, not shell implementation disguised as mainline work.

1. **support-relevant shell candidate**
   - an operator shell / chrome that directly hosts the support-governance mission control
   - a support reader shell only when it genuinely hosts review / publish / recovery / evidence-reading surfaces
   - the minimum sign-in / entry gate used to reach the support-governance control plane

2. **generic-product shell candidate**
   - generic auth / account center
   - admin / system settings shell
   - wiki home / library / editor surfaces whose primary subject is generic knowledge work

3. **non-support shell work that stays excluded by default**
   - marketing / landing / showcase pages
   - project / workspace / onboarding pages unrelated to support governance
   - parity-only UI added merely to make the migration “look complete”

#### Current exclusion / isolation rules
- `auth / admin / wiki` shells must currently be classified first; they do not automatically enter the mandatory P1/P2/P3 scope
- a shell candidate may only advance as a future P4 candidate when it **directly unblocks support verticalization**
- “visual completeness” or “the upstream product had this page” are not valid migration reasons
- non-support pages must stay isolated inside the deferred shell lane and must not flow back into the current substrate-migration mainline

## 5. Recommended Jira split
### Parent lanes
1. **[全量迁移] Arkon Full-Port Baseline**
2. **[修复跑通] Repair & Runability Recovery**
3. **[内化迁移] Arkon Internalization & Upstream Cutover**
4. **[延期] Optional Product-Shell Parity**

### Current 10 migration stories
1. Runtime topology import
2. Database import
3. Services import
4. Protocol import
5. MRP import
6. Knowledge substrate import
7. MCP / routers / backend surfaces import
8. Wiring recovery
9. Boot / smoke-run recovery
10. Import-vs-runability boundary freeze

## 6. Relationship to existing governance stories
### `CYG-6 ~ CYG-17`
Keep them.

They represent:
**Cygnus support verticalization / governance surfaces**

They no longer represent:
- the first engineering mainline
- Arkon baseline migration
- backend parity work

### `CYG-18 ~ CYG-22`
Preserve them as:
- bootstrap history
- selective-extraction reconnaissance

but no longer as the current migration strategy.

## 7. Completion truth
Four completion states must remain separate:

### A. Source parity completed
Means:
- Arkon baseline code has been imported

Does not mean:
- the system boots
- Cygnus is complete

### B. Runability recovered
Means:
- the baseline is minimally reconnectable, bootable, and smoke-runnable

Does not mean:
- support verticalization is complete

### C. Internalization completed
Means:
- Cygnus has started owning the substrate under its own engineering identity
- key runtime identity residue has been cut or explicitly isolated

Does not mean:
- support verticalization is complete
- optional shell parity is complete

### D. Cygnus verticalization completed
Means:
- the support-domain center, governance loops, and product surfaces are materially being built

### 7.1 Status-reporting contract
All future Jira comments, handoffs, logs, and completion notes must carry an explicit phase meaning:

- **P1** may only be reported as `source parity imported`, `baseline mirrored`, or `upstream topology preserved`
- **P2** may only be reported as `runability recovered`, `wiring restored`, or `boot/smoke-run regained`
- **P2.5** may only be reported as `internalized substrate`, `upstream cutover started`, or `Cygnus-owned runtime identity established`
- **P3** may only be reported as `support verticalization implemented` or `governance surface established`

The following must never be treated as interchangeable claims:
- code imported
- system runnable
- substrate internalized
- product support-verticalized

### 7.2 Jira parent-child interpretation contract
- `CYG-23` is the **P1 full-port baseline parent lane**; its child tickets prove imported substrate slices, not runtime recovery
- `CYG-24` is the **P2 runability recovery parent lane**; only its child tickets may claim restored wiring or startup paths
- `CYG-6 ~ CYG-17` remain **P3 support verticalization stories** and are not implicitly implemented just because P1 child tickets close
- parent-lane tickets like `CYG-23 ~ CYG-25` must not be misread as complete because one child ticket finished

## 8. One-sentence conclusion
**Cygnus product truth did not change; the engineering landing sequence did.**

The correct order is now:
**full-port baseline first, runability recovery second, support verticalization third.**
