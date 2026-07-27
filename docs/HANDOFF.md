# HANDOFF — Cygnus Frontend (rebuilt 2026-06-22; trimmed 2026-06-27; synced 2026-07-26)

> **Frontend-only handoff.** Backend governance/architecture is mentioned only where the
> frontend depends on it as an API contract. Status reflects the working tree as of this
> writing — verify before acting.
>
> Trim policy: keep SPA-facing contracts (endpoint paths the SPA calls, return shapes the
> SPA renders, the `persisted:false` honesty rule, auth model). Cut backend internals
> (boot commands, config/auth ownership, executor implementation, in-process stores,
> fixture locations, backend module mappings).

## 1. What the frontend is

A React + Vite + TypeScript SPA, single-origin with the Cygnus backend (Vite proxies
`/api` → `127.0.0.1:8077`). Visual system is the **blueprint / engineering-drawing**
aesthetic: grid-paper background, thin lines, sharp corners, monospace labels, `DWG-*`
drawing numbers, `SEC-*` section codes, tolerance chips. i18n is **zh-first, en real**
(not a stub). Dark/light themes via `ThemeProvider`.

- Stack: React 19, react-router-dom, react-force-graph-2d, lucide-react, i18next, Tailwind v4.
- Animation: `motion/react` (framer-motion) — used by charts, PlotterPanel, DimensionLines, mastermind.
- Auth: JWT bearer in `localStorage` (`cygnus_token`), injected by `authApi()` wrapper.
- No build-time secrets in the bundle; all data via authenticated `/api` calls.

## 2. Page inventory (all blueprint unless noted)

| Page | Route | Blueprint | bp-refs | Notes |
|------|-------|-----------|---------|-------|
| Overview | `/console` (index) | ✅ | 45 | DWG-01, title block, annotation table, SEC-A dimension lines |
| ReviewQueue | `/console/queue` | ✅ | 31 | Risk inbox + detail drawer (PlotterPanel reveal); CmdButton → PublishPreviewModal |
| KnowledgeObjects | `/console/objects` | ✅ | 40 | Force graph + **traceability drawer** (projection-aware) |
| AudiencePublish | `/console/audience` | ✅ | 29 | Audience × risk, action presets |
| Propagation | `/console/propagation` | ✅ | 29 | Propagation ledger + status lanes (SEC-F) |
| CoverageDrift | `/console/drift` | ✅ | 16 | Drift watch cards |
| SourcesEvidence | `/console/sources` | ✅ | 14 | Source-blindness health board |
| RecoveryDetail | `/console/recovery/:commandId` | ✅ | 13 | Recovery window + reality check (dimension lines) |
| Login | `/login` | ✅ | 20 | DWG-000 access-control sheet, PlotterPanel reveal, bp-cmd submit |
| Placeholder | `/console/audit` | ✅ | 7 | SEC-G reserved-sheet (no backend endpoint yet) |
| PlotterDemo | `/demo/plotter` | ✅ | 8 | Standalone PlotterPanel demo, auth-gated |
| Mastermind | `/demo/mastermind` | ✅ | 30 | Blueprint game page, auth-gated (engine in `@/game/mastermind`) |
| Landing | `/` | ❌ (by design) | 0 | Independent dark brand page, framer-motion skiper6 roll, intentionally not blueprint |

13 routed pages total: 2 public (`/`, `/login`); both `/demo` pages and all 9 console
pages sit behind `RequireAuth` (demos gated in `7ee23eb`). The full drawing set is
visually consistent: every console surface + Login + Placeholder + both demos is
blueprint. Only Landing stays dark-brand on purpose.

## 3. Governance write path (the contract that must stay honest)

`PublishPreviewModal` → `POST /api/publish/apply` → returns `PublishApplyResult`
(`opened/removed/held` bindings + `action_log`, `rehearsal`, `persisted`).

**Critical honesty contract:** `persisted: false, rehearsal: true`. The UI must never
claim durable post-publish state. Enforced in three places:
- type: `PublishApplyResult.rehearsal: boolean` / `.persisted: boolean` (`api.ts`)
- result panel: renders the `notPersisted` note only when `!applyResult.persisted`
  (`PublishPreviewModal`, i18n key `publish.notPersisted = "未持久化（演练）" / "not persisted (rehearsal)"`)
