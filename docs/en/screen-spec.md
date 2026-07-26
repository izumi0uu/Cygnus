# Support Brain for SaaS — Screen Spec

## 1. Purpose
This document turns the page-level story map into per-screen specification.

It defines:
- why each screen exists,
- what problem the user is solving there,
- which regions the screen should contain,
- which meaningful actions the user can issue,
- which system states must be reflected.

## 2. Shared screen anatomy across critical surfaces

### A. Situation Frame
At the top of the screen, answer:
- why the user is here,
- what the current operational tension is,
- what happens if nothing moves.

### B. Command Spine
A persistent strip or rail showing whether the current step is:
Observe / Frame / Route / Change / Propagate / Verify.

### C. Main Field
The screen’s primary judgment or action zone.

### D. Consequence Lens
Before a major action, show blast radius, affected audiences, downstream surfaces, and ownership changes.

### E. Propagation Theater
After action, show:
- whether it propagated,
- where it propagated,
- what is blocked,
- whether secondary risk was triggered.

## 3. Screen 01 — Command Center / Morning Command Brief

### Core job
Turn “what matters most in the support system today” into a daily command briefing.

### Entry conditions
- Default landing after login
- Returning to global view after an intervention
- Reassessing the whole system after release / incident / drift spikes

### Primary user question
- Where is the whole system moving now?
- Which 3 things deserve my attention first?

### Key regions
1. **Briefing Header**
   - One-sentence summary of the day’s system tension
2. **Priority Stack**
   - Highest-priority system movements
3. **Movement Grid**
   - Queue / topic / audience / channel movement view
4. **Command Queue Preview**
   - Active important commands already in motion
5. **Recovery Snapshot**
   - Whether recent commands improved alignment

### Primary actions
- Open a high-priority movement
- Mark a movement as intervention-worthy
- Enter Queue / Topic Coordination
- Open Propagation Ledger to inspect last command cycle

### Required states
- Calm / Stable
- Emerging risk
- Multi-surface spread
- Incident-linked spike
- Leadership intervention overdue

### Must never feel like
- a BI overview,
- a ticket report,
- a flat card gallery.

## 4. Screen 02 — Queue / Topic Coordination Board

### Core job
Help the user decide who should move, what should move first, and what type of move is needed around a queue or topic.

### Primary user question
- Who is affected here?
- Who should own it?
- Is this a review move, publish move, source move, or escalation move?

### Key regions
1. **Situation Frame**
2. **Decision Constellation**
   - Relationship view across queue/topic/object/audience/source
3. **Intervention Ladder**
   - route / assign / escalate / review / publish constraint
4. **Owner & Load Strip**
   - Which team has capacity or should receive the move
5. **Consequence Lens**

### Primary actions
- route to reviewer/team
- escalate route
- push into urgent review
- open object control room
- pause or constrain external propagation

### Required states
- Single-zone issue
- Cross-audience issue
- Cross-team issue
- Ambiguous ownership
- No-safe-route-yet

### Creative rule
Decision Constellation must help real priority and ownership judgment, not behave like decorative graph art.

## 5. Screen 03 — Coverage & Drift Radar

### Core job
Reveal where drift is accumulating before it fully explodes.

### Primary user question
- Where is the system going stale?
- What looks stable on the surface but is already drifting underneath?

### Key regions
1. **Drift Weather Layer**
2. **Coverage Gap Matrix**
3. **Audience Risk Strip**
4. **Source vs Object Attribution Panel**
5. **Suggested Intervention Entry**

### Primary actions
- drill into drift pocket
- open related source / object / publish surface
- initiate refresh / review / source repair move

### Must never feel like
- a static coverage report,
- a KPI dashboard.

## 6. Screen 04 — Knowledge Review Queue

### Core job
Treat review as the governance execution queue created by command decisions.

### Primary user question
- Which drafts matter most right now?
- Which drafts are direct responses to system-level risk?

### Key regions
1. **Command-origin Tag**
   - Which upstream command generated this item
2. **Priority Re-stack Lane**
   - Reordered sequence after command changes
3. **Evidence Strength Column**
4. **Audience Impact Column**
5. **Decision Footer**
   - approve / reject / request evidence / reroute

