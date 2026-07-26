# Cygnus — Arkon Internalization & Upstream Cutover Plan

> **Status: ✅ Completed (closed 2026-07).** The internalization / upstream-cutover lane is fully closed (Jira CYG-69–75, CYG-88–90); the preserve/audit/delete stop-line for the external checkout is enforced by `scripts/external_checkout_{preserve,audit}.py` and `scripts/upstream_cutover_gate.py`. Kept as a decision record; see `docs/README.md` for the current mainline (session seam, CYG-92–96).

## 1. Purpose
This document freezes a new engineering decision:

**when the goal is not only to import Arkon into Cygnus, but to fully internalize it as part of Cygnus and eventually delete the separate upstream codebase, Cygnus must open a dedicated post-P2 internalization lane.**

It answers:
- whether Cygnus should keep Arkon upstream identity residue long-term after P1/P2
- which work belongs to internalization / de-upstreaming rather than being shoved back into P1 import work
- how Cygnus can fully absorb Arkon without pulling product-shell parity back into the mainline

It does not answer:
- whether Cygnus is still a support knowledge operating system
- whether Nanobot is still the session layer
- whether optional shell parity should suddenly become the roadmap mainline

Those boundaries remain unchanged.

## 2. Current settled decision
The new settled decision is:

1. **after P1/P2, “keep upstream Arkon naming forever” is no longer the default end state**
2. **if the goal is full absorption plus eventual deletion of the separate upstream codebase, Cygnus enters a dedicated P2.5 internalization lane**
3. **the internalization lane is not shell parity and not support verticalization**
4. **renames, entrypoint convergence, identity cutover, and deletion readiness must happen in P2.5 rather than being misreported as P1 import work**
5. **Cygnus still preserves the product relationship of “Arkon = internal substrate,” but engineering ownership converges into Cygnus itself**

## 3. Why this lane must exist separately
Without this lane, the team will blur three different truths again:

- **P1**: whether source parity was imported from upstream code
- **P2**: whether minimum runability and smoke-run behavior were recovered
- **P2.5**: whether Cygnus has actually taken ownership of naming, entrypoints, boundaries, and deletion readiness for the substrate

Without P2.5, common drift looks like:
- leaving `arkon` identity residue inside runtime / MCP / default config indefinitely
- claiming “full-port completed” while still keeping dual entrypoints or dual truth surfaces
- letting product-shell parity steal attention before substrate ownership is actually transferred

## 4. Phase placement
### P2.5 — Internalization & Upstream Cutover
This lane sits:
- **after P2**: because it depends on minimum runability already being restored
- **before or alongside early P3**: when the goal is to delete the separate Arkon base, substrate ownership should become explicit first
- **before P4**: because this is not product-shell parity; it is substrate ownership transfer

### It does not mean
- support verticalization is complete
- optional shell parity has been decided
- Cygnus should copy all Arkon UI surfaces

### It really means
- Arkon as an “external upstream project identity” starts being internalized into Cygnus
- Cygnus gains engineering naming ownership, entrypoint control, and boundary interpretation authority over this substrate
- future deletion of the separate Arkon repo no longer lacks migration semantics or acceptance boundaries

## 5. Mandatory work cuts
### 5.1 Identity residue cleanup
Cygnus must clean up leftover runtime signals that still imply “Arkon is the runtime owner,” for example:
- default sender names / example config aliases / server aliases
- permission sentinels or runtime identifiers still named `arkon`
- outward-facing identity strings that mislead users or downstream agents

### 5.2 App assembly convergence
Cygnus must decide and converge:
- the public-entry relationship has already converged onto `cygnus.runtime.main`
- `cygnus/api/*` has been removed as a legacy package
- which app is the outward-facing main entry
- which surfaces remain baseline-preservation layers and which are now Cygnus’s own control plane

### 5.3 Namespace & ownership freeze
Cygnus must freeze:
- which upstream topology remains under `cygnus/runtime/*` as substrate reference
- which capabilities now belong to Cygnus-owned naming and Cygnus-owned boundaries
- which naming residue is only transitional debt and must continue shrinking


### 5.3.1 Package boundary freeze (current long-term interpretation)
After `identity` and `assembly` convergence, P2.5 now freezes the package semantics as follows:

