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
创建持久化草稿或信号，或显式请求受治理的队列迁移，但不产生外部可见提交。

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
将已认证的消费反馈记录为持久化事实，并为两种需要路由的 signal type 创建可被有界 feedback worker 认领并执行的持久化 route。CYG-118 将该路由冻结为 replay-safe 的 durable queued intent；CYG-119 在其上增加执行生命周期（`queued / running / completed / blocked / failed`）与有界 claim/recovery。`queued` 绝不表示 review 或 refresh 工作已完成；`completed` 只证明该 route 已把 durable outcome governance signal 物化进 governed review truth。

### 风险级别
`R1`

### 输入
```json
{
  "command_id": "string",
  "signal_type": "answer_accepted|human_rewrite|escalated|low_rating|unsupported_answer|stale_answer",
  "object_id": "optional-string",
  "draft_id": "optional-uuid",
  "audience_context": {
    "visibility": "internal|external"
  },
  "notes": "optional-string",
  "source_context_ref": "optional-string"
}
```
- `command_id` 必填、去除首尾空白后不得为空，长度最多 220 个字符。

### 输出与真相边界

- 可接受的 signal type 固定为 `answer_accepted`、`human_rewrite`、`escalated`、`low_rating`、`unsupported_answer` 与 `stale_answer`。
- `GovernanceFeedbackSignal.command_id` 全局唯一；每条 signal 保存基于规范化 payload 与已认证 actor 的 64 字符 `request_fingerprint`。即使 payload 相同，不同 command ID 仍代表不同的 feedback signal。
- 完成语法校验后，command binding 会先于 governed resource lookup 判定。`command_id`、规范化 payload 与已认证 actor 完全相同的 exact replay 返回已有 signal 及其 route（如有），不创建新的 signal、route 或 audit row；复用 `command_id` 但规范化 payload 或 actor 不同，则返回结构化 `conflict` 且不写入。只有尚未绑定的 command 才解析 object/draft ref，因此新 command 的隐藏或缺失引用仍返回 `not_found`，且不泄露资源。Replay 不是冻结的逐字节响应快照：它保留相同的 signal/route 身份，但投影 route 当前的 durable lifecycle，因此稍后的 exact replay 可以如实显示 `completed`、`blocked` 或 `failed`，且不产生重复真相。
- 新调用在同一个 caller-owned transaction 内暂存原始 `GovernanceFeedbackSignal`、适用时的一条 route，以及恰好一条 runtime mutation `AuditLog`。feedback persistence owner 只 flush、不 commit；caller 必须全部提交或全部回滚。exact replay 不产生重复 audit。
- `GovernanceFeedbackRoute` 是唯一的 durable queue truth；它在 `(feedback_signal_id, route_kind)` 上唯一，`route_kind` 为 `review|refresh`，`lifecycle_state` 初始为 `queued`。映射已冻结：`low_rating` → queued `review`，`stale_answer` → queued `refresh`，其他所有可接受 type → 无 route 且为 `recorded_only`。ownership migration 会为 route table 建立前已存在的 durable feedback signal 按相同映射补写 route。
- Routed response 暴露 `route_id`、形如 `feedback-route:{uuid}` 的 `route_ref`、`route_kind`、跨生命周期的 `route_state`（`queued|running|completed|blocked|failed`），以及形如 `<route_kind>_<route_state>` 的 `routing_state`（`review_queued|review_running|review_completed|review_blocked|review_failed` 或对应的 `refresh_*`）；`review_queued` 与 `refresh_queued` 恰有一个为 `true` 只在 route state 为 `queued` 时成立，`running`/`completed`/`blocked`/`failed` 时两个 queue flag 都为 `false`。
- Non-routed response 暴露 `route_id:null`、`route_ref:null`、`route_kind:null`、`route_state:null`、`routing_state:"recorded_only"`、`review_queued:false` 与 `refresh_queued:false`。
- `actor_id` 及已解析的 `page_id` / `draft_id` 是 `RESTRICT` 外键；`object_id` 与 `source_context_ref` 是持久化上下文而非数据库外键，`source_context_ref` 不会解析为 `Source` row。
- `persisted:true`、`rehearsal:false`；`trace_ref` 只标识 durable feedback row，route fields 标识 durable route row；两者都不表示下游工作已完成。
- 隐藏、缺失或有歧义的 object/draft ref 统一返回结构化 `not_found`；冲突的 object/draft ref 返回结构化 `conflict`，不泄露资源且不写入记录。