### Primary actions
- bulk reorder review priority
- bulk change ownership
- review one draft
- jump back to originating system tension

### Required states
- Needs decision now
- Evidence incomplete
- Waiting on owner
- Safe to defer

## 7. Screen 05 — Knowledge Object Workspace / Control Room

### Core job
Make an object legible first as a system node, then as content.

### Primary user question
- Which queues, audiences, and surfaces does this object affect?
- Should I change content, audience logic, or visibility?

### Key regions
1. **Object Gravity Panel**
2. **Version / State Rail**
3. **Audience Variant Pane**
4. **Source Evidence Drawer**
5. **Command Actions Area**
   - revise / split / restrict / escalate / send to review

### Primary actions
- revise object
- adjust audience variant
- change external visibility
- trigger urgent review
- inspect propagation impact

### Must never feel like
- a CMS editor,
- a document backend.

## 8. Screen 06 — Audience / Publish Command Center

### Core job
Make publish feel like a scoped command with explicit consequence.

### Primary user question
- Who should see this?
- If I open or tighten this now, what will it touch?

### Key regions
1. **Audience Scope Summary**
2. **Channel Gate Matrix**
3. **Blast Radius Preview**
4. **Conflict Warnings**
5. **Propagation Theater**

### Primary actions
- publish
- unpublish
- restrict audience
- split variant
- hold propagation

### Required states
- Internal only
- External ready
- Conflict risk
- Propagation blocked
- Partial rollout

## 9. Screen 07 — Source Integrity / Evidence Health

### Core job
Translate source health into command risk instead of technical metrics.

### Primary user question
- Is the system partially blind because source integrity failed?
- Should I repair the source first or contain the downstream consequence first?

### Key regions
1. **Signal Loss Layer**
2. **Source Health Table**
3. **Affected Objects List**
4. **Affected Surfaces Preview**
5. **Repair vs Contain Actions**

### Primary actions
- trigger resync / repair
- contain downstream publish
- escalate to source owner
- lower evidence confidence

## 10. Screen 08 — Copilot / Downstream Reality Check

### Core job
Verify whether control-tower moves changed frontline reality.

### Primary user question
- Are people still rewriting this?
- Which surfaces still haven’t synchronized?

### Key regions
1. **Reality Check Strip**
2. **Rewrite / Reject / Escalate Feed**
3. **Mismatch by Audience View**
4. **Upstream Object Links**
5. **Send Back to Command**

### Primary actions
- mark a feedback cluster as systemic
- jump back to object / queue / publish
- open Recovery Window

## 11. Screen 09 — Propagation Ledger

### Core job
Make command propagation traceable and re-actionable instead of merely logged.

### Primary user question
- Where did my last command go?
- What stage is blocked?
- What follow-up move is still needed?

### Key regions
1. **Command Timeline**
2. **Propagation Theater**
3. **Blocked Stage Column**
4. **Affected Surface Checklist**
5. **Follow-up Command Actions**

### Creative requirement
This should feel like watching a move pass through the system, not reading an audit trail.

## 12. Screen 10 — Recovery Window

### Core job
Help the user judge whether a command cycle actually restored alignment.

### Primary user question
- Was this intervention worth it?
- Is the problem closed or only temporarily suppressed?

### Key regions
1. **Before / After Alignment View**
2. **Rewrite Delta**
3. **Drift Delta**
4. **Escalation Delta**
5. **Continue or Close Decision Area**

### Primary actions
- continue commanding
- mark cycle as closed
- move to long-tail monitoring

## 13. Global lightweight command layer (creative extension)
Recommend a persistent lightweight cross-screen layer:

### Command Ribbon
Not a traditional command palette.
A persistent “current command context strip” that shows:
- the hottest active command,
- the most dangerous unresolved issue,
- the next route / publish / source conflict that deserves renewed judgment.

Its purpose is to keep the user aware that every page is part of one continuous command chain.

## 14. Screen-spec usage rule
Before wireframes or implementation, each screen must confirm:
- it belongs to some part of the Command Spine,
- it enables an explicit observation / coordination / governance action,
- it reflects propagation and recovery rather than only success,
- it preserves the control tower as the protagonist.