- `cygnus/runtime/*` = **runtime / app shell / imported upstream topology reference**
  - this layer continues to preserve the upstream-aligned FastAPI app, worker, database, services, routers, MCP, utils, and scripts topology
  - its job is to host the imported runtime shell and infrastructure wiring; it does not mean “all Cygnus backend truth”
  - this layer was converged into `runtime` in `CYG-75`; any further structural rework now belongs to a new architecture-convergence action, not a P1 source-parity action

- `cygnus/substrate/*` = **Cygnus-owned substrate contracts**
  - this layer holds provider-neutral protocol, tool runtime, pipeline phase/checkpoint, and durable workflow primitives
  - it is not a second app shell and does not own the FastAPI / worker / database entrypoints
  - `substrate` is a long-term layer, not a temporary facade
  - the currently frozen source-compilation primitive cluster includes `cygnus.substrate.source_outline`, `cygnus.substrate.source_images`, and `cygnus.substrate.source_text`
  - `runtime` may still call these primitives for worker / router / storage assembly, but it no longer owns their extraction semantics

- `cygnus/api/*` = **removed legacy package**
  - no Python modules remain under `cygnus/api/`
  - `cygnus.api.*` must not reappear as an internal or external import path

- `cygnus/domain/*` = **support-domain contracts / object vocabulary**
  - Answer Card / Policy Rule / Troubleshooting Flow / Escalation Route style support object truth freezes here

- `cygnus/evidence/*` = **evidence normalization and record layer**
  - raw support evidence, freshness, and source-record normalization/recording live here

- `cygnus/retrieval/*` = **object/evidence retrieval and source-trace query layer**
  - object retrieval, evidence retrieval, source-trace resolution, and semantic embedding persistence belong here rather than to the runtime shell owner

- `cygnus/review/*` / `cygnus/publish/*` / `cygnus/recovery/*` = **governance control-plane modules**
  - review, publish, and recovery are Cygnus-owned governance control planes, not loose residue waiting to be shoved back into runtime

- `cygnus/integrations/*` = **external/session-facing integration adapters**
  - Nanobot/MCP-facing and other outward adapter surfaces belong here rather than being mistaken for the product core

- `cygnus/workflows/*` = **workflow composition layer, not generic runtime shell**
  - this layer composes governance workflows and must not regrow into a second roaming session runtime

### 5.3.2 Import policy freeze (current long-term execution rule)
Once package ownership is frozen, internal imports must also converge to one rule set:

- `cygnus.runtime.main` is the canonical app owner
- `cygnus.runtime.governance_router` is the sole governance-router owner
- `cygnus.runtime.config` and `cygnus.runtime.services.auth_service` own config/auth
- `cygnus.api.*` must not reappear as a default internal import
- `cygnus.api.auth`, `cygnus.api.config`, `cygnus.api.governance_router`, and `cygnus.api.app` are no longer allowed as internal dependencies
- no new internal implementation may reintroduce the old `app.*` namespace

This means:
- a compatibility facade may keep a minimal shell, but it must not regrow a second owner
- tests must lock the no-backflow paths instead of relying on convention only
- once a facade has no internal callers, it must be deleted or reduced further

Additional interpretation:
- `review / publish / recovery / retrieval / domain / evidence / integrations / workflows` represent Cygnus-owned domain and control-plane modules; living outside `runtime` does not make them boundary violations
- the real convergence goal is not “move everything under runtime”, but “stop misreading runtime as the entire product backend”
- the first package rename completed in `CYG-75`; any later tree reshaping should happen through a new architecture-convergence ticket rather than quietly regrowing parallel naming truth

### 5.4 Docs / tests / handoff truth sync
Cygnus must synchronize:
- handoff docs
- smoke / boundary tests
- agent execution context
- Jira narrative

Otherwise the repo will drift back into “the code is internalized but the docs still describe two different truths.”

### 5.5 Upstream deletion readiness
Cygnus must define the minimum acceptance bar before deleting the separate Arkon codebase:
- no external Arkon source import dependency
- no critical runtime identity residue
- entrypoint, naming, and boundary relations documented explicitly
- Jira no longer assumes “continue depending on external Arkon” as the default premise

