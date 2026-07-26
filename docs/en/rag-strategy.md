# Support Brain for SaaS — RAG Strategy

## 1. Purpose
This document defines the first-pass RAG strategy for Cygnus.

Its goal is not to describe generic retrieval theory.
Its goal is to define how retrieval should work for a **support knowledge operating system** built as an **Arkon-enhanced support product**.

## 2. Core judgment
For this project:
- **Arkon** is the underlying **LLM wiki / knowledge-compilation / RAG substrate**
- **Cygnus / Support Brain** is the support-domain product built on top of that substrate

So Cygnus should not invent a second unrelated generic RAG system.
Instead, it should use an **Arkon-style LLM wiki retrieval substrate** and specialize it for support-domain needs.

The key specialization is:
- retrieval should serve **support knowledge objects**
- not degrade into anonymous chunk search

## 3. What RAG means in this product
In many AI products, "RAG" means:
- embed chunks
- search chunks
- paste chunks into the prompt

That is too weak for Cygnus.

In Cygnus, RAG should mean:
- retrieve **knowledge objects**
- retrieve the **support evidence** behind those objects
- apply **audience-aware filtering**
- preserve **source traceability**
- use retrieval to support **review, publish, freshness, and copilot answering**

So RAG here is not just "retrieval before generation."
It is the **retrieval layer of the support knowledge operating system**.

## 4. Arkon's role in the retrieval stack
Arkon should be treated as the base implementation style for:
- LLM wiki ingestion and normalization
- knowledge compilation into reusable artifacts
- retrieval substrate for stored knowledge
- review / publish oriented knowledge mechanics

Cygnus then adds the support-domain specialization:
- support-native object types
- audience variant handling
- support policy and escalation logic
- freshness / drift loops tied to support operations

## 5. The two retrieval planes
Cygnus should separate retrieval into two planes.

### 5.1 Object retrieval
Purpose:
- retrieve already-compiled support knowledge objects

Primary units:
- Answer Card
- Troubleshooting Flow
- Policy Rule
- Known Issue Page
- Escalation Route

Best for:
- support copilot answers
- policy lookup
- known-issue handling
- answer reuse

Tool surface anchor:
- `search_knowledge_objects`
- `read_knowledge_object`

### 5.2 Evidence retrieval
Purpose:
- retrieve the supporting raw or normalized evidence behind the object layer

Primary units:
- help-center article excerpts
- resolved ticket excerpts
- release-note fragments
- incident updates
- internal SOP excerpts

Best for:
- draft generation
- reviewer inspection
- trace expansion
- freshness refresh
- conflict diagnosis

Tool surface anchor:
- `search_support_evidence`
- `get_source_trace`

### 5.3 Why the split matters
Without the split, the product collapses into:
- a single undifferentiated chunk search surface

With the split:
- object retrieval serves answering
- evidence retrieval serves grounding and governance

## 6. Retrieval architecture
The retrieval layer should be understood as four logical stages:

1. **Index**
2. **Retrieve**
3. **Filter / gate**
4. **Trace / explain**

### 6.1 Index
Cygnus should maintain at least two logical indexes:

- **Object index**
  - one record per support knowledge object or variant

- **Evidence index**
  - one record per evidence unit or normalized excerpt

The object index is the primary answering surface.
The evidence index is the primary grounding surface.

### 6.2 Retrieve
Both indexes should support:
- lexical retrieval
- semantic retrieval
- hybrid retrieval

The default recommendation is:
- **hybrid retrieval** for most domain tasks

Reason:
- lexical helps with exact plan names, feature flags, version strings, SKUs, error codes
- semantic helps with paraphrased support questions

### 6.3 Filter / gate
Retrieval results should pass through domain gates such as:
- audience gate
- visibility gate
- freshness gate
- scope gate

This is where Cygnus differs from generic RAG:
- retrieval is not just relevance-ranked
- it is also **policy-shaped**

### 6.4 Trace / explain
Every retrieved answer object should be able to resolve into:
- source refs
- evidence refs
- freshness markers
- approval / publish context when relevant

This is how the product keeps traceability first-class.

## 7. Hybrid retrieval strategy
Cygnus should default to hybrid retrieval rather than dense-only retrieval.

### 7.1 Why hybrid
Support traffic naturally mixes:
- literal queries  
  e.g. exact plan names, error strings, entitlement labels
- paraphrased queries  
  e.g. "how do we handle canceled uploads?"

Lexical and semantic retrieval fail on different distributions.
Hybrid is the safer default.

### 7.2 Suggested merge pattern
Use a rank-based fusion strategy by default, not score interpolation.

Why:
- lexical scores and dense scores are not naturally comparable
- rank fusion is more stable across index and embedding changes

The exact algorithm can evolve, but the product-level rule is:
- **hybrid first, rerank second, answer later**

### 7.3 Reranking
Reranking is recommended after first-pass hybrid retrieval, especially for:
- object retrieval where top-1 quality matters
- evidence retrieval where trace fidelity matters

But reranking should not become the only relevance mechanism compensating for poor indexing or poor object design.

