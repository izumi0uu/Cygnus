# Support Brain for SaaS — Loop Boundaries

## 1. Purpose
This document prevents Cygnus from evolving into a system with three overlapping general-purpose agent loops.

It answers:
- which layer is allowed to perform open-ended reasoning
- which layer is restricted to deterministic business logic
- which layer stores which category of state
- which layer owns approval truth
- whether Cygnus internal workflow orchestration is merely a workflow engine or a second agent runtime

## 2. Core conclusion
The correct Cygnus shape is not three agent loops. It is:

1. **Nanobot**: the only general-purpose session-oriented agent loop
2. **Cygnus Harness**: the domain control layer, not a second general-purpose agent
3. **Cygnus Workflow Orchestration**: a business workflow engine, not a third chat brain

One-line summary:
**1 agent loop + 1 domain harness + 1 workflow engine**

## 3. Non-goals
This document does not define:
- UI detail
- database schema
- exact model selection
- detailed SDK implementation

It defines runtime boundaries and responsibility ownership only.

## 4. Three-layer runtime model

## 4.1 Layer A — Nanobot Loop
### Role
The only **open-ended session agent loop**.

### Owns
- multi-turn conversation
- session continuity
- workspace / workbench context
- memory / sustained goals
- general tool proposal
- user-facing planning and decomposition
- synthesis of tool results

### Reasoning it may do
- decide whether to search, read, ask, or call a tool next
- decide when Cygnus domain tools are needed
- generate user-facing explanations, clarifications, and proposals

### Business truth it should not own
- whether a draft may publish externally
- whether an audience variant is valid
- whether a policy rule may bypass approval
- whether evidence is sufficient for approved knowledge

## 4.2 Layer B — Cygnus Domain Harness
### Role
The business control plane, not a second general-purpose agent.

### Owns
- typed domain tools
- schema validation
- permission and approval enforcement
- audit trail
- retrieval orchestration
- domain invariants
- draft / review / publish guardrails

### What kind of “reasoning” is acceptable here
Only:
- controlled, local, goal-bounded domain validation
- small drafting or classification calls with clear risk boundaries
- deterministic or bounded business judgments

### What it must not become
It must not become:
- a new open-ended chat agent
- a new persistent session brain
- a reimplementation of Nanobot memory, planning, or workspace logic

## 4.3 Layer C — Cygnus Workflow Orchestration
### Role
The business workflow orchestrator.

### Owns
- workflow state transitions
- branch / retry / rollback routing
- human approval gates
- step-level resumability
- workflow-level observability

### It should not own
- general chat
- session memory
- user-facing open-ended conversation
- a second free-roaming agent shell

## 5. Which layers may contain loops

## 5.1 Allowed loops
### A. Main loop: Nanobot loop
This is the only general-purpose agent loop.

### B. Workflow loop: Cygnus workflow state progression
This is a workflow loop, not a conversational agent loop.

### C. Local mini-loop: Cygnus bounded task loop
Examples:
- a draft-object writer loop with 2-5 steps
- bounded critic/reviewer retries
- evidence-insufficiency retry logic

These mini-loops must satisfy:
- fixed goal
- strict step bound
- no ownership of global session memory
- no ownership of final approval truth
- failure returns structured state rather than endless continuation

## 5.2 Disallowed loop shapes
The following patterns should be explicitly avoided:

### Anti-pattern 1: Nanobot has one planner while Cygnus has another planner
This creates split planning truth.

### Anti-pattern 2: Every workflow step embeds an open-ended agent
This turns the workflow engine into a swarm runtime.

### Anti-pattern 3: Cygnus maintains a second session-memory system
This splits memory truth.

### Anti-pattern 4: Approval is judged both in Nanobot and in Cygnus
Approval truth must have a single durable home.

