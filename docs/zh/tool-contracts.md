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
  "expected_version": 1,
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
  "expected_version": 2,
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

### 当前 durable 并发行为
`propose_knowledge_object` 现在会持久化真实的 `WikiPageDraft`，初始状态为 `draft`，并返回 `draft_version`。`update_draft_object` 与 `request_review` 都必须携带当前整数 `expected_version`；过期写入返回 `conflict` / `stale_draft`。成功的 review request 会经由 append-only ledger 将 durable draft 推进到 `in_review`，且只会重放完全相同的请求。

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

### 当前持久化输入
```json
{
  "draft_id": "string",
  "approval_ref": "string",
  "command_id": "string",
  "action_key": "publish|republish|restrict_publish|hold_external|republish_internal_only",
  "target_channels": ["internal_copilot", "internal_mcp"],
  "expected_version": 7
}
```

`expected_version` 是对象级乐观并发保护；publish 会在锁定后的当前 WikiPage 上再次校验它。同一 `command_id` 的已提交 replay 仍优先返回原 publication。

### 权限规则
- `validate_publish_policy` 是请求级只读检查；调用者只能看到权限作用域内的 draft/object 结果。
- `publish_knowledge_object` 仅允许 admin 执行，并且必须提供真实 approval ledger event。
- external publish 与 policy/regulated object 仍遵守更严格的 audience binding 与审批规则；工具不得自行放宽。

### 输出重点
- `persisted:true`、`rehearsal:false`
- publication record id、ledger event id、approval ref、command id
- published object/version 与 effective bindings
- 每个目标 surface 的显式 propagation 状态

### 当前持久化边界
- 只有已审批、已物化为 typed support object、且全部 evidence source 为 `ready` 的 `WikiPageDraft` 才能进入 durable publish。
- `command_id` 是幂等键；同一请求重放返回原 publication，复用到不同 payload 会被拒绝。
- durable transaction 同时写入 append-only governance event、immutable publication record 与每个目标 surface 的 propagation row。
- propagation 初始状态必须为 `pending`；只有显式、带 `expected_version` 的后续更新才能写入 `synced`、`failed` 或 `manual_action_required`。
- 仅提供 `object_ref` 的 fixture-backed 调用仍是演练，必须返回 `persisted:false`、`rehearsal:true`，不得被表述为生产发布。
- 当前 durable write/read HTTP surface 仍为 admin-gated；更宽的 scoped write permission 不在此切片中推导。

## 8.3 `list_drift_alerts`
### 用途
读取当前 durable release / incident drift 告警，不能把空结果或覆盖不完整误写成“无风险”。

### 风险级别
`R0`

### 输入
```json
{
  "filters": {
    "object_type": "optional-supported-knowledge-object-type",
    "severity": "medium|high|urgent",
    "channel": "optional-nonblank-string"
  },
  "limit": 20
}
```

`filters` 只接受上面三个可选 key。每个提供的值都必须是非空字符串；未知 key、非法 object type 或 severity、boolean、非 object，以及不在整数 `1..50` 内的 limit 都返回结构化 `invalid` envelope。

### 输出重点
- `status`、`summary`、`warnings`、`errors`，以及规范化后的 `data.filters`、实际 `data.limit`、`data.observation` 与 `data.alerts`
- 每条 alert 包含 durable signal/object ref 与 type、title、由 compiled proposal urgency 得到的 `severity`、reason、summary、affected audience filter 与 surface、已有 suggested action、freshness、`observed_at` 和 `trace_ref=governance-signal:{signal_ref}`
- alert 保持 durable `observed_at DESC, signal_ref` 顺序；filter 不重排，`limit` 只在 filter 之后应用

### 作用域与 coverage 边界
- Runtime MCP 先把 bearer identity 解析为当前 `Employee`，再在同一请求 DB session 内，通过既有 SQL scope 与 order 读取 active release/incident `GovernanceSignal`。
- inline audience filter 是 durable truth。binding-backed row 只批量解析 active 且权限内可见的 binding；binding 必须同时匹配 signal 的 `page_id` 和 `object_ref`。未解析或不匹配 row 必须省略，并以包含 `audience_binding_resolution` 的 `partial` observation 返回，绝不能泄露 alert。
- 完整 scoped query 即使无匹配 row 也返回 `ready` 和 `observed_count:0`。`unavailable` 只允许来自显式 no-coverage provider result。provider、DB 或 serialization exception 必须传播，不能变成空 success 或 unavailable 响应。

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

