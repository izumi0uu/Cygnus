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
Cygnus 应使用能证明相关真相的最窄评估方法。CYG-117 只实现离线、确定性的领域层。

### 6.1 Deterministic verifiers
当真相足够清晰时，使用确定性检查。

例如：
- required citations 存在
- trace refs 可解析
- audience visibility 合法
- stale guidance 冲突时选择 fresh evidence
- unsupported request 返回 fallback、restricted 或 escalate，而不是暴露直接答案
- approval 与 publish-policy 结果符合既有 governance 路径

### 6.2 CYG-117 固定的 production-shaped corpus
`production_eval_cases()` 返回十个按稳定 `case_id` 排序的 case；以下五个 family 各有且仅有两个 case。

| Family identifier | Fixture 范围 |
|---|---|
| `plan_tier_refund` | 按 plan tier 区分的退款政策 |
| `product_version_known_issue` | 按 product version 区分的 known issue |
| `region_feature_availability` | 区域特定的 feature availability |
| `freshness_conflict` | stale guidance 与 fresh evidence 的冲突 |
| `ticket_cluster_draft` | 支持 unpublished troubleshooting draft 的 ticket-cluster evidence 及其 policy expectations |

corpus 包含正向与负向 audience boundary、supported 与 unsupported query、fresh/stale 冲突、unpublished troubleshooting draft，以及 publish-policy expectations。“Production-shaped”表示 fixture 使用 Cygnus domain object 与 evidence contract；不表示它读取生产数据或调用 provider。

### 6.3 CYG-117 gate 之外的方法
当 deterministic truth 不足时，judge-assisted check 仍可能适用于 answer clarity 或 troubleshooting usefulness 等维度。但它不属于 CYG-117：该 gate 不调用 evaluator model，也不产生 judge-model score。

以后若增加 judge-assisted evaluation，应基于 retrieved evidence 与 trace，而不是只看原始输出文本。

## 7. CYG-117 确定性领域 eval gate

### 7.1 命令与 report contract
在仓库根目录运行：

```bash
uv run python scripts/domain_eval_gate.py
```

stdout 是 `EvalReport.to_dict()` 的稳定、排序后 JSON 序列化结果：包括 suite 状态、case/check 汇总，以及按 `case_id` 排序的 case result；每个 result 包含适用的 check 与失败细节。`--quiet` 会抑制 stdout，但不改变状态契约。

仅当 `report.passed` 为 true，即所有 case 和所有适用 check 都通过时，命令才退出 `0`。任一 case 或 check 失败时退出 `1`。CI 应使用该进程状态作为 merge-blocking signal，而不是解析说明文字。

### 7.2 Merge-blocking checks
CYG-117 没有容忍区间或 judge-model threshold。所有适用的确定性 check 都必须通过：
- `object_retrieval`
- `audience_restriction`
- `trace_resolution`
- `citation_grounding`
- `freshness_preference`
- `unsupported_escalation`
- `approval_required`
- `publish_policy`

预期 object/evidence ref 是必须出现的子集；forbidden object ref 不得出现在 answer 或 alternatives 中。supported answer 缺少要求的 trace/evidence ID 时，trace/citation check 失败。unsupported case 必须返回 fallback、escalation 或 restricted truth，且不能暴露直接答案。

### 7.3 Runtime 与 truth boundaries
- retrieval 经过既有 `GovernedSessionBridge`；publish-policy expectation 经过既有 `GovernedPublishTools.validate_publish_policy`。gate 不会重新定义 audience、lifecycle、freshness、escalation、approval 或 publish rule。
- fixture 直接构造 domain object 与 evidence。它们不导入 `sample_*`、不使用替代性的 fallback fixture、不读取数据库，也不调用 live network/provider。预期的 fallback/restricted/escalation disposition 是可观察结果，不是 fixture source fallback。
- session memory 不是 retrieval 或 policy truth。
- judge model 不属于该 gate。
- report 只提供确定性回归证据。CYG-119 现已提供 durable route-outcome truth，因此可以在该 gate 之外增加 worker-outcome instrumentation；但 CYG-117 的 report 本身仍不执行或证明 feedback-route worker 执行、在线 business KPI instrumentation 或 business-impact evidence。

## 8. 该 gate 之外的 Business-layer metrics
以下指标仍是独立在线层的推荐业务度量：
- human rewrite rate
- suggestion acceptance rate
- unsupported answer rate
- wrong-audience rate
- freshness SLA
- ticket-cluster to draft conversion rate
- review-to-publish cycle time

CYG-117 既不执行 feedback routing，也不测量这些 KPI。durable feedback-route outcome truth 现已存在（CYG-119），允许在独立在线层做未来的 worker-outcome instrumentation；但 domain report 通过仍不能被表述为 route 执行或 business impact 的证据。

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

## 11. 推荐的后续评估层
1. 从观察到的失败中扩充 deterministic case，同时不弱化固定 gate contract
2. 在存在可观察契约时，增加更广的 drafting fixture
3. CYG-119 已提供 durable route-outcome truth，可为 online support KPI 与 feedback-route worker outcome 做 instrumentation，但必须保留在 CYG-117 gate 之外
4. 仅对 deterministic check 无法证明的质量维度考虑 judge-assisted layer

## 12. 当前结论
CYG-117 gate 把确定性的 governance correctness 和领域专用离线 fixture 变成 merge-blocking check。它通过既有 governed retrieval 与 publish-policy path 评估 Cygnus domain control plane；不会把 Cygnus 变成另一个 agent loop，也不会把真相移入 Nanobot session memory。

generic agent benchmark、judge-model quality score、durable feedback routing、feedback-route worker 执行与在线 business impact 均不属于该 gate，也不能由该 report 证明；route outcome 现已在 CYG-119 下持久化，worker-outcome instrumentation 可以放在 gate 之外。

## 13. 参考资料
- AI Engineering from Scratch — Eval-Driven Agent Development  
  https://github.com/rohitg00/ai-engineering-from-scratch/tree/main/phases/14-agent-engineering/30-eval-driven-agent-development
- AI Engineering from Scratch — Eval Harness with Fixture Tasks  
  https://github.com/rohitg00/ai-engineering-from-scratch/tree/main/phases/19-capstone-projects/27-eval-harness-fixture-tasks
- AI Engineering from Scratch — Observability with OTel Traces  
  https://github.com/rohitg00/ai-engineering-from-scratch/tree/main/phases/19-capstone-projects/28-observability-otel-traces
- Anthropic — Building Effective AI Agents  
  https://www.anthropic.com/engineering/building-effective-agents
