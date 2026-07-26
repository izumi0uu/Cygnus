# Support Brain for SaaS — Information Architecture / Page Structure

## 1. Goal
This document defines the first-pass product structure, not high-fidelity UI. It answers:
- what core modules operators will see
- how those modules collaborate around support knowledge objects
- which surfaces belong to V1 versus future phases

## 2. Top-level product surfaces
### A. Knowledge Review Console
Purpose: review AI-suggested creates/updates to knowledge objects and decide whether to publish.

Key views:
- Draft Queue
- Diff Review
- Source Evidence Panel
- Audience Variant Comparison
- Publish Decision Bar

### B. Knowledge Object Workspace
Purpose: view, edit, version, and manage existing knowledge objects.

Key views:
- Object List
- Object Detail
- Relationship Graph
- Version History
- Status / Ownership

### C. Coverage & Drift Dashboard
Purpose: identify missing topics, stale objects, and answers frequently rewritten by humans.

Key views:
- Coverage Gaps
- High Rewrite Topics
- Freshness Alerts
- Audience Coverage Matrix
- Source Drift Signals

### D. Ticket Cluster Insights
Purpose: convert repeated ticket patterns into reviewable knowledge suggestions.

Key views:
- Cluster List
- Cluster Summary
- Suggested Object Type
- Draft Recommendation
- Acceptance / Rejection Actions

### E. Source Connectors & Sync Status
Purpose: manage input sources and sync health.

Key views:
- Connector Catalog
- Sync History
- Parse Failures
- Source Priority Rules
- Access Scope Settings

### F. Publication & Channel Rules
Purpose: control which knowledge objects can be used by which channels.

Key views:
- Channel Matrix
- Internal vs External Access
- Audience Targeting Rules
- Region / Plan / Version Filters
- Publish History

### G. Agent Copilot Surface
Purpose: consume published knowledge inside support work, not govern knowledge itself.

Key views:
- Suggested Answers
- Related Knowledge Objects
- Source Trace
- Escalation Guidance
- Feedback / Rewrite Capture

### H. Command Center / Morning Brief
Purpose: act as the governance command entry to review, re-ranking today's highest-leverage items by risk instead of listing drafts by creation time. It is the risk-ranked entry to the Review Console (A), not a separate content store.
Status: domain logic implemented (`cygnus/review/briefing.py`); UI not built.

Key views:
- Situation Frame (today's system tension)
- Priority Stack (re-ranked by Review Risk Type)
- per-item affected audience / downstream surface / Owner State

### I. Propagation Ledger
Purpose: after publish, show where a command propagated and where it is blocked. It is the post-publish view of Publication & Channel Rules (F).
Status: domain logic implemented (`cygnus/publish/propagation.py`); UI not built.

Key views:
- Propagation Status per supporting surface (synced / pending / failed / manual_action_required)
- Blocked Stage column
- follow-up command entry

### J. Recovery Window
Purpose: around a single governance action, answer "did the system become more consistent?", showing before/after deltas and unresolved points. It verifies whether governance actually took effect.
Status: planned (maps to Jira E4 / CYG-16, CYG-17); not yet implemented.

Key views:
- before/after deltas (changes in rewrites / escalations / coverage gap / drift / publish conflict)
- residual risk and unresolved loops
- next-command entry

## 3. Recommended primary navigation
- Command Center / Morning Brief
- Review Queue
- Knowledge Objects
- Ticket Insights
- Coverage
- Sources
- Publish Rules
- Propagation Ledger
- Copilot
- Recovery Window (planned)

## 4. Core page flows
### Flow 1: From ticket cluster to published knowledge
1. Ticket Insights detects a repeated pattern
2. A draft knowledge suggestion is created
3. Review Console checks evidence and object type
4. Workspace edits object details and audience variants
5. Publish Rules ships the object to internal/external channels

### Flow 2: From drift signal to knowledge refresh
1. Coverage Dashboard finds freshness or drift issues
2. Operator opens the object detail
3. Source diffs, release notes, or known-issue evidence are inspected
4. A new draft version is created
5. After review, the new version is republished

### Flow 3: Copilot usage and feedback write-back
1. Copilot suggests an answer
2. Agent checks traceability and audience fit
3. Agent rewrites, escalates, or rejects the answer
4. Feedback flows back into coverage and rewrite signals

## 5. Object-to-surface relationship
- **Answer Card**: Review / Workspace / Copilot / Publish Rules
- **Troubleshooting Flow**: Review / Workspace / Copilot
- **Policy Rule**: Workspace / Publish Rules / Copilot
- **Known Issue Page**: Coverage / Workspace / Copilot
- **Escalation Route**: Workspace / Copilot
- **Audience Variant**: Review / Workspace / Publish Rules

## 6. V1 IA boundary
### Included in V1 depth
- Command Center / Morning Brief (command entry; domain logic implemented, UI not built)
- Review Queue
- Knowledge Objects
- Ticket Insights
- Coverage dashboard
- basic Source Connector views
- basic Publish Rule controls
- Propagation Ledger (domain logic implemented, UI not built)
- Copilot answer-consumption surface
- Recovery Window (planned, not yet implemented — maps to Jira E4)

### Deferred from V1 depth
- full customer-bot conversation builder
- action execution center
- enterprise-grade analytics customization
- pricing/admin/billing center

## 7. IA principles
1. **Object-first, not file-first**
2. **Review is central, not secondary**
3. **Copilot consumes knowledge; it is not the whole product**
4. **Coverage and drift are operational, not decorative**
5. **Source trace should be one click away from every answer**