- traceability drawer: PROJECTION block carries `persisted={trace.projection.persisted}`

- `POST /api/publish/apply` requires **admin**; all other `/api/*` require only an
  authenticated user. (How the backend enforces this is backend's concern — the SPA just
  sends the bearer token and treats the response shape as the contract.)
- `applyPublishAction(objectRef, actionKey)` in `api.ts` is the only write caller.

## 4. Traceability + projection (post-apply what-if)

`GET /api/traceability/{object_id}` returns the object→evidence→source→freshness chain,
**plus an inline `projection` field** (`projection: PublishApplyResult | null`).

- `projection = null` if no apply, or the snapshot for that object after an apply.
- `KnowledgeObjects` drawer's `TraceabilitySection` renders a **PROJECTION** block
  (opened/removed/held, tagged `not-persisted/rehearsal`) when `trace.projection` is present.

This is the correct shape per the invariant **"approval truth lives in Cygnus"**: projection
truth is backend-held, not SPA session state. (An earlier attempt used a frontend
`PublishActionProvider` context — that was deleted in `97a0fde` because it violated the
invariant. Do not reintroduce SPA-held governance truth.)

> How projection truth is held server-side, and the proposal-id↔object-id bridge, are
> backend implementation details and are intentionally not documented here. The SPA-facing
> contract is only: call `applyPublishAction`, then `fetchTraceability(objectId)` may
> return a `projection` snapshot for that object.

## 5. Auth model (SPA-facing)

- JWT bearer in `localStorage` key `cygnus_token`, injected by `authApi()`.
- `AUTH_BASE = ''` (same-origin via Vite proxy).
- Two auth calls in `lib/auth.tsx`: `POST /api/auth/login` (returns `{access_token, user}`)
  and `GET /api/auth/me` (mount-effect identity + `refresh()`).
- No `DEV_DEFAULT_LOGIN` bypass remains — real `/api/auth` calls only.
- Local default credentials come from backend settings; the SPA does not hardcode them.
  (Backend boot/config is out of scope for this handoff.)

## 6. Revision clouds (canvas overlay)

`RevisionClouds.tsx` — SVG clouds positioned by a hash of notification id, derived from
the command-center `priority_stack` (read-first by severity via `commandCenterSource`).
- **Max 5 clouds** (`MAX_CLOUDS = 5`, slices the already-sorted list).
- **Click-outside-to-close** the detail panel: document-level `pointerdown` listener,
  guarded by `closest('.bp-cloud, .bp-cloud-panel')`, so the canvas stays interactive.
- `CloudSummaryButton` (coordinate-bar summary) and `NotificationBell` (bell dropdown)
  **coexist** in the coordinate bar. `CloudSummaryButton` does NOT replace
  `NotificationBell` — the old comment in `RevisionClouds.tsx` saying so is stale.
  The cloud-visibility toggle lives inside the `NotificationBell` dropdown.

## 7. Component map

- `components/layout/AppShell.tsx` (341 LOC) — directory panel + coordinate bar + canvas + zoom + clouds.
- `PublishPreviewModal.tsx` (367 LOC) — blast-radius modal (portal); APPLY + propagation link; result panel.
- `CmdButton.tsx` (57 LOC) — opens PublishPreviewModal for publish-family commands (`PUBLISH_COMMANDS`).
- `RevisionClouds.tsx` (224 LOC) — see §6; also exports `CloudSummaryButton`.
- `NotificationBell.tsx` (126 LOC) — bell dropdown: notification list, unread count, click-outside/Escape close, cloud toggle.
- `PlotterPanel.tsx` (285 LOC) — pen-plotter reveal (see §9, Idea 1; **implemented**).
- `DimensionLines.tsx` (429 LOC) — caliper-cursor dimension annotations (see §9, Idea 2; **implemented**).
- `CommandPalette.tsx` (197 LOC) — ⌘K palette: sections + risks + coordinate jump.
- `charts/` — 14 chart files (pie/context/slice, stat-flow, reveal-clip, motion utils).
- `mastermind/` — 4 files: `GuessRow`, `Palette`, `Peg`, `ResultOverlay` (framer-motion).
- `ui/button.tsx`, `Segmented`, `Stat`, `Skeleton` (+`PageSkeleton`), `ThemeToggle`,
  `LangToggle`, `RequireAuth`.
