# Support Brain for SaaS — Tool Contracts（Nanobot ↔ Cygnus）

## 1. 目的
本文件定义 **Nanobot 作为会话层** 时，调用 **Cygnus 作为领域控制面** 的第一版**目标工具契约**。

它描述的是希望稳定下来的接口目标，不应被自动视为“当前代码已全部兑现”。

目标不是写 SDK 代码，而是先把以下事情定清楚：
- 哪些能力由 Nanobot 会话层消费
- 哪些能力必须由 Cygnus 域内 harness 执行
- 每个工具的输入、输出、风险级别、审批边界是什么
- 如何保证 RAG、审核、发布、traceability 不漂成 generic runtime 行为

## 2. 边界原则
### 2.1 所有高风险业务决策留在 Cygnus
Nanobot 可以：
- 发起检索
- 发起草稿生成
- 发起 review 请求
- 发起 policy validation
- 发起 publish 请求

但 Nanobot **不应直接**：
- 绕过 Cygnus 修改业务数据库
- 绕过 approval 直接 external publish
- 自己实现 audience policy 判定
- 自己实现 source-of-truth traceability

### 2.2 工具返回的是结构化观察，不是自由文本副作用
每个 tool call 都必须返回结构化结果，哪怕被拒绝、超时、需审批、数据不足。

### 2.3 Draft / Commit 分离
- `propose_knowledge_object` / `update_draft_object` / `request_review` 属于 draft side
- `publish_knowledge_object` 属于 commit side

### 2.4 RAG 归属于 Cygnus
RAG 的 object retrieval、evidence retrieval、audience filtering、traceability 都在 Cygnus 中实现。
Nanobot 只消费结果，不拥有检索真相。

## 3. 通用上下文字段
以下字段可被多个工具复用。

### 3.1 `audience_context`
```json
{
  "brand": "optional-string",
  "product_line": "optional-string",
  "plan_tier": "optional-string",
  "region": "optional-string",
  "language": "optional-string",
  "product_version": "optional-string",
  "visibility": "internal|external"
}
```

### 3.2 `source_ref`
```json
{
  "source_id": "string",
  "source_type": "help_center|ticket|chat|release_note|incident|wiki|other",
  "locator": "string"
}
```

### 3.3 `evidence_ref`
```json
{
  "evidence_id": "string",
  "source_id": "string",
  "excerpt_ref": "string",
  "confidence": 0.0,
  "freshness": "fresh|stale|unknown"
}
```

## 4. 通用返回结构
所有工具建议共享以下顶层返回形状：

```json
{
  "status": "success|error|denied|approval_required|not_found|conflict",
  "summary": "short human-readable summary",
  "data": {},
  "trace_ref": "optional-trace-or-audit-id",
  "warnings": [],
  "errors": []
}
```

### 4.1 常见错误码
- `invalid_arguments`
- `scope_denied`
- `approval_required`
- `policy_violation`
- `not_found`
- `stale_draft`
- `conflict_detected`
- `trace_unavailable`
- `result_too_large`
- `upstream_timeout`

## 5. 风险分级
### R0 — Read only
纯读取，无副作用。

### R1 — Draft write
会修改 draft / signal / queue，但不直接 external commit。

### R2 — Governance check
会影响 review / policy / publish readiness，但不真正发布。

### R3 — Commit / publish
会触发真实业务状态变化或外部可见变化。

## 6. Tool Group A — Retrieval

## 6.1 `search_knowledge_objects`
### 用途
按 query + audience context 搜索已存在知识对象。

### 何时使用
- 客服 copilot 需要找可直接消费的对象
- graph 需要先判断是否已有类似对象
- reviewer 需要比较候选对象

### 不要用于
- 直接读原始 evidence
- 绕过 audience gating 做通用搜索

### 风险级别
`R0`

### 输入
```json
{
  "query": "string",
  "audience_context": {},
  "object_types": ["answer_card", "troubleshooting_flow", "policy_rule", "known_issue_page", "escalation_route"],
  "limit": 10,
  "include_unpublished": false
}
```

### 输出
```json
{
  "status": "success",
  "summary": "3 matching knowledge objects found",
  "data": {
    "results": [
      {
        "object_id": "ko_123",
        "slug": "billing-refund-policy",
        "object_type": "policy_rule",
        "title": "Billing Refund Policy",
        "audience_match": "exact|partial",
        "freshness": "fresh|stale|unknown",
        "publication_status": "published|draft|archived",
        "snippet": "short summary",
        "trace_ref": "trace_abc"
      }
    ]
  }
}
```

## 6.2 `read_knowledge_object`
### 用途
读取单个知识对象详情。

### 风险级别
`R0`

### 输入
```json
{
  "id_or_slug": "string",
  "include_variants": true,
  "include_trace": true
}
```

### 输出重点
- canonical content
- audience variants
- status / version
- source trace summary
- allowed channels

## 6.3 `search_support_evidence`
### 用途
搜索原始/归一化证据，而不是最终知识对象。