## 8. Audience-aware retrieval
Audience-aware retrieval is not optional post-processing.
It is a core retrieval concern.

### 8.1 Audience dimensions
Retrieval should be able to respect:
- brand
- product line
- plan tier
- region
- language
- product version
- internal vs external visibility

### 8.2 Product rule
Do not:
- retrieve broadly and hide the mismatch later if it is avoidable

Prefer:
- constrain or rerank by audience as early as possible

### 8.3 Why it matters
In support, the wrong answer often looks plausible.
The most dangerous answer is:
- factually coherent
- semantically relevant
- but for the wrong plan, region, or version

That is why wrong-audience rate is a first-class metric.

## 9. Traceability strategy
Cygnus retrieval must preserve traceability as a domain guarantee.

### 9.1 Required trace links
For any retrieved knowledge object, Cygnus should be able to expose:
- source ids
- evidence ids
- excerpt refs
- freshness markers
- object version / publication status

### 9.2 Object answers vs evidence answers
The preferred copilot answer path is:
- retrieve object -> optionally inspect trace -> answer

Not:
- retrieve raw evidence only -> let the model improvise a final support answer every time

Why:
- objects are the governed layer
- evidence is the grounding layer

### 9.3 Large content handling
Retrieval results should default to:
- summaries
- IDs
- trace refs

Large bodies should be fetched via a second explicit read, not always dumped into the first answering prompt.

## 10. Freshness and drift
RAG quality in Cygnus is not only about relevance.
It is also about freshness.

### 10.1 Freshness signals
Cygnus should consider signals such as:
- release notes
- known issue updates
- incident changes
- repeated unresolved conversations
- manual freshness SLA breaches

### 10.2 Retrieval behavior under staleness
When freshness is uncertain or stale:
- the system may still retrieve the object
- but should surface freshness metadata
- and may route to evidence inspection, revision, or review workflows

### 10.3 Product rule
Freshness should not be hidden behind confident answer wording.

## 11. Query classes
Cygnus retrieval should assume at least these query families:

1. **policy lookup**
2. **troubleshooting lookup**
3. **known issue lookup**
4. **audience-specific entitlement lookup**
5. **draft grounding / review support**
6. **trace inspection**

Different families may deserve different:
- retrieval defaults
- top-k
- rerank profiles
- answering behavior

## 12. RAG and generation boundary
Cygnus should not treat generation as the main product value.

Preferred order:
1. retrieve the right object
2. verify audience fit
3. verify trace / freshness if needed
4. generate or synthesize a user-facing answer

This keeps the product centered on governed knowledge, not prompt stitching.

## 13. Evaluation strategy for RAG
Cygnus RAG should be evaluated at both retrieval and answer layers.

### 13.1 Retrieval evals
Examples:
- object retrieval relevance
- evidence retrieval relevance
- top-1 / top-k recall
- wrong-audience rejection correctness
- trace completeness

### 13.2 Answer-layer evals
Examples:
- citation grounding
- answer relevance
- unsupported-case escalation
- stale-answer avoidance

### 13.3 Governance-sensitive evals
Examples:
- stale object surfaced with warning
- missing evidence blocks draft promotion
- high-risk answer path requests review

## 14. Recommended first implementation order
1. object index + evidence index separation
2. hybrid retrieval on both planes
3. audience-aware filtering
4. source trace expansion
5. freshness markers and drift-triggered refresh hooks
6. retrieval + answer eval fixtures

## 15. Anti-patterns
Avoid these shapes:

### Anti-pattern 1 — generic chunk search as the main product
This weakens the support-object model.

### Anti-pattern 2 — retrieval only in Nanobot memory
RAG truth must remain in Cygnus.

### Anti-pattern 3 — traceability as an optional debug feature
Traceability is core product behavior.

### Anti-pattern 4 — audience filtering only after answer generation
That is too late for many support failures.

### Anti-pattern 5 — dense-only retrieval as ideology
Support domains often need exact lexical matches.

## 16. Current conclusion
Cygnus should absolutely have a strong RAG layer.

But the right shape is:
- **Arkon-style LLM wiki / knowledge substrate underneath**
- **Cygnus support-domain retrieval policy on top**
- **object retrieval + evidence retrieval split**
- **hybrid retrieval + audience gating + traceability + freshness**

That is much stronger than generic retrieval-augmented answering.

## 17. References
- AI Engineering from Scratch — RAG  
  https://github.com/rohitg00/ai-engineering-from-scratch/tree/main/phases/11-llm-engineering/06-rag
- AI Engineering from Scratch — Hybrid Retrieval with BM25 and Dense Embeddings  
  https://github.com/rohitg00/ai-engineering-from-scratch/tree/main/phases/19-capstone-projects/65-hybrid-retrieval-bm25-dense
- AI Engineering from Scratch — RAG Evaluation: Precision, Recall, MRR, nDCG, Faithfulness, Answer Relevance  
  https://github.com/rohitg00/ai-engineering-from-scratch/tree/main/phases/19-capstone-projects/68-rag-eval-precision-recall