## 6. State ownership table
| State type | Owning layer | Notes |
|---|---|---|
| session chat history | Nanobot | user conversation and session context |
| workspace / workbench state | Nanobot | session work area state |
| long-session memory | Nanobot | continuity memory |
| active user task decomposition | Nanobot | open-ended task breakdown |
| retrieved business objects | Cygnus | domain object facts |
| draft object state | Cygnus | draft and version truth |
| review queue state | Cygnus | review workflow state |
| approval records | Cygnus | approval truth |
| publication records | Cygnus | publish truth |
| workflow step state | Cygnus workflow engine | workflow state |
| eval traces | Cygnus | domain quality and business traces |
| session-level tool traces | Nanobot + Cygnus refs | Nanobot logs session use; Cygnus retains business trace refs |

## 7. Approval ownership
### Rule
**Approval truth must live in Cygnus.**

Why:
- publication is a business action
- audience, visibility, and policy are domain rules
- approval records must stay auditable alongside drafts, objects, and publication records

### Nanobot's role
Nanobot may:
- initiate an approval request
- show the approval preview to the user
- receive user confirmation

Nanobot should not:
- become the only store of approval records
- write final approval state instead of Cygnus
- bypass Cygnus for high-risk publication

## 8. Memory ownership
### Nanobot memory
Good for:
- user preferences
- current session context
- long-running goals
- active workbench progress

### Cygnus domain state
Good for:
- draft objects
- review notes
- source trace
- publication records
- feedback signals
- drift alerts

### Invariant
**Business object state is not chat memory.**

## 9. Planning ownership
### Nanobot planning
Owns:
- user-facing task planning
- next-step choice inside the session
- deciding which domain tools to call

### Cygnus planning
Allowed only as local planning within domain workflows, such as:
- object-type classification
- evidence-sufficiency judgment
- draft-completeness judgment

### Invariant
Cygnus must not grow into a full user-task planner.

## 10. RAG ownership
### Cygnus owns
- object retrieval
- evidence retrieval
- metadata filtering
- audience gating
- reranking
- source traceability

### Nanobot owns
- deciding when retrieval is needed
- explaining retrieval results
- weaving retrieval results into the session flow

### Invariant
**RAG truth lives in Cygnus, not in Nanobot memory.**

## 11. Workflow orchestration placement rule
Cygnus internal workflow orchestration should serve only workflows that are already clearly business-governance flows, such as:
- knowledge object creation
- freshness refresh
- publish governance

Internal workflow orchestration should not become:
- a general chat orchestrator
- a session memory manager
- a generic copilot runtime
- a second planning shell

## 12. Controlled mini-loop rules
If a workflow step needs an internal LLM mini-loop, it must satisfy:
1. single goal
2. tiny tool set
3. fixed max steps
4. fixed timeout
5. structured failure result
6. no new global session truth
7. no override of approval truth

## 13. Mechanical invariants for implementation
Future implementation should enforce:
- only Nanobot maintains the general session loop
- only Cygnus stores approval truth
- only Cygnus owns business object truth
- Cygnus workflow orchestration only handles business-state transitions
- all high-risk external publication must be validated and logged inside Cygnus

## 14. Quick routing test
If a new capability is mainly answering these questions, it belongs in Nanobot:
- what does the user want next?
- which tool should the session call?
- how should the response be organized?

If a new capability is mainly answering these questions, it belongs in Cygnus:
- is this object valid?
- is this audience variant allowed?
- does this publication require approval?
- is this trace complete?

If a new capability is mainly answering these questions, it belongs in Cygnus workflow orchestration:
- which workflow node is active?
- which edge should execute next?
- which node should retry, roll back, or wait for approval?

## 15. Current conclusion
To avoid maintaining three general-purpose agent loops, Cygnus must preserve:

- **Nanobot = the only general-purpose agent loop**
- **Cygnus Harness = the domain control layer, not a second agent**
- **Cygnus workflow orchestration = the workflow engine, not a third agent**

This is the baseline runtime boundary for future implementation.
