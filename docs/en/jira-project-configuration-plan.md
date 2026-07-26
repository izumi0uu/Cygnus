# Cygnus — Jira Project Configuration Reverse Plan

## 1. Purpose
This document does not redefine the product itself. It explains:
**what Jira project shape CYG needs so it can carry both the “governance product stories” and the “Arkon full-port engineering mainline” at the same time.**

It serves three purposes:
- explain why the board is temporarily using “Task + Relates”
- provide a low-risk adjustment sequence for future Jira configuration
- ensure the backlog can hold both **support-governance mission control** and the **full-port baseline engineering lane** without collapsing into a generic PM board

## 2. Current observed state (based on CYG validation on June 18, 2026)
What is currently verified:
- Jira project: `CYG`
- Board: `68 / CYG面板`
- Through the current MCP creation path:
  - `Task` can be created successfully
  - `Epic` / `Story` return an “invalid issue type” style error
  - assigning `parent` directly to a Task can also fail with an “invalid parent issue” style error
- Therefore the current temporary structure is:
  - `CYG-2 ~ CYG-5` as governance-theme parent tickets (still Tasks)
  - `CYG-6 ~ CYG-17` as governance leaf stories (still Tasks)
  - `CYG-23 ~ CYG-25` as full-port / runability / shell-parity parent lanes (still Tasks)
  - `Relates` links used as weak parent-to-leaf connections

## 3. What this means
### 3.1 Confirmed fact
The confirmed fact is not “Jira doesn’t support Epic / Story.”
It is:
**the current CYG project does not expose Epic / Story as usable work types in this creation context, and Task-parent hierarchy is not reliably open either.**

### 3.2 High-confidence inference
Based on behavior, `CYG` still looks like a **team-managed / next-gen style project**, but this must be confirmed in project settings.

> “team-managed” here is an inference from behavior, not an admin-confirmed fact.

## 4. CYG now effectively contains two backlog structures
Cygnus no longer has only one Jira narrative.

### 4.1 Governance product lane
- `CYG-2 ~ CYG-5`: governance parent lines
- `CYG-6 ~ CYG-17`: user-visible governance capability changes

This structure serves:
- product narrative
- page story maps
- visual and interaction design
- later P3 support verticalization

### 4.2 Engineering migration lane
- `CYG-23`: P1 full-port baseline parent lane
- `CYG-24`: P2 runability recovery parent lane
- `CYG-25`: P4 optional shell-parity parent lane
- their migration children: runtime/database/services/protocol/MRP/knowledge/surface/wiring/boot/boundary

This structure serves:
- the real current engineering mainline
- the control surface for Arkon full-port migration
- the follow-up schedule for runability repair

## 5. Why these two structures must not be merged back together
If they stay mixed:
- product stories will be misread as the current code mainline
- full-port tasks will swallow the governance subject
- the board becomes an undifferentiated Task heap
- both support-governance mission control and engineering migration lose clarity

So the minimal correct approach right now is:
- **keep the two lanes side by side structurally**
- **make the parent-lane meaning explicit semantically**
- **use labels + links to keep phase and lane visible**

## 6. Ideal hierarchy (future upgrade)
The long-term hierarchy should still be:
- **Epic** = one governance line or one migration line
- **Story** = one user-visible capability shift or one clear engineering slice
- **Task** = miscellaneous, research, or temporary support work
- **Subtask** = only when finer execution breakdown is genuinely needed

### 6.1 Mapping the current two lanes
#### Governance product lane
- `CYG-2 ~ CYG-5` → Epics
- `CYG-6 ~ CYG-17` → Stories

#### Engineering migration lane
- `CYG-23 ~ CYG-25` → Epics
- new migration children → Stories

## 7. Current recommended configuration plan

### 7.1 Short term: continue accepting Task + Relates
Before work types and hierarchy are repaired:
- continue using Tasks
- continue using `Relates` to express parent-lane relationships
- do not stop backlog construction simply because hierarchy is imperfect

### 7.2 Medium term: enable Epic / Story / Subtask
Whether CYG ends up team-managed or company-managed, the target should be:
1. make Epic / Story / Subtask available
2. make backlog features recognize the real hierarchy
3. restore both the governance lane and the engineering migration lane to actual hierarchy

### 7.3 Minimal migration principle
Do not do these at the same time:
- do not rewrite all story content during hierarchy repair
- do not rewrite governance stories into pure technical chores
- do not rewrite engineering migration tickets into page requirements

The minimal goal is simply:
**restore the current two backlog truths into the correct hierarchy.**

## 8. Current label conventions
### 8.1 Governance product lane
- `cygnus`
- `governance-loop`
- `migration`
- `review-publish`
- `support-brain`
- `theme-review` / `theme-publish` / `theme-pressure` / `theme-recovery`
- `story-leaf`
- `seq-01 ~ seq-12`

### 8.2 Engineering migration lane
- `arkon-full-port`
- `full-port-baseline`
- `migration`
- `support-brain`
- `phase-01-full-port`
- `phase-02-runability`
- `phase-04-shell-parity`
- plus narrower substrate tags such as:
  - `runtime-backbone`
  - `database-layer`
  - `service-layer`
  - `protocol-layer`
  - `mrp-pipeline`
  - `knowledge-substrate`
  - `integration-surface`

### 8.3 Deferred shell-parity lane
- `phase-04-deferred`
- `shell-parity`
- `support-relevant-candidate`
- `generic-shell-reference`
- `non-support-excluded`

Usage rule:
- `support-relevant-candidate` is only for shell candidates that **directly host or unblock a support-governance surface**
- `generic-shell-reference` is for auth / admin / wiki shells that may remain reference material but are not current-mainline scope
- `non-support-excluded` is for pages or shells explicitly isolated from current P1/P2/P3 work
- if a shell-lane ticket cannot name a concrete support blocker, it must remain deferred/reference scope and must not rewrite current engineering priority

## 9. Recommended board usage conventions
### 9.1 Board reading order
A board reader should first be able to tell:
1. is this governance product lane or engineering migration lane?
2. is this a parent line or a leaf story?
3. is this ticket in P1, P2, P3, or P4?

### 9.2 Current default rule
- governance product stories default to **P3**
- `CYG-23+` default to **P1/P2/P4**
- current engineering execution priority is higher than P3 page/interaction implementation

## 10. Migration recommendations for existing tickets
### 10.1 `CYG-6 ~ CYG-17`
Keep their meaning intact and later upgrade them as P3 stories.

### 10.2 `CYG-18 ~ CYG-22`
Keep their completed status, but annotate via comment / label as:
- bootstrap history
- selective-extraction reconnaissance
- superseded-by-full-port

### 10.3 `CYG-23+`
Keep them as the current engineering mainline; do not downgrade them into explanatory placeholders.

## 11. One-sentence conclusion
**CYG is no longer one backlog. It is two coexisting backlogs: one for the governance product narrative, and one for Arkon full-port migration plus runability recovery.**
