# Support Brain for SaaS — Page-Level Story Map

## 1. What this document solves
The earlier docs already define:
- who the product is a control layer for,
- what visual mood it should carry,
- what interaction posture it should use.

This document moves one layer lower and defines:
**how the full product is organized as a page-level narrative for commanding a support system.**

It is not just a page list. It defines:
- what the user sees first,
- what they judge next,
- where they issue coordination moves,
- how they observe propagation,
- how they determine whether alignment recovered.

## 2. North-star creative spine: Command Spine
To prevent the product from degrading into “a collection of screens,” the experience needs one cross-page creative skeleton:

## Command Spine
Command Spine is not one component name. It is a recurring experience mechanism:

1. **Situation Frame**
   - Every critical page should answer:
     - Why am I here now?
     - Why does this matter?
     - Who is affected?

2. **Command Spine**
   - Every critical flow should make the user feel they are inside one continuous chain:
     - Observe
     - Frame
     - Route
     - Change
     - Propagate
     - Verify

3. **Propagation Theater**
   - After every coordination move, the system should not merely say “success.”
   - It should show:
     - what changed,
     - which queues were reprioritized,
     - which surfaces are already in sync,
     - what remains unresolved.

4. **Recovery Window**
   - Users need to revisit whether their move actually made the system more aligned.
   - This is not an activity log. It is an alignment readback.

## 3. The overall story path
The experience should be organized into five repeating phases:
1. **See movement**
2. **Frame what matters**
3. **Issue command**
4. **Watch propagation**
5. **Verify recovery**

These are not wizard steps. They are the rhythm of the whole product.

## 4. Story map overview

| Phase | User’s core question | Primary page family | Page output | Creative signature |
|---|---|---|---|---|
| See movement | Where is the support system shifting right now? | Command Center | system changes worth intervention | Morning Command Brief |
| Frame what matters | Why is this worth moving now? | Queue / Topic Coordination, Coverage & Drift | risk scope and coordination context | Situation Frame |
| Issue command | What should I change, and who should move? | Review Queue, Object Workspace, Publish Control | routing / review / publish / escalation commands | Command Spine |
| Watch propagation | Where did my move go? | Propagation Ledger, Downstream Feedback | propagation state and remaining gaps | Propagation Theater |
| Verify recovery | Did the system actually re-align? | Recovery / Feedback surfaces | alignment delta | Recovery Window |

## 5. Page families and their narrative role

### A. Command Center / Morning Command Brief
**Narrative role:** opening scene

This is not a dashboard homepage. It is a command briefing for the day’s support movement.

#### User job
- See which queues, topics, audiences, and channels are changing.
- Identify the interventions most worthy of leadership attention.
- Enter a coordination chain.

#### System promise
- Surface the most important change first.
- Keep users out of object-level detail initially.
- Explain the operational consequence of each major movement.

#### Creative signature
**Morning Command Brief**
- The system behaves like a support war-room briefing.
- It does not recite all metrics; it says which 3 moves deserve leadership now.

### B. Queue / Topic Coordination Board
**Narrative role:** theater of judgment

This is not a queue list. It is where users understand why one risk zone matters, who should own it, and what shape intervention should take.

#### User job
- Compare the impact of queues / topics / audiences.
- Decide what moves first.
- Choose whether to route, assign, escalate, or trigger review.

#### System promise
- Compose relationships across sources, objects, queues, and audiences.
- Make required ownership explicit.
- Show that queues are competing for command attention, not merely coexisting.

#### Creative signature
**Decision Constellation**
- A “decision constellation” feel for the relationships among queues, topics, audiences, and objects.
- Not a decorative graph, but a way to sense where risk clusters are forming.

### C. Coverage & Drift Radar
**Narrative role:** early warning layer

Its job is not KPI display. Its job is to reveal what has not exploded yet but is heading there.

#### User job
- Spot coverage gaps and freshness drift.
- Decide whether the problem is local content, version shift, or propagation failure.
- Decide whether to intervene at the source, object, or publish layer.

#### System promise
- Make drift more perceptible than static coverage.
- Present risk accumulation rather than isolated alerts.

#### Creative signature
**Drift Weather Layer**
- Risk appears like a weather system moving in, not like disconnected warning dots.

### D. Knowledge Review Queue
**Narrative role:** governance execution surface

This should not feel like “a stack of drafts.” It should feel like the execution queue created by upstream command decisions.

