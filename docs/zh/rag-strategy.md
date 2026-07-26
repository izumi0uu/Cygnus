# Support Brain for SaaS — RAG Strategy

## 1. 目的
本文件定义 Cygnus 的第一版 RAG 策略。

它的目标不是泛泛介绍 retrieval 理论。
它的目标是说明：一个 **Arkon-enhanced support product** 的 **support knowledge operating system**，其 retrieval 到底应该怎么工作。

## 2. 核心判断
对当前项目来说：
- **Arkon** 是底层的 **LLM wiki / knowledge compilation / RAG substrate**
- **Cygnus / Support Brain** 是建立在这个 substrate 之上的 support 领域产品

所以 Cygnus 不应该另外再造一套脱离 Arkon 的 generic RAG 系统。
更合理的做法是：
- 采用 **Arkon-style LLM wiki retrieval substrate**
- 再在其上做 support-domain specialization

这个 specialization 的关键在于：
- retrieval 要服务 **support knowledge objects**
- 而不是退化成匿名 chunk search

## 3. 这个产品里的 RAG 到底是什么意思
很多 AI 产品里，“RAG”通常是：
- embed chunks
- search chunks
- 把 chunks 塞进 prompt

这对 Cygnus 来说太弱了。

在 Cygnus 里，RAG 更准确的含义应该是：
- 检索 **knowledge objects**
- 检索这些对象背后的 **support evidence**
- 应用 **audience-aware filtering**
- 保留 **source traceability**
- 让 retrieval 参与 **review / publish / freshness / copilot answering**

所以这里的 RAG 不只是 “retrieval before generation”。
它是这个 support knowledge operating system 的 **retrieval layer**。

## 4. Arkon 在 retrieval stack 里的角色
Arkon 更适合作为以下能力的底层实现方式：
- LLM wiki ingestion 与 normalization
- knowledge compilation into reusable artifacts
- 存量知识的 retrieval substrate
- 面向 review / publish 的知识机制

而 Cygnus 在此基础上增加 support-domain specialization：
- support-native object types
- audience variant handling
- support policy 与 escalation logic
- 和 support operations 绑定的 freshness / drift loops

## 5. 两个 retrieval 平面
Cygnus 应把 retrieval 明确拆成两个平面。

### 5.1 Object retrieval
目的：
- 检索已经编译好的支持知识对象

主要单位：
- Answer Card
- Troubleshooting Flow
- Policy Rule
- Known Issue Page
- Escalation Route

适合场景：
- support copilot answers
- policy lookup
- known-issue handling
- answer reuse

对应 tool surface：
- `search_knowledge_objects`
- `read_knowledge_object`

### 5.2 Evidence retrieval
目的：
- 检索对象层背后的原始或归一化支持证据

主要单位：
- help-center article excerpts
- resolved ticket excerpts
- release-note fragments
- incident updates
- internal SOP excerpts

适合场景：
- draft generation
- reviewer inspection
- trace expansion
- freshness refresh
- conflict diagnosis

对应 tool surface：
- `search_support_evidence`
- `get_source_trace`

### 5.3 为什么这个拆分重要
没有这个拆分，产品很容易塌缩成：
- 一个没有区别的 chunk search surface

有了拆分之后：
- object retrieval 服务 answering
- evidence retrieval 服务 grounding 与 governance

## 6. Retrieval architecture
这个 retrieval layer 可以理解成四个逻辑阶段：

1. **Index**
2. **Retrieve**
3. **Filter / gate**
4. **Trace / explain**

### 6.1 Index
Cygnus 至少应该维护两个逻辑 index：

- **Object index**
  - 每条记录对应一个 support knowledge object 或 variant

- **Evidence index**
  - 每条记录对应一个 evidence unit 或 normalized excerpt

object index 是主要 answering surface。
evidence index 是主要 grounding surface。

### 6.2 Retrieve
两个 index 都应支持：
- lexical retrieval
- semantic retrieval
- hybrid retrieval

默认建议：
- 大多数 domain tasks 走 **hybrid retrieval**

原因：
- lexical 对 exact plan names、feature flags、version strings、SKUs、error codes 更强
- semantic 对 paraphrased support questions 更强

### 6.3 Filter / gate
retrieval 结果应经过 domain gates，例如：
- audience gate
- visibility gate
- freshness gate
- scope gate

这也是 Cygnus 和 generic RAG 的关键区别：
- retrieval 不只是 relevance-ranked
- 还必须是 **policy-shaped**

### 6.4 Trace / explain
每一个被取回的 answer object，都应该能继续解析出：
- source refs
- evidence refs
- freshness markers
- 如果相关，还能看到 approval / publish context

这是让 traceability 成为一等行为的关键。

## 7. Hybrid retrieval 策略
Cygnus 默认应采用 hybrid retrieval，而不是 dense-only retrieval。

### 7.1 为什么是 hybrid
support 流量天然混合了：
- literal queries  
  例如 exact plan names、error strings、entitlement labels
- paraphrased queries  
  例如 “how do we handle canceled uploads?”

lexical 和 semantic 在不同 query distribution 上各有失败点。
hybrid 是更稳妥的默认值。

### 7.2 建议的 merge pattern
默认应采用 rank-based fusion，而不是 score interpolation。

原因：
- lexical scores 和 dense scores 本身不可直接比较
- rank fusion 对 index / embedding 变动更稳定

具体算法以后可以演进，但产品级规则应该是：
- **hybrid first, rerank second, answer later**

### 7.3 Reranking
在 first-pass hybrid retrieval 之后，建议加 reranking，尤其适合：
- top-1 质量要求高的 object retrieval
- 对 trace fidelity 很敏感的 evidence retrieval

