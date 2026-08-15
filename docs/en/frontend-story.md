# Support Brain for SaaS — Frontend Behavior Story

## 1. Writing contract
This document describes only two things:
- user behavior,
- expected system behavior.

It does **not** describe:
- component implementation,
- frontend stack,
- API design,
- visual mock fidelity.

## 2. Overall frontend posture
Users should not feel like they are entering a “workspace.”

They are entering:
**a support command layer that shows system movement, lets them shift priority, and issues coordination moves.**

Every page family should therefore follow one order:
1. show where the system is moving,
2. help decide what should move next,
3. let the user issue moves and see propagation.

## 3. Page family 1: Command Center / Overview

### User behavior
- Scan global movement first.
- Compare pressure across queues, topics, audiences, and channels.
- Identify the highest-leverage intervention for today.
- Judge which problems are local and which are spreading.

### Expected system behavior
- Rank the changes most worthy of leadership intervention first.
- Make movement and blast radius more visible than static objects.
- Show links to release, incident, policy, or publish movement.
- Let the user move directly into coordination rather than browsing irrelevant details.

## 4. Page family 2: Queue / Topic Coordination

### User behavior
- Select a queue or topic that is heating up or losing control.
- Judge who is affected, why it matters now, and who should handle it.
- Compare priority across multiple queues.
- Issue different next moves for different queues.

### Expected system behavior
- Show relationships among the queue/topic, knowledge objects, audiences, sources, and feedback.
- Make required team intervention explicit.
- Let the user route, escalate, send to review, or constrain publish from the queue layer.
- Show downstream impact before action is confirmed.

## 5. Page family 3: Knowledge Review Queue

### User behavior
- Review which suggested knowledge changes need attention.
- Judge what should be handled first.
- Decide whether to approve, reject, request evidence, or re-route ownership.

### Expected system behavior
- Emphasize why this draft matters now, not just that it exists.
- Show linked risk, affected audience, downstream surfaces, and evidence strength.
- Help users coordinate review order in batches, not just handle items one by one.
- Preserve a “needs more evidence” middle state instead of forcing false certainty.

## 6. Page family 4: Knowledge Object Workspace

### User behavior
- Open an Answer Card, Troubleshooting Flow, Policy Rule, or Known Issue Page.
- Understand its status, version, evidence, and audience fit.
- Decide whether it should be revised, split by audience, or restricted externally.

### Expected system behavior
- Present operational meaning before full editing depth.
- Quickly show which surfaces, audiences, and queues the object affects.
- Make version changes, exceptions, and superseded history easy to read.
- Allow coordination actions from the object layer itself.

## 7. Page family 5: Audience / Publish Rules

### User behavior
- See which audiences and channels currently consume an object.
- Decide whether to restrict, expand, differentiate, or delay publication.
- Confirm blast radius before changing visibility.

### Expected system behavior
- Treat audience and channel differences as first-class operational objects.
- Show who is affected before publish / unpublish / restrict actions.
- Make internal vs external consequences explicit.
- Reflect propagation status after action, not just button success.

## 8. Page family 6: Sources / Evidence Health

### User behavior
- Check which sources are healthy, stale, or failing.
- Judge whether a knowledge problem is caused by content, source, or sync failure.
- Decide whether to repair the source before the object.

### Expected system behavior
- Connect source health to knowledge risk rather than isolating it as a backend page.
- Trace source failures to affected objects and downstream consequences.
- Explain source-originated knowledge problems in product-operational terms.

## 9. Page family 7: Copilot / Downstream Surface Feedback

### User behavior
- Check whether control-tower commands changed frontline behavior.
- Observe where suggestions are still rewritten, rejected, or escalated.
- Judge whether the system is re-aligning.

### Expected system behavior
- Treat rewrite, reject, and escalate as control feedback loops, not isolated events.
- Show where downstream surfaces still diverge from published knowledge.
- Let downstream behavior reshape upstream governance priority.

## 10. Behavioral chains across page families
- **Chain A:** global risk -> queue/topic coordination -> route/review/publish move.
- **Chain B:** object issue -> object workspace -> audience/publish impact -> downstream propagation adjustment.
- **Chain C:** downstream rewrite spike -> object/queue/source intervention.

## 11. Anti-patterns for frontend behavior
The frontend story should not make users feel like they are:
- processing tickets one at a time,
- approving AI suggestions one at a time,
- browsing a knowledge tree,
- watching a dashboard that cannot change the system.

It should make them feel like they are:
- detecting movement,
- setting priority,
- issuing coordinated interventions,
- checking whether the support system re-aligned.

## 12. Validation rule
If a page cannot answer at least one of these questions, it is drifting away from the complete story:
- What system-level movement does this page help the user see?
- What priority does it help the user decide?
- What coordination move does it let the user issue?
- What downstream propagation does it help the user observe?