#### User job
- Decide which changes to review first.
- Judge what needs evidence, urgent approval, or rerouting.
- Process work whose priority has already shifted because of command decisions upstream.

#### System promise
- Treat the review queue as post-command execution, not an isolated list.
- Keep the originating system problem visible.

#### Creative signature
**Priority Re-stack**
- When upstream commands land, the review queue visibly re-stacks to reflect new command order.

### E. Knowledge Object Workspace / Control Room
**Narrative role:** single-object control room

This is not a classic editor page. Users should first understand what role the object currently plays in the wider system.

#### User job
- Understand status, version, evidence, audience fit, and propagation scope.
- Decide whether to revise, split by audience, or restrict exposure.

#### System promise
- Show operational meaning before editing depth.
- Make the object feel like a node with system gravity, not just a page of content.

#### Creative signature
**Object Gravity Panel**
- Emphasizes which queues, audiences, surfaces, and risks this object currently attracts.

### F. Audience / Publish Command Center
**Narrative role:** propagation gate

This page family should feel like an airlock or release gate, not like a settings form.

#### User job
- Decide who should see what, where, and under what constraint.
- Confirm blast radius before changing visibility.
- Observe whether propagation completed.

#### System promise
- Show downstream consequence before publish / unpublish / restrict actions.
- Give strong operational meaning to internal vs external exposure.

#### Creative signature
**Blast Radius Preview**
- A publish change should feel like a consequential release command, not a form submit.

### G. Source Integrity / Evidence Health
**Narrative role:** trustworthiness substrate

This is not a backend admin page. It is the reliability layer of command itself.

#### User job
- Judge whether source failure is contaminating support knowledge.
- Decide whether to repair the source before the object.

#### System promise
- Translate source failure into governance impact.
- Make the user feel that when sources fail, command visibility degrades.

#### Creative signature
**Signal Loss Layer**
- A failing source should feel like partial system blindness, not just a sync error.

### H. Copilot / Downstream Reality Check
**Narrative role:** downstream reality readback

This is where users verify whether control-tower moves changed frontline behavior.

#### User job
- See which suggestions are still rewritten, rejected, or escalated.
- See where downstream surfaces still diverge.
- Judge whether the system is re-aligning.

#### System promise
- Treat frontline rewrite as governance feedback, not local noise.
- Make control effectiveness visible.

#### Creative signature
**Reality Check Strip**
- Shows the gap between upstream command and downstream reality.

### I. Propagation Ledger
**Narrative role:** command propagation stage

This is a new creative page family in this design pass.

It is not just a history log. It shows:
- where an important command traveled,
- what synchronized,
- what got blocked,
- what secondary conflict it created.

#### User job
- Revisit whether a critical command reached all required surfaces.
- Find the break in the propagation chain.
- Issue another move if necessary.

#### System promise
- Treat propagation as first-class information.
- Make “the command was issued but the system is not aligned yet” visible.

#### Creative signature
**Propagation Theater**
- A stage-like reveal of how a move lands through review, publish, copilot, and external surfaces.

### J. Recovery Window
**Narrative role:** alignment recovery view

This is another newly proposed creative page family.

It is not a KPI summary. It helps answer:
**did this intervention actually restore alignment?**

#### User job
- Compare before and after.
- Evaluate rewrite, drift, coverage, escalation, and publish conflict movement.
- Decide whether this command cycle is closed or another move is needed.

#### System promise
- Organize around recovery, not just completion.
- Help the user decide whether to continue commanding.

#### Creative signature
**Before / After Alignment View**
- A recovery judgment surface, not a pretty report.

## 6. Cross-page creative objects
These do not belong to one page only:

### 1. Situation Frame
One sentence that explains why this page deserves the user’s time now.

### 2. Command Spine
Shows whether the user is currently in Observe / Frame / Route / Change / Propagate / Verify.

### 3. Consequence Lens
Before any important action, show scope of effect.

### 4. Propagation Theater
After any important action, show propagation outcome.

### 5. Recovery Window
After a command cycle, show the system’s degree of recovery.

## 7. How to use this story map
When the work moves into wireframes or implementation, every page should first answer:
1. Which of the five phases does it belong to?
2. Is it attached to the Command Spine?
3. Does it enable observation, coordination, or governance?
4. Does it reveal propagation and recovery?

If the answer is no, the page is not yet specific enough to Cygnus.