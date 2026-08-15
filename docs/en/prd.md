# Support Brain for SaaS — Product Definition / PRD

## 1. One-line definition
**Support Brain for SaaS** is an **Arkon-enhanced support knowledge brain** that does not replace Zendesk or Intercom. It compiles, reviews, and distributes support knowledge to AI agents and human support teams so answers come from one auditable, audience-aware, publishable source of truth.

## 1.1 Relationship to Arkon
Cygnus / Support Brain is not defined as a product that merely borrowed inspiration from Arkon.

For this project, the intended relationship is:
- **Arkon** is the foundational **LLM wiki / knowledge-compilation / RAG implementation substrate**
- **Support Brain for SaaS** is the **support-domain vertical enhancement** built on top of that substrate
- **Cygnus** is the repo/product surface where that Arkon-enhanced support product is being defined

In practical terms, Arkon is expected to contribute the underlying knowledge-system mechanics such as:
- source ingest and normalization patterns
- LLM-wiki style knowledge compilation
- draft / review / publish mechanics
- knowledge retrieval substrate

But the Support Brain product adds the support-specific layer that Arkon alone does not define:
- support-native knowledge objects
- audience-aware support answers
- support policy and escalation logic
- support-specific freshness / drift / feedback loops

So the right mental model is not:
- "a totally separate new product unrelated to Arkon"

It is:
- **"an Arkon-enhanced support knowledge operating system for SaaS support teams"**

## 2. What the product is not
It is not:
- another customer-facing support bot
- a generic RAG or generic knowledge base product
- a pure search tool
- a GTM or sales-narrative package

## 3. Problem statement
Most SaaS support teams already have:
- Help Center / docs
- Zendesk / Intercom / Freshdesk
- Confluence / Notion / internal SOPs
- resolved tickets and chat transcripts
- release notes, incident updates, and known-issue records

Yet the knowledge system still breaks in five ways:
1. **Fragmentation** — knowledge is scattered across docs, tickets, chats, and release records
2. **Staleness** — answers do not keep up with product/version/policy changes
3. **No audience control** — different plans, regions, and versions need different answers
4. **No structured capture** — repeated support work does not become reusable knowledge assets
5. **No traceability** — leaders cannot see why AI answered incorrectly or which source must be fixed

## 4. Product hypothesis
If support knowledge is compiled into reviewable, publishable, traceable objects and then distributed to support copilots, help centers, and AI agents, then:
- answer quality becomes more consistent
- updates propagate faster
- audience-specific answers become controllable
- support teams can convert ticket experience into knowledge assets
- AI failures can be traced to knowledge gaps instead of vague model blame

## 5. Core users
### Primary users
- Head of Support
- Support Ops / Knowledge Manager
- Senior support agent / escalation lead

### Secondary users
- CX / Product Education
- Product / PMM in collaboration or read-only roles
- internal AI and support-copilot consumers

### Deferred users
- end customers interacting directly with AI

## 6. Positioning
### Category
**Support knowledge operating system**

### Positioning statement
For SaaS support teams already running on an existing helpdesk stack, Support Brain is a **knowledge control layer** above Zendesk, Intercom, or an in-house support system. It does not replace ticketing or chat systems. It turns support knowledge into a compiled, reviewable, traceable, audience-aware answer system.

### Competitive framing
- **vs. Zendesk / Intercom AI**: those are closer to answer-execution layers; Support Brain is the knowledge-governance layer
- **vs. generic RAG**: RAG retrieves chunks; Support Brain manages support-native objects and publishing control
- **vs. internal wiki**: a wiki stores information; Support Brain compiles, reviews, distributes, and closes the feedback loop

## 7. Core principles
1. **Knowledge before answer**
2. **Support-native objects over anonymous chunks**
3. **Audience-aware by design**
4. **Human-in-the-loop by default**
5. **Traceability first**
6. **Freshness matters**

## 8. Core knowledge objects
The first-pass model centers on:
- **Answer Card** — customer-facing standard answer
- **Troubleshooting Flow** — problem-solving flow
- **Policy Rule** — refund, cancellation, SLA, permission, or entitlement rule
- **Known Issue Page** — known issue with workaround
- **Escalation Route** — when and where to escalate
- **Audience Variant** — plan / region / version-specific answer variant

These are closer to the support team's real unit of work than raw chunks.

## 9. V1 boundary
### V1 focus
The first product phase should prioritize:
- internal support-copilot knowledge layer
- knowledge compiler / review / publish workflow
- ticket-to-knowledge suggestion
- audience-aware search and answer retrieval
- traceability and coverage insight

### V1 not focus
The first phase should not prioritize:
- customer-facing bot interaction design
- action layer automation
- GTM / pricing / sales collateral
- deep technical architecture lock-in

## 10. Key product capabilities
1. Multi-source ingest
2. Support-semantic normalization
3. Ticket-to-knowledge reduction
4. Knowledge object planning
5. Review and publish control
6. Audience-aware retrieval
7. Coverage / drift observability
8. Source traceability

## 11. Product surfaces (high level)
### Primary control surface
- **Support Mission Control** — the support-lead / support-ops command surface for global state, risk, priority, and coordination

### Supporting surfaces
- Knowledge Review Console
- Coverage & Drift Dashboard
- Knowledge Object Workspace
- Source Connectors / Sync Status
- Ticket Cluster Insights
- Publication & Channel Rules
- Agent Copilot Surface (a supporting surface, not the product center)

## 12. Success definition for this stage
This first-pass document package succeeds when it aligns everyone on:
- what the product is and is not
- which support-knowledge problem it solves
- what the first object model is
- how the first lifecycle works
- what is explicitly deferred
- how AI agents, human agents, and help-center channels share one knowledge source

## 13. Future directions (boundary only)
- V2: customer-facing answer engine
- V3: action layer
- deeper permissions / compliance / regulated-topic controls
- deeper analytics / ROI / knowledge-health scoring