## 8.5 Governance audit read surface
### 用途
从 append-only `GovernanceLedgerEvent` 读取 review、approval、publish 与 recovery 的持久化状态迁移，供人类治理工作台与受控客户端追踪一次变更。

### 风险级别
`R0`

### 当前 HTTP surface
- `GET /api/governance/audit`
- `GET /api/governance/audit/{event_id}`
- list 可按 `phase`、`event_type`、`draft_id`、`page_id`、`actor_id` 过滤，并使用 `page` / `page_size` 分页；`page_size` 上限为 `100`。
- 当前切片是受认证的 HTTP read surface，不会自动扩张 runtime MCP 的四个已批准 R0 retrieval tools。

### 输出重点
- `event_id` 与稳定的 `trace_ref=governance-event:{event_id}`
- `phase`（`review|approval|publish|recovery`）与原始 ledger `event_type`
- `from_state` / `to_state`、actor、draft/page/object 引用、作用域、reason 与时间戳
- 只返回按 event type allowlist 的 `details`；不得透传完整 ledger payload、请求指纹或内部执行结果
- list 返回 `total`、分页信息与 `SurfaceObservation`

### 权限与真相边界
- 必须先在 SQL 内按当前用户的 Wiki read scope 过滤，再做投影：admin / `wiki:read:all` 可读全部，`wiki:read:own_dept` 只读 global 与所属 department。
- 尚未物化 page 的 create draft 使用 `suggested_metadata.scope_type/scope_id` 做同样的作用域判断；没有 Wiki read 权限时返回空集合。
- 单条记录不存在或越权时统一返回 `404`，不得泄露隐藏 ID 是否存在。
- 数据只能来自 durable governance ledger，不得回退到 runtime `AuditLog`、`sample_*` fixture 或 session memory。
- audit item 与 list 的 `persisted:true` / `rehearsal:false` 只证明 ledger 事件本身已持久化，不代表对应知识对象已发布或下游 propagation 已完成。
- 作用域内无匹配事件时 observation 仍为 `ready`、`observed_count:0`；这表示真实查询为空，不是 `unavailable`。
## 8.6 Durable recipient notification inbox
### 用途
读取治理生命周期产生的 in-app notification，并在当前收件人作用域内推进未读 → 已读状态。

### 当前 HTTP surface
- `GET /api/notifications?lifecycle_state=unread|read`：分页读取当前用户的 durable records。
- `GET /api/notifications/unread-count`：读取当前用户的未读数量。
- `POST /api/notifications/{notification_id}/read`：幂等地将当前用户拥有的记录推进为 `read`。
- `POST /api/notifications/read-all`：只推进当前用户的未读记录。

### 真相与生命周期
- `Notification` 表由 Alembic migration `20260809_01` 管理；local `create_all` 只能作为兼容已存在 schema 的开发辅助。
- `read_at IS NULL` 投影为 `lifecycle_state=unread`，非空投影为 `read`；当前切片没有隐式 dismiss 或恢复未读状态。
- 每条响应包含 `trace_ref=notification:{id}` 与 `persisted:true`；这只证明 notification record 已落库，不代表外部 email/webhook 已送达。
- 外部 fan-out 必须在响应事务提交后，以新 session 重新读取仍存在的 notification IDs；回滚记录不得被发送。
- 所有 list / count / transition SQL 都包含 `recipient_id=current_user.id`；缺失记录与他人记录统一 `404`，不泄露跨用户 ID。
- 这是 runtime HTTP inbox，不会扩张 Nanobot 当前四个 R0 governed retrieval tools。



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
本节对账 `cygnus/integrations/nanobot_tools.py`、`cygnus/integrations/governed_draft_review_tools.py`、`cygnus/integrations/governed_publish_tools.py` 与 `cygnus/integrations/governed_drift_tools.py`，明确区分：
- 上文的**目标 contract**
- 下文当前可调用的 **durable interface**
- 仍有意保持不可用的治理语义

