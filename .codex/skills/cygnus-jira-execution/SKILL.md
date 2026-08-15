---
name: cygnus-jira-execution
description: Use this skill when working from the CYG Jira board, when the user wants Codex to start from Jira/kanban, pick the next Cygnus issue, execute work according to the CYG backlog, or treat Jira as the project execution control surface; also use it for 根据 Jira 开始做、从 CYG 看板推进、把 Jira 当 Kanban、按 story/substrate 映射开始实现 Cygnus。
---

# Cygnus Jira Execution

## When to use
Use this skill when the task is to:
- start work from the `CYG` Jira board
- ask “what should we do next from Jira?”
- treat Jira as the execution board / kanban for Cygnus
- pick a CYG issue and implement against it
- update Jira while doing real work
- decide whether a Jira story is actually buildable yet or is still blocked on substrate milestones

Do not use this skill when the task is only a general product question with no Jira/execution angle.

## Core truths to preserve
These rules are fixed for this repo:
- **Arkon = substrate**
- **Cygnus = support-domain enhancement / governance center**
- **Nanobot = session layer**
- **No LangGraph mainline; governance workflows stay explicit and bounded inside Cygnus**
- Jira product stories are **not** the same thing as engineering-first tasks
- The first product story is `CYG-6`, but the current engineering mainline is now **full-port baseline import → runability recovery → internalization (when full absorption is the goal) → support verticalization**

## Execution-state ownership
- **Jira is the sole delivery-state and Kanban source of truth** for Cygnus: priority, ownership, blockers, progress, and completion live on the CYG issue.
- Any code-changing or multi-session delivery must bind to one CYG issue. One-turn read-only investigation may remain untracked.
- Trellis defaults to **specs-only** use. Load `.trellis/spec/` through `trellis-before-dev`, use `trellis-check` and `trellis-update-spec` when relevant, but do not create a Trellis task for each Jira issue.
- A complex or high-risk issue may use a neutral local plan keyed to the CYG issue. The plan has no independent lifecycle status and never overrides Jira.
- Create/start/archive a Trellis task only when the human explicitly requests the legacy Trellis lifecycle. Never dual-write routine status into Jira and Trellis.
- Git, tests, CI, smoke checks, and review are the completion evidence; write the concise result to Jira before transitioning the issue.

## Read order
Load the smallest set needed, in this order:

1. `docs/README.md`
2. `docs/{lang}/arkon-full-port-migration-plan.md`
3. `docs/{lang}/story-to-substrate-mapping.md`
4. `docs/{lang}/jira-governance-migration-stories.md`
5. If Jira structure matters: `docs/{lang}/jira-project-configuration-plan.md`
6. Then fetch the relevant Jira issue(s)

Use `zh` for Chinese prompts and `en` for English prompts.

## Source-of-truth order
When there is tension:
1. `docs/{lang}/prd.md`
2. `docs/{lang}/arkon-full-port-migration-plan.md`
3. `docs/{lang}/story-to-substrate-mapping.md`
4. `docs/{lang}/jira-governance-migration-stories.md`
5. `docs/{lang}/jira-project-configuration-plan.md`

Interpretation rule:
- Jira stories define **user-visible migration order**
- Milestones define **engineering readiness order**

## Issue classification
When you open a CYG issue, classify it first:

### A. Governance theme parent
Examples:
- `CYG-2` to `CYG-5`

Meaning:
- product theme / migration lane
- not directly code-ready

Action:
- do not code against the parent ticket directly
- identify the child story or the enabling milestone instead

### B. Product migration story
Examples:
- `CYG-6` to `CYG-17`

Meaning:
- user-visible control migration
- now explicitly blocked until full-port baseline + runability — and, when required, internalization — are sufficiently in place

Action:
- map the story to `P0 ~ P4` using `story-to-substrate-mapping.md`
- if `P1/P2` are still missing, work on the prerequisite migration lane instead
- if the user explicitly wants to absorb Arkon into Cygnus and delete the separate upstream codebase, prefer the post-P2 internalization lane before broader P3 expansion

### C. Full-port baseline / runability task
Examples:
- `CYG-23+`

Meaning:
- engineering-first migration work
- the real current mainline before support verticalization

Action:
- execute these before jumping into later support stories
- keep source parity import, runability recovery, and internalization separate

### D. Deferred shell-parity lane
Examples:
- `CYG-25`
- `CYG-44`
- `CYG-57`
- `CYG-58`

Meaning:
- deferred boundary-clarification lane for optional product-shell parity
- not the current implementation mainline

Action:
- classify `auth / admin / wiki` shell candidates before any parity implementation
- separate **support-relevant shell candidates** from **generic-product shell candidates**
- explicitly isolate **non-support pages** into the deferred lane unless they directly unblock support verticalization
- do not turn this lane into generic UI parity or use it to rewrite P1/P2/P2.5/P3 priority order

### E. Engineering-ready task
Meaning:
- a task explicitly scoped to a current milestone slice
- usually code-ready

Action:
- execute it directly
- verify with tests
- update Jira with evidence

## Default execution rule
If Jira points to a story but no engineering-ready implementation task exists yet:
- **do not jump straight into the UI surface**
- derive the current executable slice from milestones
- start from the earliest missing prerequisite

For Cygnus now, the default first slice is:
- **P1 — Arkon full-port source parity import**
- then **P2 — Repair / Runability Recovery**
- then **P2.5 — Internalization / Upstream Cutover** when full absorption is the explicit goal
- only then **P3 — Support verticalization**

## Completion-state truth contract
Never collapse these into one implied done-state:
- imported baseline
- recovered runability
- internalized substrate
- implemented support verticalization

