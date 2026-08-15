# Support Brain for SaaS — State Matrix

## 1. 这份文档解决什么问题
前面的文档定义了页面和骨架，但一个 control tower 产品真正决定体验质量的，往往不是默认态，而是：
**系统处于不稳定、中间态、冲突态时，页面如何说真话。**

这份文档定义：
- Cygnus 的核心状态词汇表
- 不同状态出现时页面该如何变化
- 用户该先被提醒什么、还能做什么、不能误判什么

---

## 2. 状态设计总原则

### 原则 1：先告诉用户还能信什么
错误态不是只告诉用户“坏了”，而是告诉用户：
- 哪部分 truth 仍可信
- 哪部分判断应暂缓
- 哪类动作仍可安全执行

### 原则 2：中间态要被承认
Cygnus 的许多状态不是 done / failed 二元，而是：
- partial rollout
- recovery incomplete
- evidence degraded
- route unresolved

### 原则 3：状态要服务命令
状态的目的不是装饰反馈，而是帮助用户决定：
- 继续观察
- 重新路由
- 暂停传播
- 发起补救
- 宣告闭合

### 原则 4：状态不能漂成运维告警墙
即使是 source 问题，也必须翻译成支持治理后果。

---

## 3. Cygnus 通用状态词典

| 状态 | 含义 | 用户第一反应应是 | 系统必须强调 |
|---|---|---|---|
| Calm / Stable | 当前无明显系统级漂移 | 观察，不必立刻下达命令 | 最近命令是否真的闭合 |
| Emerging Risk | 已出现早期偏移信号 | 判断是否值得提前介入 | 风险在扩大还是局部波动 |
| Leadership Intervention Overdue | 系统已进入该由控制层出手的阶段 | 立即进入协调链 | 不作为成本 |
| Stale but Usable | 数据旧但还能参考 | 先看 last-known truth，再谨慎动作 | 时间戳与新鲜度差 |
| Source Blindness | 某类来源失效，系统部分失明 | 降低置信度，优先修 source 或遏制下游 | 受影响对象与 surface |
| Evidence Degraded | 有内容，但证据不够强 | 要么补证据，要么限制传播 | 哪些命令不能安全发 |
| Ambiguous Ownership | 问题存在，但谁接球不清楚 | 优先厘清 owner | 跨队列/跨团队冲突 |
| No Safe Route Yet | 有风险，但暂无安全处理路径 | 先 containment，再扩大治理 | 不能假装可直接发布 |
| Conflict Across Audiences | 不同 audience 的答案相互冲突 | 先拆 variant，再决定发布 | 哪些 audience 不能共享同一答案 |
| Propagation Blocked | 命令已发，但未穿过全部 stage | 查看 blocked stage 并追加动作 | 哪里已同步，哪里未同步 |
| Partial Rollout | 部分 surface 已更新，部分未更新 | 判断是否容许短暂不一致 | 外部与内部是否不同步 |
| Recovery Incomplete | 指标改善但未恢复一致 | 决定是否继续新一轮命令 | “改善”不等于“闭合” |
| Recovery Confirmed | 本轮命令已形成稳定恢复 | 关闭本轮，转监控 | 仍需保留证据链 |

---

## 4. 全局状态呈现规则

| 状态类型 | 顶部 Horizon | Situation Frame | Main Field | Dock / Band |
|---|---|---|---|---|
| Calm / Stable | 低噪声稳定标记 | 提醒最近恢复结果 | 默认结构 | Recovery Snapshot 可压缩 |
| Emerging Risk | 轻度高亮 | 指出风险正在成形 | 显示变化趋势 | 建议下一步入口 |
| Leadership Intervention Overdue | 高优先级提示 | 强调不作为代价 | 提前排序高风险对象 | Command Ribbon 保持未闭合警示 |
| Stale but Usable | 显示 freshness 时间差 | 明确“这是 last-known truth” | 允许只读判断 | 禁止伪装实时成功 |
| Source Blindness | 明显告知部分失明 | 指出盲区范围 | 降低相关模块置信表现 | 提供 repair / contain 动作 |
| Propagation Blocked | 标注 active blocked cycle | 说明卡住后果 | 高亮 blocked stage | 后续动作必须紧邻出现 |
| Recovery Incomplete | 维持 cycle open | 说明“改善但未闭合” | before/after 中间态明显 | 继续 / 关闭必须明确区分 |

