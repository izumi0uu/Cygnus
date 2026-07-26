# Support Brain for SaaS — Eval Plan

## 1. 目的
本文件定义 Cygnus 的第一版评估计划。

目标不是孤立地“评估模型”。
目标是同时评估：
- **session behavior**
- **domain workflows**
- **business impact**

## 2. 核心判断
对 Cygnus 来说，eval 是一个**外层循环**，不是最后上线前才补的清单项。

这意味着：
- 每个重要失败都应该能回落成一个 eval case
- 每个 policy guardrail 都尽量要有确定性 verifier
- 每次产品改动都应和已知 baseline 对比

## 3. 三层 eval 结构

| 层 | 评估什么 | 主要归属 |
|---|---|---|
| Session-layer eval | Nanobot 的 session behavior 与 tool-use discipline | Nanobot / session runtime |
| Domain-layer eval | Cygnus 的 retrieval、drafting、review、publish、trace correctness | Cygnus |
| Business-layer eval | 产品是否真的改善了支持结果 | Cygnus + support operators |

这个拆分很重要，因为一个系统可能：
- 在 session layer 看起来很流畅
- 但在 business layer 仍然是错的

## 4. Session-layer evals
这些大多属于 Nanobot 或外层 session harness。

推荐 session eval 方向：
- tool-selection accuracy
- pause/resume correctness
- 多步任务下的 session continuity
- 在缺少必要上下文时的 refusal / escalation correctness

这些很重要，但它们不是 Cygnus 的核心产品真相。

## 5. Domain-layer eval suites
Cygnus 最应该重投的是这一层。

### 5.1 Retrieval suite
目标：
- 验证 Cygnus 能否取回正确的 knowledge objects 和 evidence

建议检查项：
- object retrieval relevance
- evidence retrieval relevance
- wrong-audience rejection correctness
- citation trace completeness
- stale evidence handling

### 5.2 Knowledge drafting suite
目标：
- 验证 Cygnus 能否把 evidence 变成正确的 support-native object

建议检查项：
- object-type classification correctness
- required field completeness
- audience variant coverage
- evidence sufficiency judgment
- draft-to-source grounding

### 5.3 Review and publish suite
目标：
- 验证 governance logic 是否正确

建议检查项：
- 需要审批的 case 是否正确 pause
- 低风险 case 是否没有被过度阻塞
- publish policy correctness
- illegal state transition rejection
- stale draft rejection

### 5.4 Copilot answer suite
目标：
- 验证支持侧答案是否可用且有依据

建议检查项：
- citation grounding
- audience-appropriate answer selection
- escalation correctness when unsupported
- known-issue answer routing

## 6. Eval 方法组合
Cygnus 不应依赖单一评估方法。

### 6.1 Deterministic verifiers
当真相足够清晰时，优先使用确定性校验。

例如：
- required citations present
- trace refs resolve
- audience visibility is legal
- publication state transition is legal
- unapproved publish is blocked

### 6.2 Fixture-based offline tasks
使用固定 task fixtures 做可重复的回归检测。

建议 fixture 家族：
- 不同 plan tier 下的 refund policy
- 不同 product version 下的 known issue
- region-specific feature availability
- stale article 与新 release note 冲突
- ticket-cluster 到 troubleshooting-flow 的转化

### 6.3 Judge-assisted checks
只有在 deterministic truth 不够时，才用 evaluator model。

适合的使用场景：
- answer clarity
- troubleshooting usefulness
- escalation explanation 是否可理解

重要规则：
- judge-assisted eval 必须尽量基于 retrieved evidence 与 trace，而不是只看输出文本

## 7. 推荐的 starter regression gates
这些是推荐的**初始** gate，不是最终永久阈值。

### 7.1 Merge-blocking gates
- publish-policy suite 必须 100% 通过
- approval-required fixture set 必须 100% 通过
- wrong-audience fixture set 必须 100% 通过
- retrieval relevance suite 不允许超过约定容忍度的回归

### 7.2 Pre-rollout gates
- external answers 的 citation coverage 应保持在约定最低值以上
- unsupported / unsafe answer cases 应该 escalate，而不是猜
- freshness-sensitive fixtures 在存在新证据时，不应继续提供 stale variant

## 8. Business-layer metrics
当 workflow 已经技术上正确后，真正重要的是这些指标。

推荐业务指标：
- human rewrite rate
- suggestion acceptance rate
- unsupported answer rate
- wrong-audience rate
- freshness SLA
- ticket-cluster to draft conversion rate
- review-to-publish cycle time

这是 Cygnus 证明价值的位置，而不是“agent 看起来很聪明”。

## 9. Failure-to-eval loop
每个真实失败，最终都应该进入下面某一种结果：

1. 新增一个 fixture
2. 收紧一个 deterministic verifier
3. 新增一个 monitoring alert
4. 标记为未决产品问题

如果失败不反哺 eval suite，系统就会反复学同样的错。

## 10. Observability 要求
eval 质量依赖 trace 质量。

Cygnus 应至少保留足够结构来回答：
- 用了哪些 evidence
- 触碰了哪个 object / draft
- 触发了哪个 policy gate
- 涉及哪个 approval id
- 产出了哪个 publication record

缺少这些信息，evaluator 输出也会越来越不可信。

## 11. 推荐第一阶段实施顺序
1. deterministic publish / approval / audience fixtures
2. retrieval + traceability offline fixtures
3. drafting fixtures
4. online support KPIs 与 alerts
5. judge-assisted 的模糊质量层

## 12. 当前结论
对 Cygnus 来说，最重要的 eval 不是 generic “agent benchmark” 分数。

更强的 eval 结构是：
- 确定性的 governance correctness
- domain-specific offline fixtures
- online business feedback

这比追 benchmark 更贴合产品定义。

## 13. 参考资料
- AI Engineering from Scratch — Eval-Driven Agent Development  
  https://github.com/rohitg00/ai-engineering-from-scratch/tree/main/phases/14-agent-engineering/30-eval-driven-agent-development
- AI Engineering from Scratch — Eval Harness with Fixture Tasks  
  https://github.com/rohitg00/ai-engineering-from-scratch/tree/main/phases/19-capstone-projects/27-eval-harness-fixture-tasks
- AI Engineering from Scratch — Observability with OTel Traces  
  https://github.com/rohitg00/ai-engineering-from-scratch/tree/main/phases/19-capstone-projects/28-observability-otel-traces
- Anthropic — Building Effective AI Agents  
  https://www.anthropic.com/engineering/building-effective-agents