### 13.1 当前真正已兑现的能力
- **Group A — Retrieval（4/4）**：`search_knowledge_objects` / `read_knowledge_object` / `search_support_evidence` / `get_source_trace` 已接入 substrate-backed、请求级权限过滤的检索面。
- **Group B — Draft/Review（4/4）**：`propose_knowledge_object` / `update_draft_object` / `request_review` / `read_review_feedback` 使用 durable `WikiPageDraft` 生命周期、review queue、source/evidence metadata、ledger event、notification path 与已作用域化的反馈真相。
- **Group C — Governance（已暴露 3/4）**：`validate_publish_policy` 与 `publish_knowledge_object` 使用 durable draft、approval、audience-binding 与 publication 服务；`list_drift_alerts` 读取权限内 durable release/incident signal 真相并返回显式 observation coverage。只有 `record_feedback_signal` 仍有意不暴露。

### 13.2 仍有意不暴露的目标接口
- `record_feedback_signal`（Group C，R1）

它仍保持不可用，因为当前 session seam 没有对应的 governed adapter；已有 fixture 或 observation surface 不得被表述为 session-domain tool truth。

### 13.3 已兑现的 durable draft/review seam
- `propose_knowledge_object` 会创建 typed、create-kind 的 `WikiPageDraft`，持久化在 `draft` 状态，仅记录 `proposal_created`，并保存 proposed object type、audience context、source refs、evidence refs 与 source IDs，供后续 materialization 使用。
- `update_draft_object` 按 author/admin 作用域和 version 校验执行，绝不 publish；`needs_revision` 之后的修改会回到 durable `draft`，递增 draft content version，快照保存上一轮，并追加 `draft_updated`。
- `request_review` 按 author/admin 作用域和 version 校验执行，经由 `review_requested` 推进 `draft -> in_review`，并在 `(draft_id, draft_version, revision_round)` 上写入唯一 durable pre-review outbox intent；请求 middleware 只能加速派发，worker startup/cron recovery 会清扫已提交 intent，deterministic ARQ job ID 使重放幂等，worker 会拒绝缺少两个 revision 字段的 job，stale、config-disabled 与 retry-exhausted 结果均保留显式 terminal state。相同 draft revision 只重放完全相同的 ledger request。
- `read_review_feedback` 在投影前先以 SQL 对 draft 做作用域过滤，再仅向 author、具备资格的 reviewer 或 administrator 暴露 review state、durable feedback、blocking issues、approval ref 与 review-event history。隐藏与缺失的 draft/source IDs 都返回不含资源细节的 `not_found`。

### 13.4 已兑现的 durable publish seam
- `validate_publish_policy` 是请求级只读 adapter：重新加载当前 draft、typed object、approval ledger、ready sources、active audience bindings 与可选 audience/version 条件；越权对象统一隐藏为结构化 `not_found`。
- `publish_knowledge_object` 只构造 `DurablePublishCommand` 并调用 `cygnus/publish/durable.py`；admin、approval、source readiness、binding、锁、幂等、ledger、publication 与 propagation 真相仍由既有治理内核负责。
- 成功与 replay 都保留 `persisted:true`、`rehearsal:false`、publication/ledger/approval/command IDs 和 propagation records；传播成功不会从 publish 成功推导，初始状态仍为 `pending`。
- `expected_version` 在 adapter 与锁定后的 durable core 双重校验，避免 stale write；`command_id` 重放返回原 publication，payload 改变则返回 conflict。

### 13.4.1 已兑现的 durable drift-alert seam
- `list_drift_alerts` 是基于 active durable release/incident `GovernanceSignal` 真相的请求级 R0 adapter。它保留 SQL scope provider 顺序，只校验 `object_type` / `severity` / `channel` filter 以及范围 `1..50` 的整数 `limit`，并在过滤后才应用 limit。
- inline audience 是直接 durable truth。binding-backed row 在一次 batch 中解析 active 且可见的 binding，并且必须匹配持久化的 `page_id` 与 `object_ref`；未解析 row 以显式 `partial` `audience_binding_resolution` coverage 省略，不得泄露或改写成健康空结果。
- 完整空查询仍为 `ready`；`unavailable` 只能来自显式 no-coverage provider state。provider failure 必须传播，不得变成空 success 或 unavailable envelope。

### 13.5 边界提醒
该 seam 不会创建第二套 session loop 或 memory store。Nanobot 仍拥有 session continuity 与 general-purpose loop；Cygnus 拥有 typed draft versions、review state、permission checks、audit events、source/evidence traceability、approval truth 与 publication decisions。