#### Route 执行生命周期（CYG-119）
- 上面的 replay-safe queue-intent seam 由 CYG-118 冻结；CYG-119 在其上增加有界执行。`GovernanceFeedbackRoute.lifecycle_state` 沿 `queued / running / completed / blocked / failed` 推进：worker 以 60 秒 lease 认领到期 route（最多 `limit=25` 条），可重试失败把 route 退回 `queued`（最多 3 次尝试、30 秒基础重试），目标对象缺失、仅 draft 或不符合 governed review 条件的 route 以 `blocked` 结束，且不猜测目标。
- durable route row 携带 `attempt_count`、`next_attempt_at`、`lease_token`、`lease_expires_at`、`outcome_signal_id`、`terminal_reason`、`last_error` 与 `completed_at`。每次 mutation 只 flush；caller 拥有 commit。worker wrapper 先提交 claim，再以独立 transaction 提交每次 execution 或 failure。
- completed route 物化一条 durable outcome `GovernanceSignal`，其 signal 身份恰好为 `route_ref=feedback-route:<route UUID>`，落在 `feedback` 与 `review_queue` surface；durable route row 存储 `outcome_signal_id`，response 从该 ID 投影 `outcome_signal_ref=governance-signal:<signal UUID>`（response projection，不是存储列）。`low_rating` 物化为 review pressure（`ticket_pressure`、unknown freshness），`stale_answer` 物化为疑似 freshness/drift review（`drift`、stale freshness）。low_rating/stale_answer 的派生由 worker 独占：feedback 派生类型不能通过 admin write endpoint 创建，admin read endpoint 可以读取 worker 创建的 row。route 执行不会记录原始 `source_context` 或 `notes` payload。
- 执行绝不自动修改知识内容，也绝不发布。Route 完成只证明已物化进 governed review truth——不代表 reviewer 已行动、草稿已创建、已发布、下游已传播、KPI 已改善或已产生业务影响。

## 8.5 Governance audit read surface
### 用途
从 append-only `GovernanceLedgerEvent` 读取 review、approval、publish 与 recovery 的持久化状态迁移，供人类治理工作台与受控客户端追踪一次变更。

### 风险级别
`R0`

### 当前 HTTP surface
- `GET /api/governance/audit`
- `GET /api/governance/audit/{event_id}`
- list 可按 `phase`、`event_type`、`draft_id`、`page_id`、`actor_id` 过滤，并使用 `page` / `page_size` 分页；`page_size` 上限为 `100`。
- 当前已认证 HTTP read surface 与 shared 十二工具 Runtime MCP/session ready contract 相互独立，不会新增 tool definition。

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
- 当前 runtime HTTP inbox 与 shared 十二工具 Runtime MCP/session ready contract 相互独立，不会新增 tool definition。



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
本节对账 `cygnus/integrations/nanobot_tools.py`、`cygnus/integrations/governed_draft_review_tools.py`、`cygnus/integrations/governed_publish_tools.py`、`cygnus/integrations/governed_drift_tools.py` 与 `cygnus/integrations/governed_feedback_tools.py`，以及 CYG-119 的 route 执行模块 `cygnus/governance/feedback_execution.py`，明确区分：
- 上文的**目标 contract**
- 下文当前可调用的 **durable interface**
- CYG-118 已实现的 replay-safe、durable feedback-routing 边界，以及 CYG-119 已实现的有界 route 执行生命周期

### 13.1 当前真正已兑现的能力
- **Group A — Retrieval（4/4）**：`search_knowledge_objects` / `read_knowledge_object` / `search_support_evidence` / `get_source_trace` 使用 substrate-backed、请求级权限过滤的检索面。
- **Group B — Draft/Review（4/4）**：`propose_knowledge_object` / `update_draft_object` / `request_review` / `read_review_feedback` 使用 durable `WikiPageDraft` 生命周期、review queue、source/evidence metadata、ledger event、notification path 与作用域内 review feedback 真相。
- **Group C — Governance（4/4）**：`validate_publish_policy` 与 `publish_knowledge_object` 使用 durable draft、approval、audience-binding 与 publication 服务；`list_drift_alerts` 读取权限内 durable release/incident signal 真相并返回显式 observation coverage；`record_feedback_signal` 写入 replay-safe 的 durable consumption-feedback 真相与冻结的 `low_rating`/`stale_answer` route 映射，CYG-119 的有界 worker 会将其执行成 feedback/review-queue surface 上身份为 `feedback-route:<uuid>` 的 durable outcome governance signal，且绝不自动修改内容或发布。

