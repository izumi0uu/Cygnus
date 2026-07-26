# Support Brain for SaaS — 产品定义 / PRD

## 1. 一句话定义
**Support Brain for SaaS** 是一个不替代 Zendesk / Intercom 的 **客服知识大脑**：它把分散的支持知识编译、审核、分发给 AI agent 和人工客服，让所有回答基于同一套可追溯、可分 audience、可发布治理的支持知识。

## 1.1 与 Arkon 的关系
Cygnus / Support Brain 不是一个“只是从 Arkon 借了一点灵感”的新产品。

在当前项目定义里，更准确的关系是：
- **Arkon** 是底层的 **LLM wiki / knowledge compilation / RAG 实现基座**
- **Support Brain for SaaS** 是建立在这个基座之上的 **support 垂直增强产品**
- **Cygnus** 是这个 Arkon-enhanced support 产品当前落文档与后续实现的仓库/产品表面

更具体地说，Arkon 预期承载的是这些底层知识系统能力：
- source ingest 与 normalization 形态
- LLM-wiki 风格的知识编译
- draft / review / publish 机制
- 底层知识检索 substrate

而 Support Brain 在此之上增加的是 Arkon 本身没有直接定义好的 support 领域层：
- support-native knowledge objects
- audience-aware 的支持答案
- 支持策略与 escalation 逻辑
- support-specific 的 freshness / drift / feedback loops

所以更正确的理解不是：
- “一个与 Arkon 无关的全新产品”

而是：
- **“一个面向 SaaS 支持团队的 Arkon 增强型 support knowledge operating system”**

## 2. 产品不是什麽
它不是：
- 另一个 customer-facing 客服机器人
- 通用 RAG / 通用知识库平台
- 纯搜索工具
- GTM / 销售叙事产品

## 3. 问题定义
多数 SaaS 支持团队已经拥有：
- Help Center / Docs
- Zendesk / Intercom / Freshdesk
- Confluence / Notion / 内部 SOP
- 已解决工单与聊天记录
- Release notes / incident updates / known issues

但这些知识通常存在五类断裂：
1. **分散**：知识散落在文档、工单、聊天、发布记录中
2. **过期**：答案跟不上版本、策略、事故状态变化
3. **无 audience 区分**：同一问题对不同 plan / region / version 应给不同答案
4. **无沉淀**：重复工单经验没有变成结构化知识对象
5. **无追溯**：主管不知道 AI 为何答错，也不知道应改哪一条知识

## 4. 产品假设
如果我们把支持知识先编译成可审核、可发布、可追溯的结构化对象，再把这些对象分发给客服 copilot、help center 和 AI agent，那么：
- 回答会更一致
- 答案更新会更快
- audience 差异会更可控
- 支持团队能把工单经验沉淀成知识资产
- AI 错误可以追溯到具体知识缺口，而不是模糊归因到“模型不好”

## 5. 核心用户
### Primary users
- Head of Support
- Support Ops / Knowledge Manager
- Senior support agent / escalation lead

### Secondary users
- CX / Product Education
- Product / PMM（只读或协作角色）
- Internal AI / support copilot consumers

### Deferred users
- End customers directly interacting with AI

## 6. 产品定位
### Category
**Support knowledge operating system**

### Positioning statement
对于使用现有 helpdesk 系统的 SaaS 支持团队，Support Brain 是一层位于 Zendesk / Intercom / 自研支持系统之上的 **知识控制层**。它不替代 ticketing 或聊天系统，而是负责把支持知识变成可编译、可审核、可追溯、可按 audience 分发的答案系统。

### Competitive framing
- **vs. Zendesk / Intercom AI**：它们更像答复执行层；Support Brain 是知识治理层
- **vs. generic RAG**：RAG 偏向检索片段；Support Brain 偏向支持语义对象与发布治理
- **vs. internal wiki**：wiki 是存储；Support Brain 是编译、审核、分发、反馈闭环

## 7. 核心原则
1. **Knowledge before answer**：先治理知识，再治理回答
2. **Support-native objects**：不用匿名 chunk 作为产品核心
3. **Audience-aware**：答案必须理解 plan / region / version / language 差异
4. **Human-in-the-loop**：新知识默认进草稿，不直接污染线上
5. **Traceability first**：每条答案都应可追溯到来源与发布时间
6. **Freshness matters**：release / known issue / ticket trend 一变，知识应被重新编译

## 8. 核心知识对象
第一版围绕以下对象建模：
- **Answer Card**：面向客户的标准回答
- **Troubleshooting Flow**：排障流程
- **Policy Rule**：退款、取消、权限、SLA 等规则
- **Known Issue Page**：已知问题与 workaround
- **Escalation Route**：何时升级、升给谁
- **Audience Variant**：按 plan / region / version 的差异答案

这些对象比 chunk 更接近支持团队的真实工作单位。

## 9. V1 产品边界
### V1 focus
第一版文档假定产品第一阶段优先做：
- internal support copilot knowledge layer
- knowledge compiler / review / publish workflow
- ticket-to-knowledge suggestion
- audience-aware search and answer retrieval
- traceability and coverage insight

### V1 not focus
第一阶段不优先展开：
- customer-facing AI bot 交互设计
- action layer（如改套餐、发退款）
- GTM / pricing / sales narrative
- 深度技术架构锁定

## 10. 关键产品能力
1. **Multi-source ingest**
2. **Support-semantic normalization**
3. **Ticket-to-knowledge reduction**
4. **Knowledge object planning**
5. **Review and publish control**
6. **Audience-aware retrieval**
7. **Coverage / drift observability**
8. **Source traceability**

## 11. 产品表面（高层）
### 主控台主语
- **Support Mission Control**：support lead / support ops 的全局态势、风险、优先级与调度主控台

### supporting surfaces
- Knowledge Review Console
- Coverage & Drift Dashboard
- Knowledge Object Workspace
- Source Connectors / Sync Status
- Ticket Cluster Insights
- Publication & Channel Rules
- Agent Copilot Surface（supporting surface，不是产品主控台）

## 12. 成功定义（对齐阶段）
第一版文档成功，不是因为它已经变成了工程蓝图，而是因为它已经让后续所有人对以下问题拥有统一答案：
- 这是什么产品，不是什么产品
- 解决的是哪类支持知识问题
- 第一版最小对象模型是什么
- 第一版工作流如何闭环
- 哪些内容明确延后
- AI / human / help center 如何共享同一知识源

## 13. 未来方向（仅作边界提示）
- V2：customer-facing answer engine
- V3：action layer
- 更细的 permissions / compliance / regulated topics
- 更深的 analytics / ROI / knowledge health scoring