#### 5.5.1 Readiness gate checklist
Only when all gate items remain green may “delete the separate Arkon codebase” be treated as an executable step:

1. **Code residue gate**
   - no external `arkon` runtime residue remains under `cygnus/` and `frontend/`
   - no `__arkon_requires__`, `arkon@localhost`, or `import arkon` style residue remains

2. **Compat shrink gate**
   - `cygnus/api/*` has been removed
   - no Python modules remain under `cygnus/api/`
   - transitional owners such as `cygnus/api/__init__.py`, `cygnus/api/app.py`, `cygnus/api/auth.py`, `cygnus/api/config.py`, and `cygnus/api/governance_router.py` must not reappear

3. **Owner truth gate**
   - `cygnus.runtime.main` remains the canonical public app owner
   - ownership for `cygnus.runtime.governance_router`, `cygnus.runtime.config`, and `cygnus.runtime.services.auth_service` has not regressed

4. **Narrative gate**
   - agent / Jira / handoff language continues to describe cutover as `internalized substrate` / `upstream cutover started`
   - cutover must not be described as shell parity complete or support verticalization complete

5. **Executable verification gate**
   - `scripts/upstream_cutover_gate.py` passes
   - targeted P2.5 boundary tests pass

#### 5.5.2 External checkout deletion discipline
- if a standalone external Arkon checkout still exists on disk, first use `scripts/external_checkout_preserve.py` to preserve local ahead commits, dirty worktree state, and untracked files before discussing physical deletion
- `scripts/external_checkout_audit.py --fail-if-found` is the physical-deletion proof that no external checkout remains; the preserve step only captures state and is not deletion proof
- if the audit still finds a standalone checkout, the repo may only claim `upstream cutover started`, not that the external base has already been fully deleted

The purpose of this gate is not to claim the product is finished. It is to prove:
- deletion of the separate upstream codebase now has a concrete stop-line
- downstream no longer assumes “continuing to depend on external Arkon” as the default premise
- cutover completion language does not drift into P3 or P4 claims

## 6. Completion truth
Cygnus must now distinguish four completion states:

### A. Source parity completed
Means:
- the Arkon baseline code is imported

Does not mean:
- the system is booted
- Cygnus has taken engineering identity ownership of the substrate

### B. Runability recovered
Means:
- the baseline is minimally wireable, bootable, and smoke-runnable

Does not mean:
- Cygnus has completed naming / entrypoint / boundary ownership transfer

### C. Internalization completed
Means:
- Cygnus has started owning the substrate under its own engineering identity
- key runtime identity residue has been cut or explicitly isolated
- future deletion of the separate Arkon base now has a concrete execution surface

Does not mean:
- support verticalization is complete
- optional shell parity is complete

### D. Cygnus verticalization completed
Means:
- support-domain subject matter, governance loops, and product surfaces are genuinely being built

### 6.1 Status-reporting contract
In Jira comments, handoffs, logs, and completion notes, downstream agents must now use explicit phase language:

- **P1**: `source parity imported` / `baseline mirrored` / `upstream topology preserved`
- **P2**: `runability recovered` / `wiring restored` / `boot or smoke-run regained`
- **P2.5**: `internalized substrate` / `upstream cutover started` / `Cygnus-owned runtime identity established`
- **P3**: `support verticalization implemented` / `governance surface established`

These four statements must not be collapsed into synonyms:
- code imported
- system runnable
- substrate internalized
- product verticalized

## 7. Current Jira split recommendation
### Parent lanes
1. **[全量迁移] Arkon Full-Port Baseline**
2. **[修复跑通] Repair & Runability Recovery**
3. **[内化迁移] Arkon Internalization & Upstream Cutover**
4. **[延期] Optional Product-Shell Parity**

### Recommended first-wave internalization leaf stories
1. runtime identity residue cleanup
2. public app assembly convergence
3. namespace / ownership freeze
4. docs / tests / handoff truth sync
5. deletion-readiness gate

## 8. One-sentence conclusion
**If Cygnus truly intends to absorb Arkon and then delete the separate upstream codebase, P1/P2 are not enough; it needs an explicit P2.5 internalization lane.**