### 13.2 已实现的 durable feedback-routing seam（CYG-118 scope）
以下 bullet 描述 CYG-118 的 queue-intent 切片：replay-safe signal 与冻结的 route 映射，当时还没有 worker 或 consumer 执行 route。CYG-119 的有界执行生命周期见 13.2.1。
- `record_feedback_signal` 是 authenticated、请求级 R1 adapter，后端使用独立 `GovernanceFeedbackSignal`，只接受六种固定 consumption-feedback type，不会复用 `GovernanceSignal` pressure fact 或 fixture observation。
- `GovernanceFeedbackSignal` 持有全局唯一的 `command_id` 与 64 字符 `request_fingerprint`。同一 `command_id`、规范化 payload 与已认证 actor 完全相同的 exact replay 返回已有 signal 与 route；复用 `command_id` 但规范化 payload 或已认证 actor 改变则返回不写入的 `conflict`，而新的 command ID 代表独立 feedback。
- caller-owned transaction 暂存原始 feedback row、适用时的 mapped route 与恰好一条 runtime mutation `AuditLog`；persistence owner 只 flush。exact replay 不产生重复 audit。object 与 draft ref 在投影前通过 SQL Wiki scope 解析；隐藏、缺失或有歧义的 ref 统一返回 `not_found`，不匹配 ref 返回不泄露资源且不写入的 `conflict`。
- `GovernanceFeedbackRoute` 是唯一的 durable queue truth，在 `(feedback_signal_id, route_kind)` 上唯一，kind 为 `review|refresh`，lifecycle 为 `queued`。冻结映射为 `low_rating` → `review`、`stale_answer` → `refresh`、其他所有可接受 type → `recorded_only`。routed result 暴露 queued route fields 且恰有一个 queue flag 为真；non-routed result 暴露 null route fields 且两个 flag 都为假。不引入 feedback worker 或 consumer，queued intent 绝不表示 review 或 refresh 已完成。

### 13.2.1 已实现的 durable feedback-route 执行（CYG-119）
- 核心执行模块是 `cygnus/governance/feedback_execution.py`，导出 `FeedbackRouteClaim`、`FeedbackRouteLeaseLost`、`claim_feedback_routes(session, *, now=None, limit=25)`、`execute_feedback_route(session, claim, *, now=None)` 与 `record_feedback_route_failure(session, claim, *, error, now=None)`。Exact command replay 保留相同的 signal/route 身份，并投影 route 当前的 durable lifecycle（稍后的 replay 可以如实返回 `completed`、`blocked` 或 `failed`），不产生重复的 signal、route 或 audit 真相。
- route state 为 `queued`、`running`、`completed`、`blocked` 与 `failed`。worker 以 60 秒 lease 认领最多 `limit=25` 条到期 route；lease 丢失时抛出 `FeedbackRouteLeaseLost` 而不是并发竞争。未被目标校验直接阻断的 worker 执行失败会在有界 backoff 下把 route 退回 `queued`，直到第三次尝试；第三次尝试仍失败时，route 以 `failed` 结束并记录 `terminal_reason` 与 `last_error`。目标对象缺失、仅 draft 或不符合 governed review 条件的 route 以 `blocked` 结束，不猜测目标。
- durable route row 携带 `attempt_count`、`next_attempt_at`、`lease_token`、`lease_expires_at`、`outcome_signal_id`、`terminal_reason`、`last_error` 与 `completed_at`。每次 mutation 只 flush；caller 拥有 commit；worker wrapper 先提交 claim，再以独立 transaction 提交每次 execution 或 failure。
- completed route 物化一条 durable outcome `GovernanceSignal`，其 signal 身份恰好为 `route_ref=feedback-route:<route UUID>`，落在 `feedback` 与 `review_queue` surface；durable route row 存储 `outcome_signal_id`，response 从该 ID 投影 `outcome_signal_ref=governance-signal:<signal UUID>`（response projection，不是存储列）。`low_rating` 物化为 review pressure（`ticket_pressure`、unknown freshness），`stale_answer` 物化为疑似 freshness/drift review（`drift`、stale freshness）。low_rating/stale_answer 的派生由 worker 独占：feedback 派生类型不能通过 admin write endpoint 创建，admin read endpoint 可以读取 worker 创建的 row。route 执行不会记录原始 `source_context` 或 `notes` payload。`routing_state` 沿 `<route_kind>_<route_state>` 表达（`review_running`、`review_completed` 等）；route 为 `queued` 时，依据 route kind 恰有一个 queue flag 为真，其他所有 route state 的两个 queue flag 都为假。
- 执行绝不自动修改知识内容，也绝不发布。Route 完成只证明已物化进 governed review truth——不代表 reviewer 已行动、草稿已创建、已发布、下游已传播、KPI 已改善或已产生业务影响。

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
- Sources Evidence 客户端只直接呈现 API 返回的来源失败事实、完整风险 context 与 durable mapped/unmapped impact 字段。不得通过客户端减法推导 watched 或 healthy 数量；`unmapped` 与覆盖不完整时的空结果都不是健康结论。
- `/api/recovery/overview`、`/api/recovery/window/{command_id}` 与 `/api/recovery/downstream-reality-check/{command_id}` 读取权限内的持久化 publication / propagation 真相并返回 `persisted: true, rehearsal: false`；这些 read surface 不会回退到 rehearsal fixture。

