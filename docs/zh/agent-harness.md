# Support Brain for SaaS — Agent Harness

## 1. 目的
本文件定义：Cygnus 应该如何借用 **agent harness** 的方法，而不把自己变成一个 generic agent framework。

它主要回答：
- 这个项目里的 harness 到底是什么
- **Nanobot** 和 **Cygnus** 各自负责什么
- 哪些 budget、gate、pause/resume 点最重要
- 哪些部分可以模型驱动，哪些必须保持确定性

## 2. 核心判断
Cygnus 应该借用的是 **harness 的纪律性**，不是 **通用 agent shell 的产品形态**。

真正有价值的 harness 思路是：
- **harness** 是持久的控制契约
- **模型** 是提议引擎，不是业务真相来源

在 Cygnus 里，这个判断落成：
- **Nanobot harness** = 通用会话 harness
- **Cygnus harness** = 支持知识领域控制 harness
- **Cygnus workflow orchestration** = Cygnus 内部选定治理流的 workflow engine

这也保持了前面的产品边界：
- Nanobot 负责会话如何运行
- Cygnus 负责支持知识如何治理、审核、发布、追溯

## 3. 分层 harness 模型

| 层 | 角色 | 负责内容 | 不应负责 |
|---|---|---|---|
| Nanobot session harness | 通用会话运行时 | 多轮 loop、workspace、session memory、面向用户的 planning、通用 tool proposal | approval truth、audience policy truth、publish truth |
| Cygnus domain harness | 支持知识控制面 | typed domain tools、schema validation、policy check、evidence sufficiency check、audit trail、publish guardrails | 开放式聊天 runtime、第二套 session memory、第二套通用 planner |
| Cygnus workflow orchestration | workflow 进展引擎 | checkpointed business-state transition、branch/retry/rollback、human approval pause | generic copilot runtime、自由游走的 agent loop |

## 4. 应该从参考 harness 里借什么
AI Engineering from Scratch 的 harness 材料，对 Cygnus 最有价值的是这些部分：

1. **先定义 loop contract**
   - 在写工具前先定义状态、迁移、pause 点、budget

2. **typed tool registry**
   - tools 有名称、schema、风险等级

3. **pull point 代替 crash**
   - approval、evidence 缺失、tool/result 依赖都应该 yield，而不是直接崩

4. **verification gates**
   - 用确定性层判断 proposed call 或 transition 是否允许

5. **event stream + observability**
   - traces、refusal、retry、pause 都是一等产物

这些思路之所以适合 Cygnus，是因为它们强化的是控制，而不是盲目自治。

## 5. Cygnus domain harness 的最小契约
Cygnus 应该暴露一个小而 typed 的 domain task envelope。

### 5.1 建议任务输入
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

### 5.2 输出契约
输出建议继续与 `tool-contracts.md` 对齐：

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
在 Cygnus 里，pull point 应该是**结构化 yield**，不是 crash。

推荐 pull points：
- `awaiting_tool_result`
- `approval_required`
- `evidence_insufficient`
- `policy_conflict`
- `budget_exhausted`

关键边界细节：
- Nanobot 可以负责把 pause 呈现给用户
- 但 pause 背后的 domain state 必须由 Cygnus 持久拥有

## 7. Hook topics
外部 harness 课程强调 planning、tool use、pause、complete 周围的 lifecycle hooks。Cygnus 应该借这个思路，但 hook surface 要保持 domain-native。

### 7.1 推荐第一版 hooks
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

### 7.2 为什么不要一开始暴露太多 hooks
hooks 太多会让 harness 在产品契约未稳定前，过早变成一个 plugin system。

Cygnus 应先稳定：
- tool shape
- policy gates
- approval flow
- traceability fields

然后再生长更多 extension points。

## 8. Budget 模型
参考 harness 材料强调显式 budget。Cygnus 应保留这个思路，但按层拆分。

### 8.1 Nanobot session budgets
- max turns
- max tool calls
- max wall-clock seconds

### 8.2 Cygnus domain budgets
- 每个任务最多 evidence fetch 次数
- 每个 workflow 最多 draft revision 次数
- review retry 上限
- publish attempt 上限
- unresolved policy escalation 上限

### 8.3 一个重要边界细节
在 Cygnus 里，token budget 不是唯一关键 budget。
更产品原生的 budget 是：
- evidence collection budget
- review retry budget
- governance retry budget

## 9. Verification gates
Cygnus 应借鉴 gate chain，但 gate 必须是支持领域 gate，而不是 generic shell gate。

### 9.1 推荐 gate chain
1. **Tool whitelist gate**  
   只允许跑已授权的 typed domain tools。

2. **Schema validation gate**  
   tool 参数必须满足 schema。

3. **Scope gate**  
   actor 与 workspace scope 必须允许这个动作。

4. **Audience gate**  
   请求的输出必须满足 audience visibility 规则。

5. **Freshness gate**  
   stale evidence 或 stale object version 应能阻止 publish 或高置信输出。

6. **Approval gate**  
   高风险 transition 必须 pause 等审批，而不是自动 commit。

7. **Commit gate**  
   external publish 不允许从 draft state 直接越过 review 与 policy check。

## 10. Observation ledger 与 traces
参考 harness 材料会谈 observation budget 和 event streams。在 Cygnus 里，ledger 必须记录 domain meaning，而不只是原始 tool output。

### 10.1 Session-side ledger
通常由 Nanobot 维护：
- turn count
- tool count
- wall-clock elapsed
- session transcript refs

### 10.2 Domain-side ledger
必须由 Cygnus 维护：
- evidence refs used
- object refs touched
- draft revisions
- approval ids
- publish ids
- policy decisions
- refusal reasons

这也是 Cygnus 能把 auditability 做成短路径可见的关键。

## 11. 推荐第一阶段实现切片
Cygnus 最先值得做的 harness 切片是：

1. typed tool registry
2. schema validation
3. gate chain
4. approval / policy conflict / evidence insufficiency 的 pull-point handling
5. event stream 与 trace ids

不要先做：
- multi-agent orchestration
- Cygnus 内部开放式 autonomous replanning
- 第二套 session memory

## 12. 反模式
应避免以下形态：

### 反模式 1 — Cygnus 变成第二个通用聊天 agent
这会直接把 Nanobot / Cygnus 边界打穿。

### 反模式 2 — tool validation 只存在于 prompt 里
如果 validation 只在自然语言指令里，那它不是真正的 control plane。

### 反模式 3 — publish guardrails 只在 Nanobot 里判断
approval truth 与 commit truth 必须在 Cygnus。

### 反模式 4 — 一个巨大的“agent tool”替代 domain tools
Cygnus 需要的是 typed domain verbs，而不是一个万能动作黑洞。

## 13. 当前结论
Cygnus 当然应该有 harness 思维。

但正确结构是：
- **Nanobot** 保留唯一的通用 session loop
- **Cygnus** 保留 domain harness
- **Cygnus workflow orchestration** 只在 Cygnus 内部编排选定治理流

这比“再加更多 agent loop”更强，也更稳。

## 14. 参考资料
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