但 reranking 不应变成唯一 relevance 机制，不能拿来补偿糟糕的 indexing 或糟糕的 object design。

## 8. Audience-aware retrieval
Audience-aware retrieval 不是后处理附属能力。
它是 retrieval 的核心组成。

### 8.1 Audience dimensions
retrieval 应能理解：
- brand
- product line
- plan tier
- region
- language
- product version
- internal vs external visibility

### 8.2 产品规则
不要：
- 先广泛检索，再在最后一层勉强隐藏 audience mismatch

更合理的是：
- 尽量在前面就按 audience 约束或 rerank

### 8.3 为什么这件事重要
在 support 场景里，最危险的答案往往不是胡说八道，而是：
- 看起来合理
- 语义上也相关
- 但属于错误的 plan / region / version

这就是为什么 wrong-audience rate 应被当成一等指标。

## 9. Traceability 策略
Cygnus retrieval 必须把 traceability 当作领域保证，而不是可选调试功能。

### 9.1 必要 trace links
对任何一个 retrieved knowledge object，Cygnus 至少应能暴露：
- source ids
- evidence ids
- excerpt refs
- freshness markers
- object version / publication status

### 9.2 Object answers vs evidence answers
更优先的 copilot answer path 应该是：
- retrieve object -> optional trace inspect -> answer

而不是：
- 只取 raw evidence -> 每次都让模型临场 improvisation

原因：
- objects 是治理层
- evidence 是 grounding 层

### 9.3 Large content handling
默认 retrieval 结果应尽量返回：
- summaries
- IDs
- trace refs

大正文应通过二次显式 read 获取，而不是第一次就全部塞进回答 prompt。

## 10. Freshness 与 drift
Cygnus 的 RAG 质量不只由 relevance 决定。
还由 freshness 决定。

### 10.1 Freshness signals
Cygnus 应至少考虑这些 signals：
- release notes
- known issue updates
- incident changes
- repeated unresolved conversations
- manual freshness SLA breaches

### 10.2 Staleness 下的 retrieval 行为
当 freshness uncertain 或 stale 时：
- 系统仍可检索到 object
- 但应显式带 freshness metadata
- 并在必要时路由到 evidence inspection、revision 或 review workflow

### 10.3 产品规则
不能把 freshness 问题隐藏在看起来自信的 answer wording 里。

## 11. Query classes
Cygnus retrieval 至少应假设存在这些 query families：

1. **policy lookup**
2. **troubleshooting lookup**
3. **known issue lookup**
4. **audience-specific entitlement lookup**
5. **draft grounding / review support**
6. **trace inspection**

不同 query family 可能需要不同的：
- retrieval defaults
- top-k
- rerank profiles
- answering behavior

## 12. RAG 与 generation 的边界
Cygnus 不应把 generation 当成主要产品价值。

更合理的顺序是：
1. retrieve the right object
2. verify audience fit
3. verify trace / freshness if needed
4. generate or synthesize a user-facing answer

这样产品中心仍然是 governed knowledge，而不是 prompt stitching。

## 13. RAG 的评估策略
Cygnus 的 RAG 需要同时评估 retrieval 层和 answer 层。

### 13.1 Retrieval evals
例如：
- object retrieval relevance
- evidence retrieval relevance
- top-1 / top-k recall
- wrong-audience rejection correctness
- trace completeness

### 13.2 Answer-layer evals
例如：
- citation grounding
- answer relevance
- unsupported-case escalation
- stale-answer avoidance

### 13.3 Governance-sensitive evals
例如：
- stale object surfaced with warning
- missing evidence blocks draft promotion
- high-risk answer path requests review

## 14. 推荐第一阶段实施顺序
1. object index + evidence index 分离
2. 两个平面都接 hybrid retrieval
3. audience-aware filtering
4. source trace expansion
5. freshness markers 与 drift-triggered refresh hooks
6. retrieval + answer eval fixtures

## 15. 反模式
应避免这些形态：

### 反模式 1 — generic chunk search 成为产品中心
这会削弱 support-object model。

### 反模式 2 — retrieval 真相只留在 Nanobot memory
RAG truth 必须在 Cygnus。

### 反模式 3 — traceability 只是可选 debug feature
Traceability 是核心产品行为。

### 反模式 4 — audience filtering 放到 answer generation 之后
对很多 support failure 来说这已经太晚了。

### 反模式 5 — 把 dense-only retrieval 当成信仰
support 域经常需要精确 lexical match。

## 16. 当前结论
Cygnus 当然应该有强 RAG 层。

但正确结构是：
- **底层是 Arkon-style LLM wiki / knowledge substrate**
- **上层是 Cygnus 的 support-domain retrieval policy**
- **object retrieval + evidence retrieval 分离**
- **hybrid retrieval + audience gating + traceability + freshness**

这比 generic retrieval-augmented answering 强得多。

## 17. 参考资料
- AI Engineering from Scratch — RAG  
  https://github.com/rohitg00/ai-engineering-from-scratch/tree/main/phases/11-llm-engineering/06-rag
- AI Engineering from Scratch — Hybrid Retrieval with BM25 and Dense Embeddings  
  https://github.com/rohitg00/ai-engineering-from-scratch/tree/main/phases/19-capstone-projects/65-hybrid-retrieval-bm25-dense
- AI Engineering from Scratch — RAG Evaluation: Precision, Recall, MRR, nDCG, Faithfulness, Answer Relevance  
  https://github.com/rohitg00/ai-engineering-from-scratch/tree/main/phases/19-capstone-projects/68-rag-eval-precision-recall
