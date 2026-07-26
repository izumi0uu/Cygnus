# Support Brain for SaaS — 开放问题与待验证假设

## 1. 目的
本文件记录第一版文档故意不写死的部分，以便后续研究、产品验证与架构规划使用。

## 2. 待验证产品假设
### H1. Internal copilot-first 会比 customer-facing first 更容易证明 ROI
待验证原因：
- 风险更低
- 更容易避免高风险答错
- 更容易从已有工单与客服改写中观察价值

验证信号：
- 客服采纳率
- 改写率下降
- 升级率变化
- 知识建议接受率

### H2. Ticket cluster -> knowledge suggestion 是真正的差异化能力之一
待验证原因：
- 如果只能 ingest docs，产品容易退化成 generic knowledge layer
- 如果 ticket patterns 能稳定转对象，才会体现 support-native intelligence

验证信号：
- cluster 转 draft 的可用率
- reviewer 接受率
- 从 cluster 到 published object 的时延

### H3. Audience-aware publishing 是比“回答正确率”更强的产品壁垒
待验证原因：
- 支持场景的错误往往来自 entitlement / region / version 差异
- audience mismatch 比纯文本错误更昂贵

验证信号：
- variant coverage ratio
- audience-related answer failures
- plan/version-specific rewrite frequency

## 3. 待决策问题
1. 第一阶段最小 audience 维度是否只做 plan / region / version
2. 是否需要把 internal-only 与 external-approved 建模成一等权限层
3. Ticket cluster 的最小可信证据阈值是什么
4. Known Issue Page 与 Answer Card 的边界何时自动切换
5. Escalation Route 是否作为独立对象，还是附着在 Answer Card / Flow 上
6. Coverage & Drift Dashboard 的最小指标集合是什么
7. 前端产品语言 Phase 2：领域层生成的叙事（`title` / `why_now_summary` / `primary_tension` / `headline`）目前为硬编码英文；需后端改为结构化暴露（枚举 + 参数），由前端按 zh/en 组句，同时解掉“UI 文案耦合进领域层”的问题。Phase 1（前端枚举/标识符词表 `frontend/src/lib/vocab.ts`）已完成；Phase 2 待后端排期。
8. P2.5 内化迁移线应优先按 **identity / assembly / namespace / deletion-readiness** 中的哪种切法推进，才能既不回退成 P1 重写，也不阻塞早期 P3。
9. Optional product-shell parity 是否永远保持为 deferred / non-roadmap lane，而不是正式 roadmap 项。
   - 当前已冻结的边界：`auth / admin / wiki` 壳层必须先分类；非 support 主语页面继续隔离在 future parity lane，除非它们直接解除 support verticalization 阻塞。

## 4. 待验证集成问题
- 第一优先接入哪些 source connectors
- Release notes / incidents 的结构化程度是否足以支持 freshness loop
- 不同 helpdesk 平台的数据模型差异是否会影响统一对象层
- MCP / internal AI assistant 的消费接口最小需要哪些 tools
- Nanobot 会话层与 Cygnus typed-domain tools 的边界，在真实运行时还需要哪些额外约束

## 5. 风险清单
### R1. Generic RAG drift
风险：产品被解释成“另一个知识库搜索层”
缓解：所有文档和后续设计都以 support-native objects 为主语

### R2. Scope expansion too early
风险：过早同时做 customer bot + action layer + pricing story
缓解：持续坚持 internal copilot-first 和 product-core first

### R3. Freshness without governance
风险：只做 ingest，不做 review/publish/traceability
缓解：把 review 和 publish 放在产品中枢，而不是附属功能

### R4. Audience modeling under-specified
风险：答案看似正确，但对错误人群生效
缓解：把 audience variant 作为对象层而非后处理层

### R5. Full-port drift without boundary discipline
风险：全量迁移过程中再次把 import parity、runability recovery、support verticalization 混成一个“完成态”
缓解：持续按 P0/P1/P2/P2.5/P3/P4 记录 Jira 与文档，不让状态词漂移

### R6. Optional shell parity starts stealing the current roadmap
风险：产品壳/管理壳 parity 过早抢走 P1/P2/P3 的带宽
缓解：默认把 shell parity 视为 deferred / non-roadmap lane，除非它直接解除关键 support verticalization 阻塞

## 6. 暂不展开但未来需要的主题
- 详细技术架构
- 权限与合规模型
- action layer
- customer-facing bot UX
- GTM / pricing / packaging
