# Support Brain for SaaS — Agent Harness

## 1. Purpose
This document defines how Cygnus should borrow **agent harness** patterns without turning the product into a generic agent framework.

It answers:
- what the harness is in this project
- what belongs to **Nanobot** vs **Cygnus**
- which budgets, gates, and pause/resume points matter
- what should remain deterministic vs model-driven

## 2. Core judgment
Cygnus should borrow the **discipline** of a harness, not the **product shape** of a generic agent shell.

The useful harness idea is:
- the **harness** is the durable control contract
- the **model** is a proposal engine, not the source of business truth

For Cygnus this becomes:
- **Nanobot harness** = general session harness
- **Cygnus harness** = support-domain control harness
- **Cygnus workflow orchestration** = workflow engine for selected Cygnus governance flows

This preserves the earlier product boundary:
- Nanobot owns how the session runs
- Cygnus owns support-knowledge governance, review, publish, and traceability

## 3. Layered harness model

| Layer | Role | Owns | Must not own |
|---|---|---|---|
| Nanobot session harness | General session runtime | multi-turn loop, workspace, session memory, user-facing planning, generic tool proposal | approval truth, audience policy truth, publish truth |
| Cygnus domain harness | Support-knowledge control plane | typed domain tools, schema validation, policy checks, evidence sufficiency checks, audit trail, publish guardrails | open-ended chat runtime, second session memory, second generic planner |
| Cygnus workflow orchestration | Workflow progression engine | checkpointed business-state transitions, branch/retry/rollback, human approval pauses | generic copilot runtime, free-roaming agent loop |

## 4. What to borrow from the reference harness pattern
The AI Engineering from Scratch harness material is most useful for Cygnus in these places:

1. **Loop contract first**
   - define states, transitions, pause points, and budgets before writing tools

2. **Typed tool registry**
   - tools are named, schema-validated, and risk-classified

3. **Pull points instead of crashes**
   - the runtime yields on approval, missing evidence, or tool/result dependencies

4. **Verification gates**
   - a deterministic layer decides whether a proposed call or transition is allowed

5. **Event stream + observability**
   - traces, refusals, retries, and pauses are first-class artifacts

These ideas fit Cygnus well because they strengthen control, not just autonomy.

## 5. Minimal Cygnus domain harness contract
Cygnus should expose a small, typed task envelope for domain operations.

### 5.1 Suggested task envelope
```json
{
  "goal_type": "retrieve|draft|review|publish|trace|drift_refresh",
  "actor_context": {
    "actor_type": "human_agent|support_lead|ai_copilot|workflow",
    "actor_id": "string"
  },
  "audience_context": {
    "brand": "optional-string",
    "product_line": "optional-string",
    "plan_tier": "optional-string",
    "region": "optional-string",
    "language": "optional-string",
    "product_version": "optional-string",
    "visibility": "internal|external"
  },
  "object_ref": "optional-string",
  "draft_ref": "optional-string",
  "allowed_tools": ["string"],
  "policy_profile": "default|high_risk|internal_only",
  "budgets": {},
  "trace_ref": "optional-string"
}
```

### 5.2 Result contract
The result should stay aligned with `tool-contracts.md`:

```json
{
  "status": "success|error|denied|approval_required|conflict|not_found",
  "summary": "short summary",
  "data": {},
  "trace_ref": "optional-trace-id",
  "warnings": [],
  "errors": []
}
```

## 6. Pull points
In Cygnus, a pull point is a **structured yield**, not a crash.

Recommended pull points:
- `awaiting_tool_result`
- `approval_required`
- `evidence_insufficient`
- `policy_conflict`
- `budget_exhausted`

Important detail:
- Nanobot may present the pause to the user
- Cygnus must remain the durable owner of the domain state behind the pause

## 7. Hook topics
The external harness lessons use lifecycle hooks around planning, tool use, pause, and completion. Cygnus should adapt that idea, but keep the hook surface domain-native.

### 7.1 Recommended first-pass hooks
- `before_tool_call`
- `after_tool_call`
- `before_policy_check`
- `after_policy_check`
- `before_review_request`
- `after_review_request`
- `on_pause`
- `on_budget_exceeded`
- `on_error`
- `on_complete`

