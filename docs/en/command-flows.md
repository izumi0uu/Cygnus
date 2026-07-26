# Support Brain for SaaS — Command Flows

## 1. What this document solves
The earlier docs define pages, layout, and state.

This document defines:
**how a user moves through a full command cycle in Cygnus when a real support risk emerges.**

It does not describe implementation. It describes:
- what the user sees first,
- why they decide to act,
- how the system receives that action,
- how the action propagates,
- when another cycle is required.

---

## 2. Shared command-flow grammar

Each flow uses the same rhythm:
1. **Signal** — what anomaly brings the user in
2. **Frame** — how the user recognizes this is not local noise
3. **Command** — what governance move is issued
4. **Propagation** — how the system shows the move crossing layers
5. **Recovery** — how the user judges whether the loop is restoring alignment
6. **Next Command or Close** — whether another cycle begins

---

## 3. Flow 01 — Release Drift Recovery

### Scenario
A new version ships. The help center updates partially, but internal SOP, copilot suggestions, and some enterprise variants do not synchronize.

### User entry point
From `Command Center`, the user sees:
- release-related escalations rising,
- freshness fronts appearing in Coverage & Drift,
- copilot rewrites clustering around one version group.

### User behavior + expected system behavior

#### Step 1 — See the drift front
- The user opens `Coverage & Drift Radar`
- The system shows drift as a version migration band, not isolated alerts
- The system simultaneously identifies the affected audiences: enterprise + legacy version

#### Step 2 — Decide whether the issue is object-level or propagation-level
- The user checks `Source vs Object Attribution Panel`
- The system makes clear: release notes arrived, some Answer Cards updated, but publish propagation is incomplete
- The user does not misread the issue as “the docs were never written”

#### Step 3 — Enter coordination
- The user jumps to `Queue / Topic Coordination Board`
- The system uses Decision Constellation to show one problem connecting objects, queues, audiences, and copilot surfaces
- The user recognizes a cross-surface issue rather than a single-editor problem

#### Step 4 — Issue the first command
- The user chooses to:
  - urgent-review the enterprise variant,
  - constrain external rollout for legacy version,
  - route a knowledge owner to inspect affected cards
- The system shows in Consequence Lens which users will still see old answers and which surfaces will tighten temporarily

#### Step 5 — Watch propagation
- The user enters `Propagation Ledger`
- The system breaks the move into: review -> publish gate -> copilot sync -> external answer surface
- The system makes clear which segments passed and which remain blocked

#### Step 6 — Judge recovery
- The user opens `Recovery Window`
- The system compares before vs after:
  - whether rewrite fell,
  - whether escalations softened,
  - whether drift still remains on the legacy variant
- If enterprise recovered but legacy still drifts, the system clearly marks `Recovery Incomplete`

#### Step 7 — Decide whether to continue
- The user issues a second cycle:
  - split the variant more explicitly,
  - keep rollout hold for one audience
- or closes the cycle if recovery is sufficient

### Design emphasis
This flow must make the user feel that the problem is not “one missing article,” but “a release pulled multiple truth planes apart.”

---

## 4. Flow 02 — Incident Spread Containment

### Scenario
A product incident occurs. The status page updates, but knowledge objects, copilot suggestions, and old external workarounds continue spreading.

### User entry point
- `Command Center` shows an incident-linked spike
- `Reality Check Strip` shows rewrite and escalation rising together

### User behavior + expected system behavior

#### Step 1 — Enter the war-room view
- The user moves from homepage to `Queue / Topic Coordination Board`
- The system’s Situation Frame clearly states that inaction will continue spreading wrong guidance

#### Step 2 — Judge that containment matters before content repair
- The user sees multiple actions in the Intervention Ladder
- The system prioritizes:
  - hold external propagation,
  - mark known issue banner,
  - route urgent review
- The system does not encourage long editing first and delayed spread control later

#### Step 3 — Enter Publish Command Center
- The user chooses to temporarily constrain external answers
- The system’s Blast Radius Preview shows:
  - which external surfaces will be cut off,
  - which internal surfaces remain available for human agents

#### Step 4 — Issue containment
- The user confirms containment
- The system does not only say success; Propagation Theater shows:
  - status page aware,
  - copilot partially aware,
  - external FAQ still cached in one channel

#### Step 5 — Inspect source and object repair needs
- The user opens `Source Integrity / Evidence Health`
- The system shows incident notes are healthy, but old objects have not yet been superseded
- The user issues a review / supersede command

#### Step 6 — Verify whether the bleed is controlled
- The user opens `Recovery Window`
- The system compares escalation and wrong-answer surfaces before vs after containment
- If escalation dropped but one cached external channel remains wrong, the cycle stays open

### Design emphasis
This flow should embody a command posture:
**stop the bleed, then correct, then restore.**

---

## 5. Flow 03 — Policy Conflict Across Audiences

### Scenario
Refund or permission policy differs for enterprise, self-serve, and EU users, but multiple Answer Cards were incorrectly collapsed into one answer.

### User entry point
- `Copilot / Reality Check` shows one class of answers heavily rewritten by humans
- `Coverage & Drift` shows audience mismatch

### User behavior + expected system behavior

#### Step 1 — Confirm it is not anecdotal
- The user opens `Reality Check Strip`
- The system layers rewrite clusters by audience
- The user sees concentration in EU + enterprise

#### Step 2 — Inspect object gravity
- The user jumps to `Knowledge Object Workspace`
- The system’s Object Gravity Panel shows one object spanning multiple policy domains
- The user realizes the problem is structural variant design, not phrasing

