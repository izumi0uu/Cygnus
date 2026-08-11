# Support Brain for SaaS — 核心工作流 / 生命周期

## 1. 目标
本文件定义 Support Brain 的主闭环，重点不是底层 job 编排，而是产品层必须成立的知识生命周期。

## 2. 主工作流概览
1. **Ingest**
2. **Normalize**
3. **Map / Reduce**
4. **Plan**
5. **Review**
6. **Publish**
7. **Feedback Loop**

## 3. 分阶段定义

### 3.1 Ingest
输入来自：
- Help Center / docs
- helpdesk articles
- internal SOP / wiki
- resolved tickets / chat transcripts
- release notes
- incidents / known issues

输出：
- 可被解析的 source records
- 基础同步状态与错误状态

### 3.2 Normalize
把分散来源统一成支持语义。

关键归一化维度：
- product / feature
- plan / tier
- region
- language
- product version
- issue type
- visibility（internal / external）

输出：
- normalized support evidence
- tags / metadata / confidence / freshness markers

### 3.3 Map / Reduce
从证据中抽出可用于创建知识对象的支持模式。

重点抽取：
- recurring questions
- rules and exceptions
- troubleshooting sequences
- known issue patterns
- escalation triggers
- audience-specific differences

输出：
- candidate answer shapes
- ticket clusters
- draft object suggestions

### 3.4 Plan
决定应该创建或更新哪些对象，而不是直接给出最终答案。

计划维度：
- object type
- evidence sufficiency
- urgency / freshness
- audience coverage gap
- risk of wrong answer

输出：
- create / update proposals
- suggested priority
- routed reviewer ownership

### 3.5 Review
由人或受控 AI 进行审查。

审查问题：
- 证据是否足够
- 对象类型是否正确
- audience variant 是否完整
- 是否需要转 internal-only
- 是否存在政策/合规风险

输出：
- approved draft
- rejected draft
- needs-more-evidence draft

### 3.6 Publish
把 approved 对象发布给目标渠道。

目标渠道示例：
- internal support copilot
- internal AI assistant / MCP
- external help center
- customer-facing answer engine（后续）

发布控制：
- audience filters
- internal/external visibility
- versioning
- publish history

发布动作（不止 approve / reject）：
- `publish` / `restrict` / `split_variant` / `hold_external` / `republish_internal_only`

发布前 blast-radius 预览（逐个 audience × channel 的后果）：
- `new_exposure` / `continuing_exposure` / `stopped_exposure` / `conflict`

发布后传播状态（各下游面是否已同步）：
- `synced` / `pending` / `failed` / `manual_action_required`

### 3.7 Feedback Loop
从消费结果反推知识缺口。

反馈信号示例：
- unresolved conversation
- low rating
- human rewrite
- escalation after suggestion
- stale answer due to release/incident

输出：
- drift alert
- coverage gap
- refresh candidate
- object deprecation/update queue
- durable feedback-route 生命周期真相（`queued` → `running` → `completed`；目标缺失、仅 draft 或不符合条件时 `blocked`；失败在有界 backoff 下最多退回 3 次，之后以 `failed` 结束），其完成只物化进 governed review truth，绝不自动修改内容或发布

## 4. 关键闭环
### Loop A：Ticket-to-Knowledge
重复工单 -> cluster -> draft object -> review -> publish

CYG-122 把 Loop A 的输入边界固化为一个有界 pilot：管理员通过 `POST /api/governance/ticket-imports` 提交已脱敏的 `resolved-ticket-export/v1` CSV/JSONL snapshot；`source_ref` 是不可变导出身份，整包验证通过后才按 `issue_signature + audience/product/version/language + object_type` 确定性分组。未达到可配置阈值的 cluster 只在响应中作为候选可观察；达到阈值的 cluster 才复用既有 `GovernanceSignal` 与 review-assignment 真相，保存结构化 ticket evidence refs。Exact replay 返回同一 signal，复用 `source_ref` 却改变事实返回 conflict；导入绝不自动创建 draft、approve 或 publish。

CYG-123 在该导入边界之后增加显式的 reviewer-controlled draft 命令：已认证管理员可针对符合条件且仍为 `active` 的 `ticket_pressure` signal，通过 `POST /api/governance-signals/{signal_ref}/commands/promote-draft` 提交 `command_id`、`expected_assignment_version` 与非空 `reason`。同一事务会锁定 signal、验证 assignment 版本与结构化 ticket evidence，创建 `WikiPageDraft(status=draft)` 和 append-only governance event，并记录可重放的 promotion receipt；完全相同的 `command_id` 返回同一结果，负载漂移返回 conflict。成功只证明 draft 已持久化；不会提交审阅、审批或发布。

### Loop B：Freshness Recovery
release/incident change -> drift alert -> revision draft -> review -> republish

### Loop C：Consumption-to-Improvement
copilot answer -> rewrite/reject/escalate -> feedback signal -> coverage fix

### 从信号到治理命令（signal → review pressure → command）
drift / ticket / source 信号不止是观察项，而是可被直接发出的治理命令。命令类型已在实现中固化：
- 漂移（drift）→ `open_urgent_review` / `freeze_external_publish` / `force_audience_recheck`
- 工单 / 改写压力（ticket_pressure）→ `route_to_review` / `assign_owner` / `mark_urgent`
- 来源失明（source_blindness）→ `repair_source` / `restrict_propagation` / `route_to_human_review`
- 审阅队列重排 → `restack` / `reroute` / `escalate`
- 消费反馈 route（CYG-118/119）：`low_rating` 物化为 review pressure（`ticket_pressure`、unknown freshness），`stale_answer` 物化为疑似 freshness/drift review（`drift`、stale freshness）；route 执行只物化 durable governed review truth，绝不自动修改内容或发布
- CYG-120 运维观察：`GovernanceFeedbackRoute` 仍是唯一 queue truth；权限内 SQL summary/drilldown 与结构化 worker outcome event 可区分 backlog、due age、lease expiry、retry、blocked/failed 与 outcome/review trace，但这些运行证据不等于 reviewer action、发布、传播或业务 KPI

## 5. 生命周期原则
1. **New knowledge defaults to draft**
2. **No publish without traceable evidence**
3. **Audience fit is part of correctness**
4. **Feedback is a first-class product input**
5. **Refresh is continuous, not a maintenance afterthought**

## 6. V1 工作流边界
V1 必须讲清楚：
- internal copilot 如何消费已发布知识
- 工单模式如何变成知识建议
- 发布如何受到 audience / visibility 控制
- 错误回答如何反推知识更新

V1 不必讲清楚：
- action layer orchestration
- fully autonomous customer bot loop
- fine-grained infra jobs / queues / schedulers