---

## 5. 分页面 State Matrix

## Screen 01 — Command Center

| 状态 | 页面表现 | 用户可做动作 | 必须避免 |
|---|---|---|---|
| Calm / Stable | Priority Stack 收缩，Recovery Snapshot 更突出 | 浏览、抽查最近恢复 | 假装什么都不用看 |
| Emerging Risk | Movement Grid 出现 drift front 或 rewrite cluster | 进入 Coordination / Drift Radar | 把新风险埋在统计后面 |
| Leadership Intervention Overdue | Priority Stack 顶部出现强烈 command callout | 立即发起介入 | 仍像普通日报 |
| Stale but Usable | 标出更新时间差，保留 last-known layout | 只做低风险判断 | 冒充实时战情 |
| Multi-surface Spread | Movement Grid 扩张到 cross-channel view | 进入 Propagation / Coordination | 把多 surface 问题当单队列噪声 |

## Screen 02 — Queue / Topic Coordination Board

| 状态 | 页面表现 | 用户可做动作 | 必须避免 |
|---|---|---|---|
| Ambiguous Ownership | Owner & Load Strip 高亮“无清晰 owner” | route、assign、escalate | 让用户自己推断归属 |
| No Safe Route Yet | Intervention Ladder 中部分动作禁用并解释原因 | contain、hold、request evidence | 允许危险 publish |
| Cross-team Issue | Decision Constellation 显示多团队拉扯 | route to team、escalate | 把复杂 ownership 扁平化 |
| Conflict Across Audiences | audience 节点呈现冲突色带 | split variant、restrict scope | 把冲突答案合并处理 |
| Propagation Blocked | 页面下部 band 显示前一次动作未穿透 | 再发 follow-up command | 让新动作脱离历史上下文 |

## Screen 03 — Coverage & Drift Radar

| 状态 | 页面表现 | 用户可做动作 | 必须避免 |
|---|---|---|---|
| Emerging Risk | Drift Weather Layer 出现轻度前沿 | 预先发起 refresh/review | 只在爆炸后才高亮 |
| Stale but Usable | coverage 仍可读，但 freshness 标志退化 | 打开 sources / objects | 把 coverage 与 freshness 混成一个数 |
| Source Blindness | Source vs Object Panel 明确偏向 source 责任 | repair source / contain publish | 让用户误判是内容问题 |
| Conflict Across Audiences | Gap Matrix 出现 audience 分裂空洞 | split route | 继续用统一 coverage 视图 |

## Screen 04 — Knowledge Review Queue

| 状态 | 页面表现 | 用户可做动作 | 必须避免 |
|---|---|---|---|
| Needs Decision Now | Priority Re-stack Lane 顶部锁定显示 | approve / reject / reroute | 让紧急项沉底 |
| Evidence Degraded | Evidence Strength Column 明确降级 | request evidence / hold publish | 让证据不足项正常流过 |
| Waiting on Owner | owner 列成为主要阻塞信号 | reassign / escalate | 只显示“等待中”而不给动作 |
| Safe to Defer | 视觉噪声降低 | defer / bundle review | 把延后项与紧急项同权 |

## Screen 05 — Knowledge Object Workspace

| 状态 | 页面表现 | 用户可做动作 | 必须避免 |
|---|---|---|---|
| Draft | lifecycle rail 明确显示未出闸 | revise / send to review | 给人已发布错觉 |
| Audience Conflict | variant pane 出现 split warning | split variant / restrict | 在同页混淆 internal/external truth |
| Evidence Degraded | evidence drawer 默认半展开 | add source / lower confidence | 把对象伪装成已稳定 |
| Propagation Blocked | object-level downstream map 显示未同步 surface | open ledger / republish / contain | 只告诉“保存成功” |

