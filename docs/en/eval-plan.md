# Support Brain for SaaS — Eval Plan

## 1. Purpose
This document defines a first-pass evaluation plan for Cygnus.

The goal is not to “evaluate the model” in isolation.
The goal is to evaluate:
- the **session behavior**
- the **domain workflows**
- the **business impact**

## 2. Core judgment
For Cygnus, eval is an **outer loop**, not a launch checklist item at the end.

That means:
- every major failure should map back to an eval case
- every policy guardrail should have a deterministic verifier where possible
- every product change should be judged against a known baseline

## 3. Three-layer eval stack

| Layer | What it evaluates | Primary owner |
|---|---|---|
| Session-layer eval | Nanobot session behavior and tool-use discipline | Nanobot / session runtime |
| Domain-layer eval | Cygnus retrieval, drafting, review, publish, trace correctness | Cygnus |
| Business-layer eval | whether the product is improving support outcomes | Cygnus + support operators |

This split matters because a system can be:
- technically fluent at the session layer
- but still wrong at the business layer

## 4. Session-layer evals
These mostly belong to Nanobot or the outer session harness.

Recommended session eval areas:
- tool-selection accuracy
- pause/resume correctness
- session continuity across multi-step work
- refusal / escalation correctness when required context is missing

These are important, but they are not the main product truth of Cygnus.

## 5. Domain-layer eval suites
Cygnus should invest most heavily here.

### 5.1 Retrieval suite
Goal:
- verify that Cygnus retrieves the right knowledge objects and evidence

Suggested checks:
- object retrieval relevance
- evidence retrieval relevance
- wrong-audience rejection correctness
- citation trace completeness
- stale evidence handling

### 5.2 Knowledge drafting suite
Goal:
- verify that Cygnus turns evidence into the right support-native object

Suggested checks:
- object-type classification correctness
- required field completeness
- audience variant coverage
- evidence sufficiency judgment
- draft-to-source grounding

### 5.3 Review and publish suite
Goal:
- verify that governance logic is correct

Suggested checks:
- approval-required cases are correctly paused
- low-risk cases are not over-blocked
- publish policy correctness
- illegal state transition rejection
- stale draft rejection

### 5.4 Copilot answer suite
Goal:
- verify that support-facing answers are usable and grounded

Suggested checks:
- citation grounding
- audience-appropriate answer selection
- escalation correctness when unsupported
- known-issue answer routing

## 6. Evaluation method mix
Cygnus should use the narrowest evaluation method that can establish the relevant truth. CYG-117 implements the offline deterministic domain layer only.

### 6.1 Deterministic verifiers
Use deterministic checks when the truth is crisp.

Examples:
- required citations are present
- trace refs resolve
- audience visibility is legal
- fresh evidence wins when stale guidance conflicts
- unsupported requests fall back, restrict, or escalate instead of exposing a direct answer
- approval and publish-policy outcomes match the existing governance path

### 6.2 CYG-117 fixed production-shaped corpus
`production_eval_cases()` returns ten cases, sorted by stable `case_id`: exactly two cases in each of these five families.

| Family identifier | Fixture scope |
|---|---|
| `plan_tier_refund` | refund policy by plan tier |
| `product_version_known_issue` | known issue by product version |
| `region_feature_availability` | region-specific feature availability |
| `freshness_conflict` | stale guidance conflicting with fresher evidence |
| `ticket_cluster_draft` | ticket-cluster evidence supporting an unpublished troubleshooting draft and its policy expectations |

The corpus includes positive and negative audience boundaries, supported and unsupported queries, fresh/stale conflicts, an unpublished troubleshooting draft, and publish-policy expectations. “Production-shaped” means the fixtures use Cygnus domain objects and evidence contracts; it does not mean they read production data or call a provider.

### 6.3 Methods outside the CYG-117 gate
Judge-assisted checks may remain useful where deterministic truth is insufficient, such as answer clarity or troubleshooting usefulness. They are not part of CYG-117: the gate invokes no evaluator model and produces no judge-model score.

Any later judge-assisted evaluation should be grounded on retrieved evidence and trace rather than raw output text alone.

## 7. CYG-117 deterministic domain eval gate

### 7.1 Command and report contract
Run the gate from the repository root:

```bash
uv run python scripts/domain_eval_gate.py
```