CYG-101～104 与 CYG-108 已把工单/改写压力、发布/事故 drift、受众冲突、审阅分配和 source impact 接入持久化或持久化派生 provider。只有 detector 完整执行且没有未解析关系时才可返回 `ready`；例如未解析 audience binding 仍必须返回 `partial`，provider 异常必须作为 `5xx` 暴露，不能用空数组或绿色 UI 冒充健康状态。

### 13.7 已落地的 governed session seam（CYG-92～96）
Nanobot 现在可以通过 `POST /api/session-bridge/query` 把 `request_ref`、可选 `session_ref`、support query、`audience_context` 与可选的前一轮 `governance_context` 交给 Cygnus。Cygnus 在请求级权限范围内重新装载 substrate-backed knowledge snapshot，并返回统一 envelope：`answer`、`source_trace`、`tool_trace`、`governance`、`continuity` 与下一轮可携带的 `governance_context`。

- `GET /api/session-bridge/capabilities` 与 Runtime MCP 消费同一份 shared adapter-definition contract，并将恰好十二个 governed tools 标为 `ready`，同时返回 `not_exposed:[]`：`search_knowledge_objects`、`read_knowledge_object`、`search_support_evidence`、`get_source_trace`、`list_drift_alerts`、`propose_knowledge_object`、`update_draft_object`、`request_review`、`read_review_feedback`、`record_feedback_signal`、`validate_publish_policy`、`publish_knowledge_object`。
- Runtime MCP 为 `list_drift_alerts`、`read_review_feedback` 与 `record_feedback_signal` 使用 authenticated visibility gate，为三个 R1 draft/review write 使用 contributor gate，并为 publication 使用 administrator gate。新 feedback 的 caller-owned transaction 暂存 signal、适用时的 mapped route 与一条 runtime audit；exact replay 返回已有 durable result，不产生重复 audit。queued feedback route 表示可认领的 intent：CYG-119 的有界 worker 会沿 `queued / running / completed / blocked / failed` 执行它，完成只证明已物化进 governed review truth——绝不代表 reviewer 已行动、草稿已创建、已发布、下游已传播、KPI 已改善或已产生业务影响。
- audience mismatch、pending review、stale/unknown freshness、source blindness 与 no-match 都返回结构化治理状态；分别收敛为 `restricted`、`escalate` 或 `fallback`，不能生成看似可直接外发的答案。
- continuity 每轮都重新查询 Cygnus truth。受众、对象、版本、trace 或 freshness 改变时前一轮 context 必须失效；即使没有变化也只能标记为 revalidated，且始终返回 `session_memory_used_as_truth:false`。

该接缝没有在 Cygnus 中增加第二套 session loop 或 memory store；Nanobot 仍拥有会话，Cygnus 只拥有知识、检索与治理裁决。