## Screen 06 — Audience / Publish Command Center

| 状态 | 页面表现 | 用户可做动作 | 必须避免 |
|---|---|---|---|
| Internal Only | Gate Matrix 明确外部闸门关闭 | prepare external / keep internal | 让 internal/external 关系不清楚 |
| Conflict Risk | Blast Radius Preview 高亮冲突 audience | split / restrict / hold | 直接鼓励 publish |
| Partial Rollout | Propagation Theater 显示已更新和未更新区 | continue rollout / rollback / hold | 只显示“发布完成” |
| Propagation Blocked | blocked stage 与 follow-up command 同屏 | reroute / republish / contain | 让用户去别页才知为何失败 |

## Screen 07 — Source Integrity / Evidence Health

| 状态 | 页面表现 | 用户可做动作 | 必须避免 |
|---|---|---|---|
| Source Blindness | Signal Loss Layer 占主场 | repair / resync / contain | 把 source failure 缩成次要通知 |
| Stale but Usable | 显示“旧但仍可参考”的 sources | 低风险观察 | 把 stale 直接当 broken |
| Evidence Degraded | Affected Objects 列表加低置信标签 | lower confidence / force review | source 健康和证据质量脱钩 |

## Screen 08 — Copilot / Downstream Reality Check

| 状态 | 页面表现 | 用户可做动作 | 必须避免 |
|---|---|---|---|
| Rewrite Spike | feed 顶部聚合 rewrite cluster | elevate to command | 只当一线个案 |
| Audience Mismatch | mismatch view 明确按 audience 分层 | open variant / publish control | 继续按整体平均看待 |
| Recovery Incomplete | 即使 rewrite 下降也保留未闭合提示 | reopen command cycle | 把局部改善当闭合 |

## Screen 09 — Propagation Ledger

| 状态 | 页面表现 | 用户可做动作 | 必须避免 |
|---|---|---|---|
| Command In Flight | timeline 显示当前 stage | wait with guardrails / inspect | 假装结果已定 |
| Propagation Blocked | blocked stage 成为主读点 | reroute / contain / republish | 把问题藏在日志深处 |
| Secondary Conflict | 受影响 surface 出现二次告警 | split follow-up command | 把传播失败视作单点错误 |
| Recovery Incomplete | ledger 明示传播已完成但恢复未完成 | open Recovery Window | 认为传播=恢复 |

## Screen 10 — Recovery Window

| 状态 | 页面表现 | 用户可做动作 | 必须避免 |
|---|---|---|---|
| Recovery Incomplete | before/after 显示改善但未闭合 | continue command | 只给绿色成功态 |
| Recovery Confirmed | closure judge 明确标记闭合 | close cycle / monitor | 隐去证据链 |
| Drift Rebound | after 指标短暂好转后再回升 | reopen drift route | 因一次改善就关闭 |

---

## 6. 创意状态：Cygnus 特有中间态

这些状态值得在体验上被命名，而不是只藏在数据里。

### A. Command Shadow
含义：上一轮命令仍在影响排序或判断，即使用户已跳到新页面。
表现：Command Ribbon 持续显示 unresolved shadow。

### B. Split-Brain Publish
含义：internal knowledge 与 external answer surfaces 暂时不一致。
表现：Publish / Propagation 页面必须明确点名两个 truth plane。

### C. Blind-but-Operating
含义：系统还能跑，但因为 source blindness 已失去完整观察能力。
表现：允许观察，不允许高风险自信发布。

### D. False Recovery
含义：某些指标变好，但根本 drift 或 audience mismatch 仍在。
表现：Recovery Window 必须阻止“漂亮但错误的闭合”。

---

## 7. 使用规则
后续任何页面设计都应先回答：
1. 这页最危险的误判是什么？
2. 如果数据不完整，用户还能安全做什么？
3. 这页有没有明确区分 partial、blocked、recovered、stale？
4. 状态是否直接帮助用户决定下一条命令？

如果状态只是在描述系统，而没有帮助用户决定下一步，它就还不是 Cygnus 的状态设计。
