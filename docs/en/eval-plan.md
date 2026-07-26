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
Cygnus should not depend on a single evaluation method.

### 6.1 Deterministic verifiers
Prefer deterministic checks when the truth is crisp.

Examples:
- required citations present
- trace refs resolve
- audience visibility is legal
- publication state transition is legal
- unapproved publish is blocked

### 6.2 Fixture-based offline tasks
Use fixed task fixtures for repeatable regression detection.

Suggested fixture families:
- refund policy by plan tier
- known issue by product version
- region-specific feature availability
- stale article vs new release note conflict
- ticket-cluster to troubleshooting-flow conversion

### 6.3 Judge-assisted checks
Use an evaluator model only where deterministic truth is insufficient.

Good uses:
- answer clarity
- troubleshooting usefulness
- whether an escalation explanation is understandable

Important rule:
- judge-assisted evals should be grounded on the retrieved evidence and trace, not only on raw output text

## 7. Recommended starter regression gates
These are recommended **initial** gates, not final permanent thresholds.

### 7.1 Merge-blocking gates
- publish-policy suite must pass 100%
- approval-required fixture set must pass 100%
- wrong-audience fixture set must pass 100%
- retrieval relevance suite must not regress beyond an agreed tolerance

### 7.2 Pre-rollout gates
- citation coverage for external answers should stay above the agreed minimum
- unsupported / unsafe answer cases should escalate rather than guess
- freshness-sensitive fixtures should not serve stale variants when fresh evidence exists

## 8. Business-layer metrics
These are the metrics that matter after the workflow is technically correct.

Recommended business metrics:
- human rewrite rate
- suggestion acceptance rate
- unsupported answer rate
- wrong-audience rate
- freshness SLA
- ticket-cluster to draft conversion rate
- review-to-publish cycle time

This is where Cygnus proves value beyond “the agent looked smart.”

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

## 11. Suggested first implementation order
1. deterministic publish / approval / audience fixtures
2. retrieval + traceability offline fixtures
3. drafting fixtures
4. online support KPIs and alerts
5. judge-assisted quality layer for fuzzy answer quality

## 12. Current conclusion
The most important Cygnus evals are not generic “agent benchmark” scores.

The strongest eval shape is:
- deterministic governance correctness
- domain-specific offline fixtures
- online business feedback

That matches the product definition much better than benchmark-chasing.

## 13. References
- AI Engineering from Scratch — Eval-Driven Agent Development  
  https://github.com/rohitg00/ai-engineering-from-scratch/tree/main/phases/14-agent-engineering/30-eval-driven-agent-development
- AI Engineering from Scratch — Eval Harness with Fixture Tasks  
  https://github.com/rohitg00/ai-engineering-from-scratch/tree/main/phases/19-capstone-projects/27-eval-harness-fixture-tasks
- AI Engineering from Scratch — Observability with OTel Traces  
  https://github.com/rohitg00/ai-engineering-from-scratch/tree/main/phases/19-capstone-projects/28-observability-otel-traces
- Anthropic — Building Effective AI Agents  
  https://www.anthropic.com/engineering/building-effective-agents