- `lib/`: `api.ts` (613 LOC, all fetchers via `authApi`), `auth.tsx`/`authApi.ts`,
  `vocab.ts`, `notifications.ts`, `theme.tsx`, `zoom.tsx`, `toast.tsx`, `useFocusTrap.ts`, `utils.ts` (`cn`).
- `game/mastermind.ts` (172 LOC) — framework-agnostic game logic (secret code, feedback, types).

## 8. Things that are NOT done / known broken

1. **Projection is single-object, single-process** — acceptable only because
   `persisted:false` is explicit; do not treat projection as a truth source.
   (Backend storage details are out of scope here.)
2. **Browser-level verification still owed** — APPLY→drawer→projection render and
   revision-cloud click-outside/5-cap are API-level verified only (no browser-automation
   dep installed).
3. **Placeholder audit page** — blueprint-styled but has no backend endpoint; it's a
   reserved sheet (SEC-G) by design until that surface exists.

### 8.1 Governed observation truth (CYG-97)

The SPA consumes typed, machine-code `observation` payloads from `api.ts`; `ObservationBanner` localizes state/reason/signal codes in both zh and en. It is presentation-only and must not derive risk or issue commands.

- `/console/queue`: partial review coverage; source failure facts and complete governance risks render in separate sections. An empty stack under partial coverage does **not** mean every detector is clear.
- `/console/drift`: unavailable detector coverage; never render the old “no drift risk” copy unless the API is `ready`.
- `/console/sources`: `SourceFailureObservation` cards display error, visible linked refs, timestamp, and `IMPACT · UNKNOWN`; they have no audience, surface, owner, or command affordance.
- `/console/objects`: an empty `nodes` array renders a same-size blueprint explanation instead of mounting `ForceGraph2D`.
- `/console`: API-driven `rehearsal:true` renders a prominent non-dismissible banner before recovery loops.

Compose-backed DB smoke passed on 2026-07-26 with the seeded administrator. Deterministic global ready/error sources plus a support Wiki page proved nonempty graph, partial queue/source observations, unavailable drift, and the rehearsal banner; a zero-department viewer did not receive the cross-department node/source or its traceability record (404). After seed cleanup, `/console/objects` rendered its same-size no-canvas explanation. Browser checks found no page-console errors; dark-mode toggle and keyboard focus both worked. `scripts/docker_smoke.sh` now bypasses ambient proxies for its loopback-only health checks.

## 9. Commits that got us here (this session)

```
97a0fde fix(governance): harden control-plane truth boundaries   # auth+CORS+config+projection_store
124838c feat(governance): bridge publish write-path to traceability id
b9d288e feat(frontend): project post-apply trace state in traceability drawer
1104411 feat(frontend): blueprint the Placeholder reserved-sheet state
bf8ecb2 feat(frontend): blueprint the Login page as access-control sheet
dc819a4 feat(frontend): cap revision clouds at 5 and click-outside to close
c3040de feat(governance): wire publish write path and evidence traceability
8f8e336 feat(frontend): publish governance flow and SaaS page rebuilds
```

## 10. Invariants the frontend must preserve (from CLAUDE.md)

- **Approval truth lives in Cygnus** → never hold governance/projection truth in SPA state.
- **RAG truth lives in Cygnus** → traceability is backend-derived, not client-assembled.
- **Nanobot is the only general-purpose session loop** → the frontend is a control surface,
  not a second agent runtime.
- Blueprint aesthetic is the settled visual system; Landing is the only intentional exception.

---

## 11. Visual Design System (Blue DNA, light + dark)

Verified accurate against `index.css` + `theme.tsx` + `index.html`.

**Light palette (`:root`):**
- Background `#f6f8fc`, Card `#ffffff`, Primary `#185ee0`, Accent tint `#e6eef9`
- Border `#e7e9f0`, Foreground `#1a1d24`, Faint `#8b91a0`
- Risk signals: urgent `#e5484d`, high `#f76808`, medium `#e8930c`, ok `#30a46c`

**Dark palette (`.dark`) — not a mechanical inversion (GitHub Dark Dimmed / Linear flavor):**
- Background `#101113` (neutral charcoal, not blue-black)
- Card `#191b1e`, Sidebar `#0b0c0d` (darker than content for depth)
- Primary `#2f6fe6` (slightly lifted, not neon), Border `#25272b` (near-invisible — elevation via bg delta)
- Risk signals softened: urgent `#db5158`, high `#d97a45`, medium `#c69438`, ok `#3ba070`

