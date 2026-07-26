# Support Brain for SaaS — 信息架构 / 页面结构

## 1. 目标
本文件定义第一版产品的信息结构，而非高保真 UI。重点是回答：
- 运营者在系统里会看到哪些核心模块
- 这些模块如何围绕支持知识对象协作
- 哪些表面属于 V1，哪些只是 future-facing

## 2. 顶层产品表面
### A. Knowledge Review Console
用途：审核 AI 建议创建/修改的知识对象，并决定发布与否。

关键视图：
- Draft Queue
- Diff Review
- Source Evidence Panel
- Audience Variant Comparison
- Publish Decision Bar

### B. Knowledge Object Workspace
用途：查看、编辑、版本化管理已存在的知识对象。

关键视图：
- Object List
- Object Detail
- Relationship Graph
- Version History
- Status / Ownership

### C. Coverage & Drift Dashboard
用途：识别哪些主题缺知识、哪些对象过期、哪些回答被人工频繁改写。

关键视图：
- Coverage Gaps
- High Rewrite Topics
- Freshness Alerts
- Audience Coverage Matrix
- Source Drift Signals

### D. Ticket Cluster Insights
用途：把重复工单模式转成待审知识建议。

关键视图：
- Cluster List
- Cluster Summary
- Suggested Object Type
- Draft Recommendation
- Acceptance / Rejection Actions

### E. Source Connectors & Sync Status
用途：管理知识输入源与同步健康度。

关键视图：
- Connector Catalog
- Sync History
- Parse Failures
- Source Priority Rules
- Access Scope Settings

### F. Publication & Channel Rules
用途：控制哪些知识对象可以被哪些渠道使用。

关键视图：
- Channel Matrix
- Internal vs External Access
- Audience Targeting Rules
- Region / Plan / Version Filters
- Publish History

### G. Agent Copilot Surface
用途：在客服工作流中消费已发布知识，而不是直接做知识治理。

关键视图：
- Suggested Answers
- Related Knowledge Objects
- Source Trace
- Escalation Guidance
- Feedback / Rewrite Capture

### H. Command Center / Morning Brief（指挥简报）
用途：作为审阅的“治理指挥入口”，按风险重排今天最值得介入的项，而不是按创建时间列草稿。它是 Review Console（A）的风险排序入口，而非独立内容库。
状态：域逻辑已实现（`cygnus/review/briefing.py`），UI 未建。

关键视图：
- Situation Frame（今日系统 tension）
- Priority Stack（按 Review Risk Type 重排）
- 每项的受影响 audience / 下游 surface / Owner State

### I. Propagation Ledger（传播账本）
用途：发布后显示命令传播到了哪里、卡在了哪里。它是 Publication & Channel Rules（F）的发布后视图。
状态：域逻辑已实现（`cygnus/publish/propagation.py`），UI 未建。

关键视图：
- 各 supporting surface 的 Propagation Status（synced / pending / failed / manual_action_required）
- Blocked Stage 列
- 后续命令入口

### J. Recovery Window（恢复窗口）
用途：围绕一次治理动作回答“系统是否因此更一致”，提供前后对比与未闭合点，用于验证治理是否真正生效。
状态：规划中（对应 Jira E4 / CYG-16、CYG-17），尚未实现。

关键视图：
- 前后对比（rewrites / escalations / coverage gap / drift / publish conflict 的变化）
- 残余风险与未闭合 loop
- 下一步命令入口

## 3. 一级导航建议
- Command Center / Morning Brief
- Review Queue
- Knowledge Objects
- Ticket Insights
- Coverage
- Sources
- Publish Rules
- Propagation Ledger
- Copilot
- Recovery Window（规划中）

## 4. 核心页面流
### Flow 1：从 Ticket Cluster 到已发布知识
1. Ticket Insights 发现重复模式
2. 生成知识建议草稿
3. Review Console 审核证据与对象类型
4. 在 Workspace 编辑对象细节与 audience variant
5. 通过 Publish Rules 发布到 internal/external channels

### Flow 2：从过期信号到知识更新
1. Coverage Dashboard 发现 freshness/drift
2. 打开对象详情
3. 查看 source diff / release note / known issue evidence
4. 生成新版本草稿
5. 审核通过后重新发布

### Flow 3：客服使用 Copilot 并回写反馈
1. Copilot 提供建议答案
2. 客服查看 trace 与 audience 适配
3. 客服改写 / 升级 / 拒绝建议
4. 反馈被回写进覆盖率与改写信号

## 5. 对象与页面关系
- **Answer Card**：Review / Workspace / Copilot / Publish Rules
- **Troubleshooting Flow**：Review / Workspace / Copilot
- **Policy Rule**：Workspace / Publish Rules / Copilot
- **Known Issue Page**：Coverage / Workspace / Copilot
- **Escalation Route**：Workspace / Copilot
- **Audience Variant**：Review / Workspace / Publish Rules

## 6. V1 页面边界
### Included in V1 IA
- Command Center / Morning Brief（指挥入口；域逻辑已实现，UI 未建）
- Review Queue
- Knowledge Objects
- Ticket Insights
- Coverage dashboard
- Source connectors basic views
- Publish rules basic controls
- Propagation Ledger（域逻辑已实现，UI 未建）
- Copilot answer consumption surface
- Recovery Window（规划中，尚未实现 — 对应 Jira E4）

### Deferred from V1 IA depth
- full customer bot conversation builder
- action execution center
- enterprise-grade analytics customization
- pricing/admin/billing center

## 7. 信息架构原则
1. **Object-first，不是 file-first**
2. **Review is central, not secondary**
3. **Copilot is a consumer of knowledge, not the product center**
4. **Coverage / drift is operational, not decorative**
5. **Source trace should be one click away from every answer**
