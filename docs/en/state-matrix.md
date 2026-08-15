# Support Brain for SaaS — State Matrix

## 1. What this document solves
The earlier docs define pages and layout skeletons, but on a control-tower product the real quality often depends not on the default state, but on:
**how the product tells the truth when the system is unstable, partial, or conflicted.**

This document defines:
- Cygnus’s core state vocabulary,
- how screens should change under those states,
- what the user should be warned about first,
- what they can still do safely,
- what they must not misread.

---

## 2. State design principles

### Principle 1: tell the user what is still trustworthy first
An error state should not only say “something broke.” It should say:
- which part of truth is still trustworthy,
- which judgment should pause,
- which actions remain safe.

### Principle 2: intermediate states must be acknowledged
Many Cygnus states are not binary done/failed states. They are:
- partial rollout,
- recovery incomplete,
- evidence degraded,
- route unresolved.

### Principle 3: states must serve command
The purpose of state is not decorative feedback. It is to help the user decide whether to:
- keep observing,
- reroute,
- pause propagation,
- trigger remediation,
- declare closure.

### Principle 4: state must not degrade into an ops alert wall
Even source failure must be translated into support-governance consequence.

---

## 3. Shared Cygnus state vocabulary

| State | Meaning | The user’s first reaction should be | The system must emphasize |
|---|---|---|---|
| Calm / Stable | no obvious system-level drift right now | observe, no urgent command required | whether recent commands truly closed |
| Emerging Risk | early deviation signals exist | judge whether early intervention is warranted | whether risk is widening or local |
| Leadership Intervention Overdue | the system has entered tower-worthy territory | enter the coordination chain now | cost of inaction |
| Stale but Usable | data is old but still directionally usable | read last-known truth, act cautiously | timestamp and freshness gap |
| Source Blindness | a source class failed and the system is partly blind | lower confidence, repair source or contain downstream | affected objects and surfaces |
| Evidence Degraded | content exists but support evidence is weak | either strengthen evidence or restrict spread | which commands are unsafe |
| Ambiguous Ownership | the problem exists but ownership is unclear | clarify the owner first | cross-queue / cross-team conflict |
| No Safe Route Yet | risk exists but no safe treatment path is ready | contain first, broaden later | do not pretend publish is safe |
| Conflict Across Audiences | different audiences currently carry conflicting truth | split variants before release | which audiences cannot share one answer |
| Propagation Blocked | command issued, but it did not pass every stage | inspect blocked stage and follow up | what synchronized vs what did not |
| Partial Rollout | some surfaces updated, some did not | decide whether temporary inconsistency is tolerable | whether internal and external are misaligned |
| Recovery Incomplete | metrics improved but alignment is not restored | decide whether another cycle is required | improvement is not closure |
| Recovery Confirmed | the cycle has produced stable recovery | close the cycle and monitor | evidence chain must remain visible |

---

## 4. Global state presentation rules

| State type | Horizon | Situation Frame | Main Field | Dock / Band |
|---|---|---|---|---|
| Calm / Stable | low-noise stable marker | reminds the user of recent recovery | default structure | Recovery Snapshot can compress |
| Emerging Risk | light elevation | states that risk is forming | shows movement trend | suggests next move |
| Leadership Intervention Overdue | high-priority alerting | emphasizes cost of inaction | reprioritizes risky objects | Command Ribbon keeps unresolved warning |
| Stale but Usable | shows freshness gap | explicitly marks last-known truth | supports read-only judgment | must not fake real-time confidence |
| Source Blindness | clearly marks partial blindness | states blind-zone scope | lowers confidence on related modules | shows repair / contain actions |
| Propagation Blocked | marks active blocked cycle | explains consequence of the stall | highlights blocked stage | follow-up actions must sit nearby |
| Recovery Incomplete | keeps cycle open | says “improved but not closed” | makes the intermediate state obvious | continue vs close must be explicit |

---

## 5. Per-screen state matrix

## Screen 01 — Command Center

| State | Page behavior | Allowed user move | Must avoid |
|---|---|---|---|
| Calm / Stable | Priority Stack compresses, Recovery Snapshot becomes more prominent | browse, inspect recent recoveries | pretending nothing deserves watching |
| Emerging Risk | Movement Grid reveals drift front or rewrite cluster | enter Coordination / Drift Radar | burying new risk under stats |
| Leadership Intervention Overdue | strong command callout appears at top of stack | initiate intervention immediately | still feeling like a routine daily report |
| Stale but Usable | freshness gap is marked while last-known layout stays visible | make low-risk judgment only | posing as live war-room truth |
| Multi-surface Spread | Movement Grid expands into cross-channel scope | enter Propagation / Coordination | treating multi-surface issues as local queue noise |

## Screen 02 — Queue / Topic Coordination Board

| State | Page behavior | Allowed user move | Must avoid |
|---|---|---|---|
| Ambiguous Ownership | Owner & Load Strip highlights no clear owner | route, assign, escalate | forcing the user to infer ownership manually |
| No Safe Route Yet | some ladder actions disable with explanation | contain, hold, request evidence | allowing risky publish |
| Cross-team Issue | Decision Constellation shows multi-team tension | route to team, escalate | flattening complex ownership |
| Conflict Across Audiences | audience nodes show conflict banding | split variant, restrict scope | merging conflicting truth into one answer |
| Propagation Blocked | lower band shows prior move failed to pass through | issue follow-up command | divorcing new actions from history |

## Screen 03 — Coverage & Drift Radar