Anti-FOUC script in `index.html` reads `cygnus-theme` from `localStorage` and adds `.dark`
before React renders. `ThemeProvider` (`theme.tsx`) supports `light | dark | system`,
persists to `cygnus-theme`, listens to `prefers-color-scheme` when `system`.

**Physical Toggle Buttons** (plain CSS):
- `ThemeToggle`: day/night checkbox with moon texture + warm yellow `#fdea7b`
- `LangToggle`: skewed ON/OFF slider, green `#86d993` when EN, gray `#888` when 中

## 12. Blueprint Interaction Features

Verified against `AppShell.tsx` + `zoom.tsx` + `CommandPalette.tsx`.

**P1: Zoom Navigation**
- Zoom controls in the coordinate bar (CAD style): `[-] [scale] [+] [FIT]`. The scale label
  is `${zoom.toFixed(2)}:1` (e.g. `1.00:1`, `0.75:1`), zoom range 0.5–2.0, step 0.15.
- Mouse wheel: `Ctrl/⌘ + wheel` = zoom toward cursor; plain wheel = native scroll.
- Drag pan: limited to ~25px (`MAX_PAN = 25`) with soft dampening (`overshoot * 0.15`) +
  **spring-back to origin on release** (`resetView()` on mouseUp).
- Dynamic grid: grid density scales with zoom (`CanvasGrid`, major 80px / minor 20px × zoom).
- Keyboard: `+`/`=` zoom in, `-` zoom out, `⌘0`/`Ctrl0` fit.

**P3: Coordinate System**
- Live readout `X:{n} Y:{n}` in the coordinate bar (drawing coordinates, mouse-relative).
- Click the readout → copies `X,Y` to clipboard.
- Command palette coordinate jump: ⌘K → type `200,300` or `200 300` → `resetView()` +
  `setZoom(1.5)` + `panBy` so the target is centered.

**Extra navigation (not in original spec):**
- `g`-key chord: press `g` then `o/q/k/s/a/d/p/t` to jump to the 8 console sections.
- `/` opens the command palette; `⌘K`/`CtrlK` toggles it.

**P4: Revision Cloud Notifications** — see §6.
- SVG clouds at deterministic positions (hashed from notification ID).
- Unread: high opacity + pulse for urgent; read: low opacity grayscale.
- Click → detail panel (risk type + title + body + nav link); mark-all-read.

**P2 (Rolled Back)**: Layer visibility toggle was implemented then reverted.

## 13. API Consumption Status (SPA-facing contract)

Verified against `lib/api.ts` (11 fetchers) + `lib/auth.tsx` (2 auth calls). Every fetcher
routes through `authApi()`. 13 live endpoints total, no strays.

| Endpoint | Fetcher | Consumed by |
|----------|---------|-------------|
| `POST /api/auth/login` | — (`auth.tsx`) | Login |
| `GET /api/auth/me` | — (`auth.tsx`) | auth identity + refresh |
| `GET /api/command-center` | `fetchCommandCenter` | CommandPalette, `notifications.ts` (clouds/feed) |
| `GET /api/review-intake` | `fetchReviewIntake` | ReviewQueue |
| `GET /api/knowledge-graph` | `fetchKnowledgeGraph` | KnowledgeObjects |
| `GET /api/traceability/{id}` | `fetchTraceability` | KnowledgeObjects drawer |
| `GET /api/drift` | `fetchDriftSurface` | CoverageDrift |
| `GET /api/source-blindness` | `fetchSourceBlindnessSurface` | SourcesEvidence |
| `GET /api/recovery/overview` | `fetchGovernanceOverview` | Overview |
| `GET /api/recovery/window/{id}` | `fetchRecoveryWindow` | RecoveryDetail |
| `GET /api/recovery/downstream-reality-check/{id}` | `fetchDownstreamRealityCheck` | RecoveryDetail |
| `GET /api/publish-preview` | `fetchPublishPreview` | PublishPreviewModal, AudiencePublish |
| `GET /api/publish-propagation` | `fetchPublishPropagation` | Propagation |
| `POST /api/publish/apply` | `applyPublishAction` | PublishPreviewModal (only write caller) |

