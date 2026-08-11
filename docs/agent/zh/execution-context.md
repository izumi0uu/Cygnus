# Support Brain for SaaS — Agent 执行上下文

## 1. 目的
本文件给后续 agent 一个稳定、简洁、可执行的产品语境，避免后续实现或扩写时把项目带偏。

## 2. Source of truth 优先级
1. `docs/zh/prd.md` / `docs/en/prd.md`
2. `docs/zh/domain-model.md` / `docs/en/domain-model.md`
3. `docs/zh/workflows.md` / `docs/en/workflows.md`
4. `docs/zh/information-architecture.md` / `docs/en/information-architecture.md`
5. `docs/zh/architecture.md` / `docs/en/architecture.md`
6. `docs/zh/tool-contracts.md` / `docs/en/tool-contracts.md`
7. `docs/zh/loop-boundaries.md` / `docs/en/loop-boundaries.md`
8. `docs/zh/open-questions.md` / `docs/en/open-questions.md`
9. `docs/zh/agent-harness.md` / `docs/en/agent-harness.md`
10. `docs/zh/eval-plan.md` / `docs/en/eval-plan.md`
11. `docs/zh/rag-strategy.md` / `docs/en/rag-strategy.md`
12. `docs/zh/arkon-full-port-migration-plan.md` / `docs/en/arkon-full-port-migration-plan.md`
13. `.omx/plans/ralplan-cygnus-arkon-full-port-baseline-consensus.md`

如果文件之间冲突：
- 以 PRD 的产品定位为上位约束
- 以 domain model 约束对象命名
- 以 workflows 约束生命周期逻辑
- open questions 中列出的未决项，不允许在实现中假装已定
- harness / eval 文档属于实现指导，不得覆盖更高位的产品与边界文档
- full-port migration plan 约束当前工程顺序，不允许回退成选择性抽取真相

## 3. 核心定位不变量
后续任何实现、扩写、页面设计、技术方案都必须保留：
- 这是 **support knowledge operating system**
- 这是一个 **Arkon-enhanced** 的 support 产品，不是与 Arkon 脱钩重造
- 它不是 generic RAG 产品
- 它不是 another customer-facing support bot
- 第一阶段优先 internal copilot + knowledge compiler
- review / publish / traceability 是中心，而非附属功能
- Nanobot 是唯一 general-purpose session loop
- Cygnus 内部工作流编排只能服务于 selected governance workflows，不得变成第二套自由游走 runtime
- LangGraph 不属于当前 Cygnus 主线；若仍有残留，也只能被视为传递依赖余留或归档规划上下文

## 4. 当前迁移纪律
当前不是从零定义新系统，而是在执行：

1. **P0 — Migration Manifest & Boundary Freeze**
2. **P1 — Arkon full-port source parity import**
3. **P2 — repair / runability recovery**
4. **P2.5 — Arkon internalization / upstream cutover**
5. **P3 — Cygnus support verticalization**
6. **P4 — optional product-shell parity**

Agent 必须保留以下纪律：
- 不要把 `CYG-6 ~ CYG-17` 误当成当前第一个工程入口
- 当前工程主线是 `CYG-23+`
- `CYG-18 ~ CYG-22` 是 bootstrap history，不是当前迁移真相
- 不要把 import parity、runability recovered、internalization completed、verticalization completed 混成一个完成态
- 优先保留 upstream Arkon topology；重命名/重构属于后续阶段，不是迁入阶段默认动作
- 如果目标是完整吸收 Arkon 并最终删除独立上游代码基座，必须进入独立的 P2.5 内化迁移线，而不是回写成 P1 迁入动作

### 4.1 状态语言契约
后续 agent 在 Jira 评论、handoff、日志、结项时必须遵守：

- **P1** 只能说“已镜像 / 已导入 / parity established”，不能说“已跑通”
- **P2** 只能说“已恢复接线 / 已恢复启动 / runability recovered”，不能说“产品已完成”
- **P2.5** 只能说“internalized substrate / upstream cutover started / Cygnus-owned runtime identity established”，不能说“support verticalization 已完成”
- **P3** 才能说“support verticalization implemented / governance surface established”
- 没有阶段限定词时，不要单独使用模糊的“已完成”来描述迁移结果
- `CYG-23 ~ CYG-25` 父线票不能因为一张子票完成就被 agent 误报为整条主线完成
- 新的内化迁移父线也不能被误报成“shell parity 已决定”或“P3 已开始”