Interpretation rules:
- a **P1** ticket may close when the scoped baseline slice is mirrored and freshly validated; its comment must not imply runability
- a **P2** ticket may close only when a concrete wiring / startup / smoke-run path is freshly proven; its comment must not imply internalization or support verticalization
- a **P2.5** ticket may close only when ownership / entrypoint / identity-cutover acceptance is freshly proven; its comment must not imply support verticalization or shell parity
- a **P3** story may close only when the user-visible governance behavior exists on top of substrate truth; it must not be justified by P1 import alone
- parent-lane tickets like `CYG-23`, `CYG-24`, and `CYG-25` are not auto-complete when one child closes
- deletion-readiness gate tickets must prove a concrete stop-line (for example `scripts/upstream_cutover_gate.py`) before claiming upstream cutover started is ready for codebase deletion
- if a real external checkout still exists on disk, preserve local ahead history plus dirty/untracked worktree state with `scripts/external_checkout_preserve.py` before proposing physical deletion; preservation does not itself satisfy `external_checkout_audit`
- `scripts/external_checkout_audit.py` is the audit surface for standalone checkout detection
- `scripts/external_checkout_audit.py --fail-if-found` is the physical-deletion proof, not the preserve step

## Story-to-phase quick routing
Use these defaults unless newer repo truth overrides them:

### P3 early-wave story batch
- `CYG-12`
- `CYG-14`
- `CYG-6`
- `CYG-7`

### P3 mid-wave story batch
- `CYG-9`
- `CYG-10`
- `CYG-11`
- `CYG-13`

### P3 late-wave story batch
- `CYG-15`
- `CYG-16`
- `CYG-17`
- `CYG-8`

Why `CYG-8` is late:
- it is easy to fake as draggable/reorderable UI before command substrate is real

## Execution workflow

### Step 1 — Read the board context
Fetch the current issue and its parent/linked context if relevant.
Confirm:
- what the issue claims to represent
- whether it is theme/story/engineering task
- what milestone it depends on

### Step 2 — Decide the real executable target
Translate the Jira issue into one of:
- `execute current code slice now`
- `blocked on earlier milestone; implement prerequisite`
- `needs task derivation before coding`
- If code-changing or multi-session work has no CYG issue yet, identify or create the engineering-ready issue before implementation; do not substitute a Trellis task.

State this briefly before editing.

### Step 3 — Implement the smallest correct slice
Prefer:
- typed domain contracts before retrieval
- retrieval before graph only when milestone order permits
- graph only for governance workflows that are clearly graph-shaped

Never skip from product story directly to polished UI if substrate truth is missing.

### Step 4 — Verify
For code work, verify with the smallest fresh evidence that proves the slice:
- targeted tests first
- then typecheck/lint if applicable
- avoid claiming completion without fresh validation or an explicit gap note

### Step 5 — Write back to Jira
When useful, add a Jira comment with:
- what was implemented
- changed files
- verification result
- blocker / next step

Keep comments execution-focused, not essay-like.

### Step 6 — Sync Jira workflow state
Do not stop at comments when the execution state has genuinely changed.

Default status rules:
- when active implementation work starts on a story or engineering-ready task, transition it to **`正在进行`**
- when the scoped story acceptance is satisfied by current code and fresh verification evidence, transition it to **`完成`**
- if work is exploratory, blocked on earlier substrate, or only partially advanced, keep it in **`待办`** or move it to **`正在进行`** instead of prematurely closing it

Completion gate before transitioning to **`完成`**:
- confirm the story has a real executable boundary in code
- confirm fresh validation was run against the current state
- confirm the result matches the story-level acceptance, not just a lower-level substrate slice

Transition / comment tool rule:
- treat Jira status transition and Jira progress comment as **separate operations**
- do **not** assume adding a comment changes the Jira workflow state
- if transition-with-comment fails because the server expects Atlassian document format, retry the transition **without the comment**, then add the comment separately

For the current CYG board defaults observed in this repo:
- `21` = **`正在进行`**
- `31` = **`完成`**

## Jira update rules
Use Jira as the **execution control surface**, not as a fake runtime.

Good Jira use:
- pick next issue
- mark progress
- record blockers
- attach evidence of completion
- preserve product-story context
- preserve the distinction between baseline import, runability recovery, internalization, and verticalization

Bad Jira use:
- pretending a product story is already implementation-ready when milestones are not
- rewriting a governance story into generic engineering chores without preserving the story intent
- using Jira to justify skipping M1/M2/M2.5 and jumping into M3/M4

## Anti-patterns
Do not do these:
- build `CYG-6` page before M1/M2 foundations exist
- start support stories before P1/P2 — and, when explicitly required, P2.5 — are materially in place
- treat chunks/wiki pages as Cygnus product nouns
- turn LangGraph into a second session runtime
- let Jira structure override product boundaries from PRD and architecture docs

## Output expectations
When using this skill, respond in this shape:
1. current Jira target
2. issue classification
3. current executable slice / milestone
4. action taken or blocker
5. verification evidence
6. optional Jira write-back note

## Minimal examples

### Example 1
User: “从 Jira 开始做，下一张票是什么？”

Expected behavior:
- inspect CYG board / target issue
- classify issue
- map it to milestone readiness
- if only product stories exist, recommend the current executable milestone slice instead of fake-starting the page

### Example 2
User: “继续做 CYG-6”

Expected behavior:
- map `CYG-6` to `M2 -> M3`
- check whether `M1` and `M2` are already real in code
- if not, work on the missing prerequisite rather than directly building the review page

### Example 3
User: “把 Jira 当成 kanban，开始开发”

Expected behavior:
- use Jira as the selection and reporting surface
- keep real implementation order driven by milestone readiness
- update Jira after meaningful progress