### 风险级别
`R0`

### 输入
```json
{
  "query": "string",
  "filters": {
    "source_type": "optional-string",
    "product_line": "optional-string",
    "region": "optional-string",
    "product_version": "optional-string"
  },
  "limit": 10
}
```

### 输出重点
- evidence excerpt refs
- source refs
- freshness markers
- confidence signals

## 6.4 `get_source_trace`
### 用途
返回某知识对象的证据追溯链。

### 风险级别
`R0`

### 输入
```json
{
  "object_id": "string"
}
```

### 输出重点
```json
{
  "status": "success",
  "data": {
    "object_id": "ko_123",
    "version": 4,
    "evidence_refs": [],
    "publication_records": [],
    "review_history_summary": []
  }
}
```

## 7. Tool Group B — Draft / Review

## 7.1 `propose_knowledge_object`
### 用途
从 evidence / ticket cluster / operator input 生成知识对象草稿。

### 风险级别
`R1`

### 输入
```json
{
  "proposed_object_type": "answer_card|troubleshooting_flow|policy_rule|known_issue_page|escalation_route|auto",
  "title": "string",
  "input_summary": "string",
  "audience_context": {},
  "source_refs": [],
  "evidence_refs": [],
  "ticket_cluster_ref": "optional-string"
}
```

### 输出重点
- `draft_id`
- inferred object type
- draft completeness score
- missing evidence warnings
- next recommended step

## 7.2 `update_draft_object`
### 用途
更新草稿对象，而不触发正式发布。

### 风险级别
`R1`

### 输入
```json
{
  "draft_id": "string",
  "patch": {
    "title": "optional-string",
    "content": "optional-string",
    "audience_variants": [],
    "linked_evidence_refs": []
  }
}
```

### 输出重点
- updated draft version
- changed fields summary
- validation warnings

## 7.3 `request_review`
### 用途
把 draft 送入 review queue。

### 风险级别
`R1`

### 输入
```json
{
  "draft_id": "string",
  "review_type": "content|policy|compliance|publish_readiness",
  "notes": "optional-string"
}
```

### 输出重点
- review request id
- current queue state
- expected reviewer role

## 7.4 `read_review_feedback`
### 用途
读取草稿的 review 反馈。

### 风险级别
`R0`

### 输入
```json
{
  "draft_id": "string"
}
```

### 输出重点
- review status
- reviewer notes
- blocking issues
- approval state

## 8. Tool Group C — Governance

## 8.1 `validate_publish_policy`
### 用途
在真正 publish 前，检查 audience / visibility / policy 是否允许。

### 风险级别
`R2`

### 输入
```json
{
  "draft_id": "string",
  "target_channel": "internal_copilot|internal_mcp|external_help_center|future_customer_answer_engine",
  "audience_context": {}
}
```

### 输出重点
```json
{
  "status": "success|denied|approval_required",
  "data": {
    "allowed": true,
    "policy_checks": [
      {
        "name": "visibility_scope",
        "result": "pass|fail|approval_required",
        "reason": "string"
      }
    ]
  }
}
```

## 8.2 `publish_knowledge_object`
### 用途
将草稿发布到目标渠道。

### 风险级别
`R3`

### 输入
```json
{
  "draft_id": "string",
  "target_channel": "internal_copilot|internal_mcp|external_help_center|future_customer_answer_engine",
  "approval_ref": "optional-string"
}
```

### 权限规则
- internal-only 低风险发布：可按组织策略自动放行或轻审批
- external publish：默认 `approval_required`
- policy_rule / regulated topics：默认更严格审批

### 输出重点
- publication record id
- published object id / version
- effective visibility
- audit trace ref

## 8.3 `list_drift_alerts`
### 用途
读取 freshness / drift 告警。

### 风险级别
`R0`

### 输入
```json
{
  "filters": {
    "object_type": "optional-string",
    "severity": "optional-string",
    "channel": "optional-string"
  },
  "limit": 20
}
```

### 输出重点
- object refs
- drift reason
- affected audience
- suggested next action

## 8.4 `record_feedback_signal`
### 用途
回写消费反馈，让系统后续修正知识对象。

### 风险级别
`R1`

### 输入
```json
{
  "signal_type": "answer_accepted|human_rewrite|escalated|low_rating|unsupported_answer|stale_answer",
  "object_id": "optional-string",
  "draft_id": "optional-string",
  "audience_context": {},
  "notes": "optional-string",
  "source_context_ref": "optional-string"
}
```

### 输出重点
- signal id
- whether refresh/review was queued
- linked object/draft refs