Stdout is the stable, sorted JSON serialization of `EvalReport.to_dict()`: suite status, aggregate case/check totals, and case results ordered by `case_id`, including each applicable check and failure detail. `--quiet` suppresses stdout without changing the status contract.

The command exits `0` only when `report.passed` is true—every case and every applicable check passed. It exits `1` when any case or check fails. CI should use that process status as the merge-blocking signal rather than parsing prose.

### 7.2 Merge-blocking checks
CYG-117 has no tolerance band or judge-model threshold. Every applicable deterministic check must pass:
- `object_retrieval`
- `audience_restriction`
- `trace_resolution`
- `citation_grounding`
- `freshness_preference`
- `unsupported_escalation`
- `approval_required`
- `publish_policy`

Expected object and evidence refs are required subsets; forbidden object refs must not appear in either the answer or alternatives. Supported answers fail trace/citation checks when required trace or evidence IDs are absent. Unsupported cases must return fallback, escalation, or restricted truth without exposing a direct answer.

### 7.3 Runtime and truth boundaries
- Retrieval runs through the existing `GovernedSessionBridge`; publish-policy expectations run through the existing `GovernedPublishTools.validate_publish_policy`. The gate does not restate audience, lifecycle, freshness, escalation, approval, or publish rules.
- Fixtures build domain objects and evidence directly. They do not import `sample_*`, use substitute fallback fixtures, read the database, or call live networks/providers. Expected fallback/restricted/escalation dispositions are observable outcomes, not fixture-source fallbacks.
- Session memory is not retrieval or policy truth.
- Judge models are outside this gate.
- The report is deterministic regression evidence only. It does not exercise or prove the durable feedback-routing seam, feedback-route worker execution, online business KPI instrumentation, or business-impact evidence.

## 8. Business-layer metrics outside this gate
The following remain recommended business measures for a separately instrumented online layer:
- human rewrite rate
- suggestion acceptance rate
- unsupported answer rate
- wrong-audience rate
- freshness SLA
- ticket-cluster to draft conversion rate
- review-to-publish cycle time

CYG-117 neither exercises feedback routing nor measures these KPIs. A passing domain report must not be presented as evidence of route execution or business impact.

## 9. Failure-to-eval loop
Every real failure should produce one of these outcomes:

1. add a new fixture
2. tighten a deterministic verifier
3. add a new monitoring alert
4. mark the issue as an unresolved product question

If failures do not feed back into the eval suite, the system will keep relearning the same mistake.

## 10. Observability requirements
Eval quality depends on trace quality.

Cygnus should retain enough trace structure to answer:
- which evidence was used
- which object/draft was touched
- which policy gate fired
- which approval id was involved
- which publication record was produced

Without that, evaluator outputs become hard to trust.

## 11. Recommended next evaluation layers
1. grow deterministic cases from observed failures without weakening the fixed gate contract
2. add broader drafting fixtures where observable contracts exist
3. instrument online support KPIs and feedback-route worker outcomes only when their durable evidence paths exist
4. consider a judge-assisted layer only for quality dimensions deterministic checks cannot establish

## 12. Current conclusion
The CYG-117 gate makes deterministic governance correctness and domain-specific offline fixtures merge-blocking. It evaluates the Cygnus domain control plane through existing governed retrieval and publish-policy paths; it does not turn Cygnus into another agent loop or move truth into Nanobot session memory.

Generic agent benchmarks, judge-model quality scores, durable feedback routing, feedback-route worker execution, and online business impact remain outside this gate and are not evidenced by its report.

## 13. References
- AI Engineering from Scratch — Eval-Driven Agent Development  
  https://github.com/rohitg00/ai-engineering-from-scratch/tree/main/phases/14-agent-engineering/30-eval-driven-agent-development
- AI Engineering from Scratch — Eval Harness with Fixture Tasks  
  https://github.com/rohitg00/ai-engineering-from-scratch/tree/main/phases/19-capstone-projects/27-eval-harness-fixture-tasks
- AI Engineering from Scratch — Observability with OTel Traces  
  https://github.com/rohitg00/ai-engineering-from-scratch/tree/main/phases/19-capstone-projects/28-observability-otel-traces
- Anthropic — Building Effective AI Agents  
  https://www.anthropic.com/engineering/building-effective-agents