### 4.1.1 Governed observation truth
- 治理读取必须先按权限作用域查询，再投影；不能用 `sample_*` 或 session memory 填充 runtime 结果。
- `ready`、`partial`、`unavailable` 是 detector 覆盖状态，不是异常吞噬机制；`partial`/`unavailable` 的空数组不得写成“无风险”。
- `SourceFailureObservation` 仍是来源失败事实。CYG-108 只允许从权限内可见 `WikiPage.source_ids`、active audience bindings、最新 durable publication / propagation 投影 `impact_state="mapped|unmapped"`、`audience_impacts` 与 `propagation_impacts`；`unmapped` 仅表示当前权限作用域内没有已映射的治理 Wiki 影响，不等于没有业务影响，也不得从原始 source row 推导 risk、owner 或执行命令。
- Sources Evidence 必须直接呈现 API 返回的来源失败事实、完整风险 context 与 durable mapping 字段。不得通过不相干集合的减法计算 watched 或 healthy 数量，也不得把 `unmapped` 或覆盖不完整时的空结果写成健康状态。
- `/api/recovery/overview`、`/api/recovery/window/{command_id}` 与 downstream reality check 只读取权限内的持久化 publication / propagation 真相并返回 `persisted:true, rehearsal:false`；缺少 durable recovery truth 时必须保持 unavailable，不能回退到 fixture。
- publish response / publish projection 的 `persisted:true` 只能来自已审批 typed `WikiPageDraft`、ready evidence、显式 channels 与 durable IDs 同事务落库；仅 `object_ref` 的 fixture 路径必须保持 `persisted:false`、`rehearsal:true`。
- governance audit 的 `persisted:true` 只证明 append-only ledger event 已落库，不代表知识对象已发布或 propagation 已完成；audit read 必须在 SQL 内按 Wiki read scope 过滤，并对不存在与越权的 event 统一返回 `404`。
- `/api/notifications` 是 durable recipient-scoped inbox：`read_at` 只投影为 `unread|read`，所有读取与状态迁移都在 SQL 内限制当前 recipient；前端不得从 command-center fixture 或 localStorage 派生通知。
- notification external fan-out 只能重新读取已提交的 IDs；事务回滚的 staged record 不得发送。

- propagation 创建时只能是 `pending`；不得把 publish 请求成功推导成下游已 `synced`，后者必须来自显式、版本校验的更新。