## 9. 审批与权限矩阵（目标态建议，不等于当前全部已实现）
| Tool | Risk | 默认策略 |
|---|---:|---|
| `search_knowledge_objects` | R0 | 自动允许（作用域内） |
| `read_knowledge_object` | R0 | 自动允许（作用域内） |
| `search_support_evidence` | R0 | 自动允许（作用域内） |
| `get_source_trace` | R0 | 自动允许（作用域内） |
| `propose_knowledge_object` | R1 | 自动允许，写入 draft scope |
| `update_draft_object` | R1 | 自动允许，记录审计 |
| `request_review` | R1 | 自动允许 |
| `read_review_feedback` | R0 | 自动允许（作用域内） |
| `validate_publish_policy` | R2 | 自动允许 |
| `publish_knowledge_object` | R3 | internal 低风险可放行；external 默认审批 |
| `list_drift_alerts` | R0 | 自动允许 |
| `record_feedback_signal` | R1 | 自动允许，记录审计 |

## 10. 结果大小与时限建议
### 结果大小
- retrieval 类结果默认摘要化
- 大正文通过 `id_or_slug` / `trace_ref` 二次读取
- 不要把整篇大对象直接塞回会话上下文

### 超时建议
- retrieval: 5-10s
- draft/review queue write: 10-15s
- publish validation: 10s
- publish commit: 15-30s

## 11. 与内部工作流编排的关系
这些 tools 是 **Nanobot / session runtime** 与 **Cygnus / domain control plane** 的稳定接口。

内部工作流编排不应该替代这些工具；相反，Cygnus 后续如需治理流编排，也应围绕这些工具对应的业务阶段展开，例如：
- creation workflow 使用 `propose_knowledge_object` → `request_review` → `validate_publish_policy` → `publish_knowledge_object`
- freshness workflow 使用 `list_drift_alerts` → `search_support_evidence` → `update_draft_object` → `request_review`

## 12. 第一版成功标准
这套 contract 的成功，首先是**边界定义成功**，不是“所有写路径都已产品化完成”。

它成立的前提是：
- Nanobot 与 Cygnus 的边界稳定
- draft / review / publish 明确分离
- RAG 仍属于 Cygnus
- 高风险发布最终仍应由 Cygnus 域内规则控制
- 后续 workflow orchestration、eval、UI 都可以围绕这些 contract 继续长出来

## 13. 当前实现状态（与代码对账）
本节对账 `cygnus/integrations/nanobot_tools.py` 的当前实现，明确区分：
- **目标 contract**
- **当前可调用接口**
- **尚未兑现的治理语义**

不要把本文件前半部分的目标接口，误读成当前代码已经全部完成。

### 13.1 当前真正已兑现的能力
- **Group A — Retrieval（4/4）**：`search_knowledge_objects` / `read_knowledge_object` / `search_support_evidence` / `get_source_trace`，已接入真实索引（`object_index` / `evidence_index` / `source_trace`）；且自 CYG-97 起索引数据来自 substrate 真相——运行时必须通过 `configure_governed_knowledge_from_substrate(session)` 装载（wiki pages + ready sources 经 `cygnus/retrieval/substrate_provider.py` 投影），sample fixtures 仅存在于测试注入路径，无隐式回退。`/api/knowledge-graph` 与 `/api/traceability/{id}` 读同一份 DB-backed snapshot。这是当前最接近真实产品语义的一组接口。
- **Group B — Draft/Review（2/4）**：仅 `propose_knowledge_object`、`request_review` 可调用，但当前仍是**占位桩**（返回结构正确，但不落库、不入队），因此只兑现了“接口形状”，没有兑现“治理状态变更”。
- **Group C — Governance（3/4）**：`validate_publish_policy`、`publish_knowledge_object` 可调用，但当前仍是**占位桩**（审批 = 按 `target_channel` 字符串判定 internal/external）；`list_drift_alerts` 已接入真实 drift 治理面（其 bundle 数据仍默认 sample fixtures，待 CYG-97 review-bundle 平面切换）。

### 13.2 尚未兑现的目标接口
- `update_draft_object`（Group B，R1）
- `read_review_feedback`（Group B，R0）
- `record_feedback_signal`（Group C，R1）

这些名字已经进入目标 contract，但当前代码尚未提供对应实现。

### 13.3 重要缺口：治理内核与 tool contract 仍然脱节
Cygnus 域层已实现、但**尚未作为工具暴露**的能力：
- blast-radius 预览（`cygnus/publish/preview.py`）
- 发布治理动作（`cygnus/publish/actions.py`：`publish` / `restrict` / `split_variant` / `hold_external` / `republish_internal_only`）
- 传播状态（`cygnus/publish/propagation.py`：`synced` / `pending` / `failed` / `manual_action_required`）

当前 `publish_knowledge_object` 写路径**未调用**上述治理内核。
这意味着：当前外部可调用 publish contract，并不等于已经走过 blast-radius / propagation / governance action 的真实治理链路。

### 13.4 边界提醒
§2.1 要求 approval truth 留在 Cygnus，但目前审批仅由 `target_channel` 字符串判定，**尚无真实审批记录存储**。在落地审批存储前，approval truth 还未被代码兑现。

因此当前更准确的描述不是“Cygnus 已完成审批治理”，而是：
- contract 已声明审批应属于 Cygnus
- 代码尚未完整兑现这一治理真相
