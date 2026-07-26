# Support Brain for SaaS — 领域数据模型

## 1. 建模目标
该模型服务于产品定义与知识治理，不是数据库表结构。重点是定义：
- 支持知识的核心对象是什么
- 这些对象的状态、关系、来源和发布方式是什么
- 为什么这些对象比“chunk”更适合作为产品核心

## 2. 核心对象

## 2.1 Source Connector
表示一个知识输入源。

示例来源：
- Help Center
- Zendesk articles
- Intercom articles
- Confluence / Notion
- resolved tickets / chats
- release notes
- incident updates

关键属性：
- source type
- owner
- sync status
- auth scope
- last synced at
- parsing health

## 2.2 Support Evidence
表示被归一化后的原始证据片段，是知识对象的依据，不是直接对外的答案单位。

关键属性：
- source connector
- source URL / record ID
- extracted text / metadata
- product / feature tags
- plan / region / version tags
- confidence / freshness markers

## 2.3 Answer Card
面向客户的标准回答对象。

关键属性：
- question / intent
- canonical answer
- constraints / caveats
- audience variants
- linked evidence
- publish targets
- status

适用场景：
- FAQ 型问题
- 解释型问题
- 简单流程指导

## 2.4 Troubleshooting Flow
用于指导复杂问题排查的步骤对象。

关键属性：
- problem statement
- prerequisites
- ordered steps
- branching conditions
- stop / escalate conditions
- linked evidence
- supported audiences

## 2.5 Policy Rule
表示支持策略规则。

关键属性：
- rule domain（refund/cancel/SLA/access/...）
- effective conditions
- exceptions
- audience / entitlement scope
- source of authority
- human override notes

## 2.6 Known Issue Page
表示已知问题对象。

关键属性：
- issue summary
- affected product / version / region
- status
- workaround
- expected next update
- linked incident / release notes

## 2.7 Escalation Route
定义何时从标准知识转人工或升级团队。

关键属性：
- trigger conditions
- destination team
- severity / urgency hints
- information required before escalation
- blocked domains

## 2.8 Audience Variant
不是独立业务页面，而是附着在其他知识对象上的 audience 差异层。

维度示例：
- brand
- product line
- plan / tier
- region
- language
- product version
- internal vs external visibility

## 2.9 Ticket Cluster
由重复工单模式抽象出的“候选知识输入”。

关键属性：
- cluster summary
- recurring intent
- volume / frequency
- representative examples
- suggested object type
- acceptance status

## 2.10 Publication Record
表示知识对象被发布到哪个渠道、何时生效、供谁使用。

关键属性：
- target channel
- visibility
- audience filter
- published version
- published by
- published at

## 2.11 Feedback Signal
表示知识消费后的反馈回流。

示例：
- copilot answer accepted
- human rewrite
- escalation after suggestion
- poor rating
- unresolved conversation

## 3. 对象关系
- Source Connector 产生 Support Evidence
- Support Evidence 支撑 Answer Card / Troubleshooting Flow / Policy Rule / Known Issue Page
- Ticket Cluster 可建议创建或更新知识对象
- Audience Variant 作用于多个知识对象
- Publication Record 绑定知识对象与消费渠道
- Feedback Signal 反向作用于 Coverage / Drift 和对象更新优先级
- Escalation Route 可被 Answer Card / Troubleshooting Flow 引用

## 4. 统一状态机（抽象）
适用于多数知识对象：
- Draft
- In Review
- Approved
- Published
- Superseded
- Archived

状态原则：
- 新知识默认不直接进入 Published
- Published 对象必须能追溯证据与版本
- Superseded 对象保留历史，不做硬删除叙事核心

## 5. 为什么不用 chunk 作为核心对象
chunk 可以是底层技术实现的一部分，但不能作为产品主语，因为它：
- 不符合支持团队认知单位
- 难以表达 policy / troubleshooting / escalation 差异
- 难以做 audience-aware publishing
- 难以对齐 review / ownership / lifecycle

因此 chunk 可以在底层存在，但对产品层应被更高阶的支持对象包裹。

## 6. V1 最小对象集合
V1 必须明确支持：
- Answer Card
- Troubleshooting Flow
- Policy Rule
- Known Issue Page
- Escalation Route
- Audience Variant
- Source Connector
- Support Evidence
- Ticket Cluster
- Feedback Signal

## 7. 审阅与治理状态词汇
以下是附着在审阅项、证据与发布动作上的受控状态词汇。它们不是独立对象，而是跨模块引用的一等值类型，且已在实现中固化（见 `cygnus/review`、`cygnus/evidence`、`cygnus/publish`）。

### 7.1 Review Risk Type — 审阅项代表的系统级风险
用于按治理风险重排审阅入口，而不是按创建时间排列：
- `audience_mismatch` — 受众 / 版本错配
- `drift` — release / incident 引发的知识漂移
- `source_blindness` — 来源失效导致的“治理失明”，而非单纯同步错误
- `ticket_pressure` — 重复工单 / 反复人工改写形成的审阅压力
- `policy_conflict` — 跨受众的策略冲突
- `owner_gap` — 责任人缺位

### 7.2 Owner State — 责任归属状态
- `assigned` / `unassigned` / `escalated`

### 7.3 Evidence Freshness — 证据新鲜度
- `fresh` / `stale` / `unknown`

### 7.4 Evidence Sufficiency — 证据充分度
- `insufficient` / `partial` / `sufficient`

### 7.5 Evidence Source Type — 证据来源类型
- `help_center` / `internal_sop` / `resolved_ticket` / `release_note` / `incident_update` / `chat_transcript`