`/api/notifications` appears only as a comment in `notifications.ts` (a future persisted
source); it is NOT called — notifications are derived from `command-center`'s
`priority_stack` today.

## 14. Governance Loop Status (frontend surfaces)

```
看见风险     ✅ Overview + ReviewQueue
审阅风险     ✅ ReviewQueue drawer
预览爆炸半径 ✅ PublishPreviewModal
执行发布     ✅ POST /api/publish/apply (rehearsal, not persisted)
跟踪传播     ✅ Propagation page
验证恢复     ✅ RecoveryDetail page
追溯证据     ✅ Traceability drawer in KnowledgeObjects (+ projection)
```

## 15. Key Design Decisions

1. Dark palette is neutral charcoal, not blue-black — blue is accent only.
2. Landing page stays independent dark — doesn't follow theme.
3. Drag pan limited to ~25px — subtle nudge, spring-back on release.
4. Plain scroll = native — no custom scroll hijacking.
5. P2 layer visibility rolled back — user decided it wasn't meaningful.
6. Cloud-visibility toggle lives inside NotificationBell dropdown; CloudSummaryButton
   and NotificationBell coexist (the "replaces" comment is stale).
7. Blueprint aesthetic is the settled visual system; Landing is the only exception.
8. `persisted: false` on write path — rehearsal only, never claim durable state.
9. Projection truth is backend-held, not SPA session state (no `PublishActionProvider`).
10. Plotter reveal uses `motion/react` MotionValue + `pathLength`, not CSS stroke-dashoffset.

## 16. How to Run (frontend)

```bash
cd frontend && pnpm dev          # Vite dev server, proxies /api → 127.0.0.1:8077
cd frontend && pnpm run build    # typecheck + vite build
```

Backend boot is out of scope for this handoff. The SPA only needs the `/api` origin
proxied to a running Cygnus backend.

---

## 17. Exploratory Frontend Ideas (Blueprint Paradigm)

10 visual/interaction ideas extending the blueprint metaphor. **Status verified against
the code as of 2026-06-27.**

| Rank | Idea | Effort | Impact | Status |
|------|------|--------|--------|--------|
| 1 | Plotter Animation | Low | High | ✅ **Implemented** — `PlotterPanel.tsx` |
| 2 | Callout Bubbles | Medium | High | ❌ Not implemented |
| 3 | Paper Texture | Low | Medium | ❌ Not implemented |
| 4 | Revision Timeline | High | High | ❌ Not implemented |
| 5 | Dimension Lines | Medium | Medium | ✅ **Implemented** — `DimensionLines.tsx` |
| 6 | Export PDF | Medium | Medium | ❌ Not implemented |
| 7 | Sound Design | Medium | High | ❌ Not implemented |
| 8 | Tools Palette | High | High | ❌ Not implemented |
| 9 | Cross-Section | High | Medium | ❌ Not implemented |
| 10 | Revision Diff | High | Medium | ❌ Not implemented |

### Idea 1: Plotter Animation (绘仪动画) — ✅ IMPLEMENTED
`PlotterPanel.tsx`. A single MotionValue `lap` (0→1) drives an SVG path whose
`pathLength === lap`, drawing the four edges clockwise; content seeps in via a derived
`contentOpacity` + two-axis diagonal `clip-path`; title-block values sweep in last via a
`SweptTitleBlock` clip. Two pacing tiers: ~1.05s entry (Login) and ~0.4s operational
(drawers). Reduced-motion respected. Wired into `Login.tsx`, `ReviewQueue.tsx` (drawer),
and `PlotterDemo.tsx`. **Note:** implemented with `motion/react` MotionValue + `pathLength`,
not plain CSS `stroke-dasharray`/`stroke-dashoffset` as the original spec suggested — same
pen-plotter effect, different technique.

### Idea 2: Dimension Lines on Hover (悬停尺寸线) — ✅ IMPLEMENTED
`DimensionLines.tsx`. Hover/focus a ranked row → SVG overlay with arrowed dimension lines
(`dim-arrow` marker) measuring the real value delta to neighbors, with a derived tolerance
(`deriveTolerance`). Two target strategies: sorted-adjacent (Overview SEC-A) and
rank-extrema (RecoveryDetail). Noisy pairs (tol ≥ delta) render dashed/dim. Pure
client-side, not persisted. Wired into `Overview.tsx` (SEC-A leverage ranks) and
`RecoveryDetail`.