### 4.1.2 Governed session seam
- `/api/session-bridge/query` 必须在当前用户权限范围内重新装载 substrate truth；前一轮 `governance_context` 只能用于判断 continuity，不能作为回答依据。
- `session_memory_used_as_truth` 必须保持 `false`。audience/object/version/trace/freshness 变化时返回 `invalidated`；未变化时也必须重新检索后才能返回 `revalidated`。
- Runtime MCP 与 session capabilities 共用恰好十二个 `ready` adapter definition，并返回 `not_exposed:[]`：`search_knowledge_objects`、`read_knowledge_object`、`search_support_evidence`、`get_source_trace`、`list_drift_alerts`、`propose_knowledge_object`、`update_draft_object`、`request_review`、`read_review_feedback`、`record_feedback_signal`、`validate_publish_policy`、`publish_knowledge_object`。
- `list_drift_alerts` 在请求 DB session 内重新读取作用域内 durable signal truth。Authenticated R1 `record_feedback_signal` 只接受六种固定 feedback type，且要求非空、最多 220 个字符的 `command_id`。`GovernanceFeedbackSignal.command_id` 全局唯一，并保存基于规范化 payload 与已认证 actor 的 64 字符 `request_fingerprint`；exact replay 返回已有 signal/route 且不写入，复用 command ID 但规范化 payload 或 actor 改变会返回不写入的结构化 `conflict`，新的 command ID 则代表独立 feedback。Exact replay 保留相同的 signal/route 身份并投影 route 当前的 durable lifecycle——绝不是冻结的逐字节快照——因此稍后的 replay 可以如实显示 `completed`、`blocked` 或 `failed`，且不产生重复真相。
- 新 feedback 调用在同一个 caller-owned transaction 内暂存原始 `GovernanceFeedbackSignal`、适用时的 mapped `GovernanceFeedbackRoute` 与恰好一条 runtime mutation `AuditLog`；persistence owner 只 flush，exact replay 不产生重复 audit。feedback 以 `RESTRICT` 外键保留 `actor_id`、`page_id`、`draft_id` 链接；`object_id` 与 `source_context_ref` 是持久化上下文，source context 不是 `Source` 外键。object/draft 解析在 SQL 内按作用域执行；隐藏、缺失或有歧义的 ref 统一返回 `not_found`，冲突 ref 返回不泄露资源的 `conflict` 且不写入记录。每个 state-changing adapter 都必须在服务端重新检查 identity、作用域和资源权限。
- `GovernanceFeedbackRoute` 是唯一的 durable queue truth，在 `(feedback_signal_id, route_kind)` 上唯一，`route_kind` 为 `review|refresh`，`lifecycle_state` 沿 `queued / running / completed / blocked / failed` 推进。映射已冻结：`low_rating` → `review`，`stale_answer` → `refresh`，其他所有可接受 type → 无 route 的 `recorded_only`。`low_rating` 物化为 review pressure（`ticket_pressure`、unknown freshness）；`stale_answer` 物化为疑似 freshness/drift review（`drift`、stale freshness）。
- Routed response 暴露 `route_id`、`route_ref=feedback-route:{uuid}`、`route_kind`、跨生命周期的 `route_state`（`queued|running|completed|blocked|failed`）与形如 `<route_kind>_<route_state>` 的 `routing_state`（`review_queued|review_running|review_completed|review_blocked|review_failed` 或对应的 `refresh_*`）；`review_queued` 与 `refresh_queued` 恰有一个为真只在 route state 为 `queued` 时成立，`running`/`completed`/`blocked`/`failed` 时两个 queue flag 都为 `false`。Non-routed response 暴露 null route fields、`routing_state:"recorded_only"` 与两个都为假的 queue flags。
- CYG-119 的有界 worker 沿 `queued / running / completed / blocked / failed` 认领并执行 route：每次认领最多 `limit=25` 条、60 秒 lease；可重试失败最多 3 次、以 30 秒基础重试退回 `queued`；route row 携带 `attempt_count`、`next_attempt_at`、`lease_token`、`lease_expires_at`、`outcome_signal_id`、`terminal_reason`、`last_error` 与 `completed_at`。每次 mutation 只 flush、由 caller 提交；worker 先提交 claim，再以独立 transaction 提交每次 execution 或 failure。completed route 在 `feedback`/`review_queue` surface 物化一条 durable outcome `GovernanceSignal`，其身份为 `route_ref=feedback-route:<route UUID>`；durable route row 存储 `outcome_signal_id`，response 从该 ID 投影 `outcome_signal_ref=governance-signal:<signal UUID>`（response projection，不是存储列）。这些 outcome 的派生由 worker 独占：feedback 派生类型不能通过 admin write endpoint 创建，admin read endpoint 可以读取 worker 创建的 row。route 执行不会记录原始 `source_context` 或 `notes`。目标缺失、仅 draft 或不符合条件的 route 以 `blocked` 结束，不猜测目标；执行绝不自动修改内容或发布。完成只证明已物化进 governed review truth——不代表 reviewer 已行动、草稿已创建、已发布、下游已传播、KPI 已改善或已产生业务影响。
- CYG-120 的 `GET /api/governance/feedback-routes` 与 `/{route_id}` 必须先在 SQL 内按 Wiki page/draft read scope 限制 route，再计算 summary 或 drilldown；隐藏与缺失 ID 统一 `404`。读面不得暴露 `last_error`、feedback `notes` 或 `source_context_ref`。worker event 只允许 event、route ID/kind、transition、attempt、duration、outcome ref、稳定 terminal reason 与 exception class；不得写 exception text 或客户/来源 payload。运维 completion/outcome event 不等于 reviewer action、publication、propagation 或 business KPI。
- no match、pending review、audience mismatch、stale/unknown evidence 与 source blindness 必须返回结构化 `fallback`、`restricted` 或 `escalate`，不得补写答案。

### 4.1.3 工程执行控制权
- Jira 是唯一的交付 backlog 与工作流状态真相；priority、owner、blocker、进度和完成态都以 CYG issue 为准。
- 会改代码或跨 session 的交付必须先绑定一张 CYG issue；一次性的只读调查可以不建票。
- Trellis 默认只保留 specs 模式：可以使用 `.trellis/spec/`、`trellis-before-dev`、`trellis-check` 与 `trellis-update-spec`，但不得默认创建另一套 task lifecycle。
- 复杂或高风险工作可以生成绑定 CYG issue 的 neutral local plan；plan 只约束实现，不拥有状态，也不能覆盖 Jira。
- 完成证据来自 Git、tests、CI、smoke 与 review；转换 Jira 状态前必须把精简证据写回 issue。

## 4.2 Package owner contract
当前 package 解释必须保持一致：

- `cygnus/runtime/*` = imported runtime/app shell/reference topology
  - source execution-state transitions 与 source-ingest orchestration 可以留在 `cygnus.runtime`