### 7.2 Why not expose too many hooks at first
Too many hooks too early turns the harness into a plugin system before the product contract is stable.

Cygnus should first stabilize:
- tool shapes
- policy gates
- approval flow
- traceability fields

Then grow more extension points.

## 8. Budget model
The external harness material emphasizes explicit budgets. Cygnus should keep that idea, but split budgets by layer.

### 8.1 Nanobot session budgets
- max turns
- max tool calls
- max wall-clock seconds

### 8.2 Cygnus domain budgets
- max evidence fetches per task
- max draft revisions per workflow
- max review retries
- max publish attempts
- max unresolved-policy escalations

### 8.3 Boundary detail
Token budget alone is not the important budget in Cygnus.
The more product-native budgets are:
- evidence collection budget
- review retry budget
- governance retry budget

## 9. Verification gates
Cygnus should borrow the idea of a gate chain, but its gates must be support-domain gates rather than generic shell gates.

### 9.1 Recommended gate chain
1. **Tool whitelist gate**  
   Only allowed typed domain tools may run.

2. **Schema validation gate**  
   Arguments must match the tool schema.

3. **Scope gate**  
   The actor and workspace scope must allow the operation.

4. **Audience gate**  
   Requested output must match audience visibility rules.

5. **Freshness gate**  
   Stale evidence or stale object versions may block publish or high-confidence answer generation.

6. **Approval gate**  
   High-risk transitions must pause for approval instead of auto-committing.

7. **Commit gate**  
   External publish must never happen from draft state without the required review and policy checks.

## 10. Observation ledger and traces
The reference harness materials talk about observation budget and event streams. In Cygnus, the ledger must capture domain meaning, not just raw tool output.

### 10.1 Session-side ledger
Usually maintained by Nanobot:
- turn count
- tool count
- wall-clock elapsed
- session transcript refs

### 10.2 Domain-side ledger
Must be maintained by Cygnus:
- evidence refs used
- object refs touched
- draft revisions
- approval ids
- publish ids
- policy decisions
- refusal reasons

This is how Cygnus keeps auditability short-path visible.

## 11. Recommended first implementation slice
The first useful harness slice for Cygnus is:

1. typed tool registry
2. schema validation
3. gate chain
4. pull-point handling for approval / policy conflict / evidence insufficiency
5. event stream and trace ids

Do **not** start with:
- multi-agent orchestration
- open-ended autonomous replanning inside Cygnus
- a second session memory layer

## 12. Anti-patterns
Avoid these shapes:

### Anti-pattern 1 — Cygnus becomes a second generic chat agent
That collapses the Nanobot/Cygnus boundary.

### Anti-pattern 2 — tool validation lives only in prompts
If validation exists only in natural language instructions, it is not a real control plane.

### Anti-pattern 3 — publish guardrails happen only in Nanobot
Approval truth and commit truth must remain in Cygnus.

### Anti-pattern 4 — one giant “agent tool” replaces domain tools
Cygnus needs typed domain verbs, not a single catch-all action hole.

## 13. Current conclusion
Cygnus should absolutely use a harness mindset.

But the correct shape is:
- **Nanobot** keeps the only general-purpose session loop
- **Cygnus** keeps the domain harness
- **Cygnus workflow orchestration** coordinates selected governance workflows inside Cygnus

That is stronger than “just add more agent loops.”

## 14. References
- AI Engineering from Scratch — Agent Loop  
  https://github.com/rohitg00/ai-engineering-from-scratch/tree/main/phases/14-agent-engineering/01-the-agent-loop
- AI Engineering from Scratch — Agent Harness Loop Contract  
  https://github.com/rohitg00/ai-engineering-from-scratch/tree/main/phases/19-capstone-projects/20-agent-harness-loop-contract
- AI Engineering from Scratch — Tool Registry with Schema Validation  
  https://github.com/rohitg00/ai-engineering-from-scratch/tree/main/phases/19-capstone-projects/21-tool-registry-schema-validation
- AI Engineering from Scratch — Verification Gates and Observation Budget  
  https://github.com/rohitg00/ai-engineering-from-scratch/tree/main/phases/19-capstone-projects/25-verification-gates-observation-budget
- Anthropic — Building Effective AI Agents  
  https://www.anthropic.com/engineering/building-effective-agents