### 13.6 已落地的 governed observation 边界（CYG-97、CYG-101～104、CYG-108、CYG-114）
`/api/command-center`、`/api/review-intake`、`/api/drift` 与 `/api/source-blindness` 现在都从请求级、权限已过滤的 `GovernanceReadSnapshot` 读取；这些 runtime path 不得隐式调用 `sample_*` fixture。

- 每个治理 risk surface 返回 `observation`：`ready` 表示覆盖完整，`partial` 表示同时列出已覆盖和缺失 detector，`unavailable` 表示 detector 尚未接入而不是“没有风险”。`reason` 和 signal 均为 machine code，由客户端 i18n 展示。
- 没有完整 proposal bundle 时，审阅队列、drift 与 source-blindness contexts 必须为空且没有治理命令；不得从普通 `WikiPageDraft` 推导 owner、audience、surface 或风险。
- `Source.status="error"` 仍只产生来源失败事实，但 CYG-108 provider 会在同一请求权限作用域内沿可见 `WikiPage.source_ids`、active audience bindings、每对象最新 durable publication 与 propagation 投影影响：`impact_state="mapped"` 表示至少存在一条可见 Wiki 关联，`unmapped` 表示当前作用域内没有已映射的治理 Wiki 影响，并不代表没有业务影响。`audience_impacts` 与 `propagation_impacts` 只能来自这些持久化记录；不得从原始 source row 推导 owner、risk rank 或执行命令。
- `/api/recovery/overview`、`/api/recovery/window/{command_id}` 与 `/api/recovery/downstream-reality-check/{command_id}` 读取权限内的持久化 publication / propagation 真相并返回 `persisted: true, rehearsal: false`；这些 read surface 不会回退到 rehearsal fixture。

CYG-101～104 与 CYG-108 已把工单/改写压力、发布/事故 drift、受众冲突、审阅分配和 source impact 接入持久化或持久化派生 provider。只有 detector 完整执行且没有未解析关系时才可返回 `ready`；例如未解析 audience binding 仍必须返回 `partial`，provider 异常必须作为 `5xx` 暴露，不能用空数组或绿色 UI 冒充健康状态。

### 13.7 已落地的 governed session seam（CYG-92～96）
Nanobot 现在可以通过 `POST /api/session-bridge/query` 把 `request_ref`、可选 `session_ref`、support query、`audience_context` 与可选的前一轮 `governance_context` 交给 Cygnus。Cygnus 在请求级权限范围内重新装载 substrate-backed knowledge snapshot，并返回统一 envelope：`answer`、`source_trace`、`tool_trace`、`governance`、`continuity` 与下一轮可携带的 `governance_context`。

- `GET /api/session-bridge/capabilities` 与 Runtime MCP 消费同一份 shared adapter-definition contract，并将十一个 governed tools 标为 ready：四个 R0 retrieval tools、R0 `list_drift_alerts`、R1 durable draft/review writes、已作用域化的 R0 `read_review_feedback`、请求级 `validate_publish_policy`，以及 administrator/approval-gated 的 `publish_knowledge_object`。只有 `record_feedback_signal` 仍为 `not_exposed`。
- Runtime MCP 为 `list_drift_alerts` 与 feedback 使用 authenticated visibility gate，为三个 R1 draft/review writes 使用 contributor visibility gate，并为 publication 使用 administrator gate。Drift alert 会在请求 DB session 内重新读取当前 employee-scoped durable truth，绝不回退到 fixture、chat history 或未作用域化的全局 index；每个 state-changing adapter 都会在服务端重新检查 identity、作用域内 draft/source visibility、author/reviewer authority 与 optimistic version。
- audience mismatch、pending review、stale/unknown freshness、source blindness 与 no-match 都返回结构化治理状态；分别收敛为 `restricted`、`escalate` 或 `fallback`，不能生成看似可直接外发的答案。
- continuity 每轮都重新查询 Cygnus truth。受众、对象、版本、trace 或 freshness 改变时前一轮 context 必须失效；即使没有变化也只能标记为 revalidated，且始终返回 `session_memory_used_as_truth:false`。

该接缝没有在 Cygnus 中增加第二套 session loop 或 memory store；Nanobot 仍拥有会话，Cygnus 只拥有知识、检索与治理裁决。