- `cygnus/substrate/*` = Cygnus-owned substrate contracts
  - `source_outline` / `source_images` / `source_text` 现在都是 substrate owner boundary
  - 不要把这些 source compilation primitives 重新塞回 `cygnus.runtime.services`
- `cygnus/domain/*` = support-domain contracts / object vocabulary
- `cygnus/evidence/*` = evidence normalization and record layer
- `cygnus/retrieval/*` = object/evidence retrieval and source-trace query layer
  - semantic embedding persistence 也属于这个 owner boundary
- `cygnus/review/*` / `cygnus/publish/*` / `cygnus/recovery/*` = governance control-plane modules
- `cygnus/integrations/*` = external/session-facing integration adapters
- `cygnus/workflows/*` = workflow composition layer，不是 generic runtime shell
- `cygnus/api/*` = 已移除的 legacy package，目录下不应再有 Python 模块

当前 import policy 也必须保持一致：
- `cygnus.runtime.main` 是 canonical app owner
- `cygnus.api.*` 不得成为内部默认入口
- `cygnus.api.auth` / `cygnus.api.config` / `cygnus.api.governance_router` / `cygnus.api.app` 不得再被内部代码依赖
- 不允许重新引入 `app.*` 旧命名空间

当前 deletion-readiness gate 也必须保持一致：
- 在 `scripts/upstream_cutover_gate.py` 通过之前，不要声称“现在可以安全删除独立 Arkon 代码基座”
- 不能把 cutover 叙事写成 shell parity 或 P3 support verticalization
- 只有 gate 通过后，才允许把“删除前 readiness 已满足”写入 Jira / handoff / 结项说明
- 如果磁盘上还存在独立外部 checkout，先用 `scripts/external_checkout_preserve.py` 保全 ahead commits、dirty worktree 和 untracked files，再讨论破坏性删除
- `scripts/external_checkout_audit.py --fail-if-found` 才是物理删除完成的证明，不是 preserve 这一步本身

执行约束：
- 不要把 `runtime` 当成“整个产品后端”的唯一命名真相
- 不要再把新的治理/知识领域能力默认塞回 `cygnus/api/*`
- 只有在明确的架构收敛票中，才允许继续重组 `runtime` 或拆分出新的长期结构
- 在后续进一步 package 收敛时，优先保持 owner 解释和 import policy 一致

## 5. 关键术语
- **Answer Card**：标准回答对象
- **Troubleshooting Flow**：排障对象
- **Policy Rule**：支持策略对象
- **Known Issue Page**：已知问题对象
- **Escalation Route**：升级路径对象
- **Audience Variant**：受众差异层
- **Support Evidence**：知识依据证据
- **Ticket Cluster**：重复工单模式候选输入

治理状态词汇（**Review Risk Type** / **Owner State** / **Propagation Status** 等）见 `domain-model.md` §7 与 `workflows.md`；同样不要弱化成 generic 名词。

除非人明确要求，否则不要把这些对象重新命名成 generic article / chunk / snippet 等弱语义名词。

## 6. 文档维护规则
- 中英文文件要保持结构大体对齐
- 可以允许微小措辞差异，但不允许产品边界不一致
- 新增文档时，优先判断它属于 human-facing 还是 agent-facing
- 若新增内容是未决假设，先写入 open questions，而不是写进既定 PRD

## 7. 扩写约束
### 可继续扩写的方向
- MVP 计划
- 更细的权限模型
- MCP tool surface
- 轻量技术架构草图
- 仪表盘指标体系
- agent harness contract
- eval plan 与 fixture design
- RAG strategy 与 retrieval-policy design

### 暂不默认扩写
- GTM / pricing
- full customer bot conversation design
- deep infra design
- action layer detailed flows

## 8. 后续实现时的判断标准
一个方案更可能是对的，如果它：
- 强化知识对象，而不是强化搜索片段
- 让人工审核更强，而不是被绕过
- 让 traceability 更短路径可见
- 让 audience-aware publishing 更显性
- 让 ticket-to-knowledge 成为闭环的一部分
- 让 Cygnus 的治理面建立在 Arkon substrate truth 上，而不是只建立在页面叙事上

一个方案更可能是错的，如果它：
- 把产品中心换成聊天窗口
- 把对象层退化成文档段落检索
- 绕开 review 直接上线新知识
- 把 internal/external 或 audience 差异放到后处理里
- 把全量迁移误写成“马上重构成全新 support-native architecture”

## 9. 交接提示
如果后续要进入计划或实现模式，建议顺序：
1. 先从这些文档出发做正式计划
2. 先确认当前属于 P1 / P2 / P2.5 / P3 的哪一个执行面
3. 再决定 MVP 范围与 milestone
4. 最后才进入架构与开发