#### Step 3 — Open Audience / Publish Command Center
- The user checks the gate matrix
- The system clearly shows internal copilot and external help center are sharing the wrong truth plane

#### Step 4 — Issue split command
- The user chooses `split variant`
- The system’s Consequence Lens shows:
  - which audiences will receive a new variant,
  - which channels enter temporary hold,
  - which old references become superseded links

#### Step 5 — Review and propagate
- The user routes the new variant into `Review Queue`
- The system preserves `command-origin` context in the queue
- After approval, Propagation Theater shows the variant entering copilot and external surfaces in sequence

#### Step 6 — Judge recovery
- In `Recovery Window`, the user sees:
  - EU rewrite sharply down,
  - enterprise escalation down,
  - self-serve stable
- The system therefore supports closure

### Design emphasis
This flow must make audience-awareness a hero capability, not a filter.

---

## 6. Flow 04 — Copilot Rewrite Spike → Governance Intervention

### Scenario
Human agents frequently rewrite copilot answers, but the rewrites are scattered across multiple queues and do not yet look like one obvious bug.

### User entry point
- `Command Center` surfaces rewrite acceleration
- `Copilot / Downstream Reality Check` shows cross-queue rewrite clusters

### User behavior + expected system behavior

#### Step 1 — Turn noise into pattern
- The user enters `Copilot / Downstream Reality Check`
- The system clusters dispersed rewrites by topic, audience, and version

#### Step 2 — Elevate into a control-tower problem
- The user clicks `mark as systemic`
- The system promotes the cluster into a new command candidate instead of leaving it as frontline noise

#### Step 3 — Enter coordination
- The user jumps to `Queue / Topic Coordination Board`
- The system reveals that multiple queues, while superficially different, share the same objects and variants

#### Step 4 — Issue governance moves
- The user chooses to:
  - open review for impacted Answer Cards,
  - lower evidence confidence on one suspect source,
  - route to a knowledge manager

#### Step 5 — Watch the echo
- `Propagation Ledger` shows:
  - review started,
  - source confidence downgraded,
  - copilot still consuming the last published variant

#### Step 6 — Judge whether frontline behavior truly changed
- `Recovery Window` compares rewrite delta
- If rewrite falls but human rewriting persists in high-value queues, the system should not allow cheap closure

### Design emphasis
This flow must prove:
**frontline rewrite is not noise in Cygnus; it is governance radar.**

---

## 7. Flow 05 — Blocked Propagation → Second Command Cycle

### Scenario
A critical publish command completes review and reaches internal copilot, but fails to reach external surfaces because of channel-rule or audience-gate conflict.

### User entry point
- Command Ribbon shows an unresolved command shadow
- `Propagation Ledger` marks partial rollout

### User behavior + expected system behavior

#### Step 1 — Return to the command scene
- From any page, the user clicks Command Ribbon
- The system takes them back to the blocked stage inside `Propagation Ledger`

#### Step 2 — Identify the blockage
- The system clearly shows:
  - review passed,
  - publish rule conflict exists,
  - external channel gate is blocked
- The user does not need to piece the story together across screens

#### Step 3 — Open Publish Command Center
- The user checks the gate matrix
- The system shows the conflict is audience overlap, not technical failure

#### Step 4 — Issue a second command
- The user chooses to:
  - temporarily restrict one audience,
  - republish to safe channels,
  - keep the internal variant live

#### Step 5 — Re-observe propagation
- Propagation Theater shows the first failure and second correction side by side
- The user sees whether the new command truly crossed the old barrier

#### Step 6 — Judge recovery again
- If external surfaces are now synchronized but rewrite remains high, Recovery Window stays open
- If external sync lands and downstream mismatch also falls, closure is allowed

### Design emphasis
This flow must show how Cygnus differs from a success toast:
**propagation failure itself becomes a new commandable object.**

---

## 8. Flow 06 — Recovery Verification and Close

### Scenario
After multiple command rounds, the system looks calmer, but the user must decide whether this is true recovery or just temporary silence.

### User entry point
- one Command Ribbon cycle is marked almost-closed,
- Recovery Snapshot improves,
- a small amount of residual mismatch remains.

### User behavior + expected system behavior

#### Step 1 — Enter Recovery Window
- The user opens the current cycle’s Recovery Window
- The system defaults to a before/after view comparing:
  - drift delta,
  - rewrite delta,
  - escalation delta,
  - publish conflict delta

#### Step 2 — Inspect residual risk
- The user sees one low-volume audience still carrying tail mismatch
- The system must distinguish:
  - acceptable residual,
  - unacceptable residual

#### Step 3 — Make closure judgment
- The user decides through Closure Judge whether to:
  - close and monitor,
  - continue with a lightweight follow-up
- The system records closure rationale rather than only “done”

#### Step 4 — Return to homepage
- The user returns to `Command Center`
- The system settles the cycle into recent recovered cycles
- Recovery Snapshot becomes not merely lower numbers, but a reusable governance case

### Design emphasis
Closure must carry a recovery criterion, not only exhaustion.

---

## 9. Usage rules
Any future flow expansion should confirm:
1. the trigger signal is system-level, not frontline-desktop noise,
2. the flow contains at least one explicit command decision,
3. the system reflects propagation, not only success,
4. the ending answers “did alignment recover?” and not only “was the task completed?”

If a flow only describes task processing and not how the tower interprets, commands, propagates, and restores, it is not yet Cygnus enough.