| State | Page behavior | Allowed user move | Must avoid |
|---|---|---|---|
| Emerging Risk | Drift Weather Layer shows light approaching front | preemptive refresh/review | only elevating after explosion |
| Stale but Usable | coverage remains readable but freshness markers degrade | open sources / objects | collapsing coverage and freshness into one number |
| Source Blindness | Source vs Object Panel clearly leans toward source responsibility | repair source / contain publish | misleading the user into thinking it is content-only |
| Conflict Across Audiences | Gap Matrix shows audience split holes | split route | continuing with one unified coverage view |

## Screen 04 — Knowledge Review Queue

| State | Page behavior | Allowed user move | Must avoid |
|---|---|---|---|
| Needs Decision Now | top of Priority Re-stack Lane becomes pinned | approve / reject / reroute | letting urgent items sink |
| Evidence Degraded | Evidence Strength Column clearly downgrades | request evidence / hold publish | letting weak evidence flow normally |
| Waiting on Owner | owner column becomes the primary blocker | reassign / escalate | showing “waiting” without action |
| Safe to Defer | visual noise reduces | defer / batch review | treating deferred and urgent equally |

## Screen 05 — Knowledge Object Workspace

| State | Page behavior | Allowed user move | Must avoid |
|---|---|---|---|
| Draft | lifecycle rail clearly shows not through gate yet | revise / send to review | implying it is already live |
| Audience Conflict | variant pane shows split warning | split variant / restrict | mixing internal and external truth on the same plane |
| Evidence Degraded | evidence drawer opens by default to half depth | add source / lower confidence | pretending the object is stable |
| Propagation Blocked | object-level downstream map shows unsynced surfaces | open ledger / republish / contain | only saying “saved successfully” |

## Screen 06 — Audience / Publish Command Center

| State | Page behavior | Allowed user move | Must avoid |
|---|---|---|---|
| Internal Only | Gate Matrix makes external gates clearly closed | prepare external / keep internal | leaving the internal/external boundary fuzzy |
| Conflict Risk | Blast Radius Preview highlights conflicting audiences | split / restrict / hold | encouraging publish immediately |
| Partial Rollout | Propagation Theater shows updated and untouched regions | continue rollout / rollback / hold | showing only “published” |
| Propagation Blocked | blocked stage and follow-up command remain on same screen | reroute / republish / contain | forcing users elsewhere to learn why it failed |

## Screen 07 — Source Integrity / Evidence Health

| State | Page behavior | Allowed user move | Must avoid |
|---|---|---|---|
| Source Blindness | Signal Loss Layer owns the screen | repair / resync / contain | shrinking source failure into a minor notice |
| Stale but Usable | marks sources as old but directionally useful | low-risk observation | treating stale as instantly broken |
| Evidence Degraded | Affected Objects list carries low-confidence tags | lower confidence / force review | uncoupling source health and evidence quality |

## Screen 08 — Copilot / Downstream Reality Check

| State | Page behavior | Allowed user move | Must avoid |
|---|---|---|---|
| Rewrite Spike | top feed aggregates rewrite clusters | elevate to command | treating it as frontline anecdote |
| Audience Mismatch | mismatch view layers by audience clearly | open variant / publish control | continuing to read only overall averages |
| Recovery Incomplete | unresolved prompt remains even if rewrite drops | reopen command cycle | treating local improvement as closure |

## Screen 09 — Propagation Ledger

| State | Page behavior | Allowed user move | Must avoid |
|---|---|---|---|
| Command In Flight | timeline shows current stage | wait with guardrails / inspect | acting as if outcome is already final |
| Propagation Blocked | blocked stage becomes primary read target | reroute / contain / republish | hiding the issue deep in logs |
| Secondary Conflict | affected surfaces show second-order warnings | split follow-up command | treating propagation failure as one-point error |
| Recovery Incomplete | ledger makes clear propagation happened but recovery did not | open Recovery Window | assuming propagation equals recovery |

## Screen 10 — Recovery Window

| State | Page behavior | Allowed user move | Must avoid |
|---|---|---|---|
| Recovery Incomplete | before/after shows improvement without closure | continue command | showing only green success |
| Recovery Confirmed | closure judge explicitly marks closure | close cycle / monitor | hiding the proof chain |
| Drift Rebound | after-state improves briefly and rises again | reopen drift route | closing after one temporary gain |

---

## 6. Creative states unique to Cygnus

These states deserve names in the experience rather than hiding in raw metrics.

### A. Command Shadow
Meaning: the previous command still affects priority or judgment, even after the user moved elsewhere.
Presentation: Command Ribbon continues to show an unresolved shadow.

### B. Split-Brain Publish
Meaning: internal knowledge and external answer surfaces are temporarily out of sync.
Presentation: publish / propagation surfaces must explicitly name the two truth planes.

### C. Blind-but-Operating
Meaning: the system can still run, but source blindness has removed full visibility.
Presentation: observation remains possible, but high-confidence release does not.

### D. False Recovery
Meaning: some metrics improved, but the underlying drift or audience mismatch remains.
Presentation: Recovery Window must block a beautiful but incorrect closure.

---

## 7. Usage rules
Any future page design should answer:
1. What is the most dangerous misread on this screen?
2. If data is incomplete, what can the user still do safely?
3. Does the page clearly distinguish partial, blocked, recovered, and stale?
4. Does the state directly help the user decide the next command?

If a state only describes the system but does not help the user choose the next move, it is not yet a Cygnus state design.