### Idea 3: Revision Timeline Scrubber — ❌ not implemented
No canvas-bottom timeline scrubber, no governance-command marks, no double-click→recovery.
(RecoveryDetail shows a recovery window, not a scrubbable timeline.)

### Idea 4: Export PDF — ❌ not implemented
No `EXPORT` button, no `window.print()`, no `@media print` CSS anywhere in `frontend/src`.

### Idea 5: Callout Bubbles / Detail View — ❌ not implemented
No detail-callout zoom (circle dense area → leader → enlarged circle). The existing
`.bp-anno` annotation row is a different (pre-existing) pattern.

### Idea 6: Paper / Vellum Texture — ❌ not implemented
No `feTurbulence`/SVG-filter paper texture. Grid-paper background exists; procedural
fiber/vellum does not.

### Idea 7: Sound Design — ❌ not implemented
No Web Audio / `AudioContext` code in `frontend/src` at all.

### Idea 8: Cross-Section View — ❌ not implemented
No SECTION button, no cutting-plane line, no hatch-pattern strata.

### Idea 9: Revision Diff Overlay — ❌ not implemented
No two-time-point overlay, no blend-ratio slider, no auto-marked diff clouds.

### Idea 10: Floating Tools Palette — ❌ not implemented
No CAD-style floating toolbar. (`CommandPalette` is ⌘K search; the mastermind "palette"
is a game channel deck — unrelated.)

## 18. Product-Connected Frontend Ideas

15 product-level features emerging from Cygnus's positioning as a Support Knowledge OS.
**Status verified against the code as of 2026-06-27.** Most are not yet built; the few
that have partial surfaces are noted.

| Rank | Idea | Domain | Product Value | Status |
|------|------|--------|---------------|--------|
| 1 | Evidence Traceability Chain | Traceability | Critical | ✅ **Implemented** (KnowledgeObjects drawer) |
| 2 | MRP Pipeline Visualizer | Compilation | High | ❌ Not implemented |
| 3 | Version History | Traceability | High | ❌ Not implemented |
| 3 | Audience Filter Composer | Audience | High | ❌ Not implemented |
| 4 | Lifecycle State Machine | Governance | High | ◐ Partial — lifecycle chip only |
| 4 | Source Ingestion Monitor | Compilation | Medium | ❌ Not implemented |
| 4 | Freshness Heatmap | Health | Medium | ◐ Partial — freshness color on cards |
| 5 | Audience Coverage Matrix | Audience | Medium | ❌ Not implemented |
| 5 | Approval Gate Sign-Off | Governance | High | ❌ Not implemented |
| 5 | Health Report Card | Health | Medium | ◐ Partial — source-health board only |
| 6 | RAG Retrieval Inspector | RAG | High | ❌ Not implemented |
| 6 | Command Sequence Diagram | Governance | High | ❌ Not implemented |
| 6 | Ticket Cluster Converter | Flow | Medium | ❌ Not implemented |
| 7 | Nanobot Session Inspector | Nanobot | High | ❌ Not implemented |
| 7 | Copilot Feedback Loop | Flow | High | ◐ Partial — flat feedback feed only |

- **Idea 13 (Evidence Traceability Chain)** — the only product idea fully implemented:
  `KnowledgeObjects` TraceabilitySection renders object→evidence→source→freshness +
  PROJECTION block. ("Export as traceability report" sub-feature is NOT present.)
- **Idea 19 (Lifecycle State Machine)** — only a per-node lifecycle tolerance *chip*
  (`KnowledgeObjects`, 3 states: published/in_review/draft). No state-machine diagram.
- **Idea 22 (Freshness Heatmap)** — only freshness color/tol on `SourcesEvidence` cards.
  No time×object grid heatmap.
- **Idea 23 (Health Report Card)** — only a source-blindness health *board*. No per-object
  A-F graded card.
- **Idea 25 (Copilot Feedback Loop)** — only a flat feedback feed (`FeedbackRow`) in
  RecoveryDetail's reality-check. No circular write-back loop diagram.

> Backend modules these ideas would consume are intentionally not listed here — that
> mapping is a backend concern. The frontend status above is what matters for handoff.
