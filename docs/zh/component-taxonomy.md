# Support Brain for SaaS — Component Taxonomy

## 1. 这份文档解决什么问题
前面的文档已经说明了：
- 产品是什么
- 页面如何组织
- 状态如何变化
- 命令如何流动

这份文档要继续解决一个更接近实现的问题：
**Cygnus 不是要拼出一套通用 dashboard 组件库，而是要形成一套带有控制塔语义的组件分类法。**

它定义：
- 哪些组件是整个产品的骨干
- 哪些组件是战情观察组件，哪些是发令组件，哪些是传播/恢复组件
- 组件应该以什么优先级出现在页面里
- 哪些设计做法会让产品重新滑回“BI 平台”或“agent workflow tool”

---

## 2. 组件分类的总原则

### 原则 1：组件必须携带角色，不只是携带数据
每个关键组件都必须回答一个角色问题：
- 它是在帮助用户看局势？
- 帮助用户做判断？
- 帮助用户发命令？
- 帮助用户看传播？
- 帮助用户判恢复？

### 原则 2：组件不应中性到可以放进任何后台
如果一个组件看起来可以无缝搬进 CRM、工单系统或普通分析台，它大概率还不够像 Cygnus。

### 原则 3：控制塔优先于编辑器
Cygnus 的大多数组件都不应以“写内容”为先，而应以“判断系统、治理传播、协调责任”为先。

### 原则 4：同一组件可以跨页复用，但语义不能漂移
例如：
- `Situation Frame` 在不同页面都存在，但它永远回答“为什么值得你在这里停留”
- `Propagation Theater` 在不同页面可以密度不同，但永远回答“动作穿过了哪些层”

### 原则 5：组件要遵守指挥顺序
组件不是平铺画廊，而应自然构成：
**Observe → Frame → Route → Change → Propagate → Verify**

---

## 3. 组件重力模型（Component Gravity Model）

为避免页面变成“多个卡片争抢注意力”，定义四层组件重力：

| 重力层 | 含义 | 典型组件 | 页面里的地位 |
|---|---|---|---|
| G0 指挥锚点 | 决定页面角色与命令上下文 | Situation Frame、Command Spine、Command Ribbon | 必须可见 |
| G1 战情主场 | 承担页面最核心判断 | Priority Stack、Decision Constellation、Drift Weather Layer、Propagation Theater | 页面唯一主战场 |
| G2 发令与治理 | 承担动作与路由 | Intervention Ladder、Decision Footer、Command Actions Strip、Closure Judge | 紧邻主战场 |
| G3 证据与回声 | 承担 blast radius、evidence、recovery、affected surfaces | Consequence Lens、Evidence Drawer、Recovery Snapshot | 辅助但不可隐藏 |

### 使用规则
- 一个页面最多只有 **1 个 G1 主战场**。
- G2 必须紧贴 G1，避免“先理解，再找半天按钮”。
- G3 可以折叠，但关键动作前后必须自动浮现或保持可见。

---

## 4. 组件家族

## 4.1 指挥连续性组件（Command Continuity Family）
这些组件负责让整套产品感觉像一个持续的 command cycle，而不是多个页面模块。

### 1. Command Horizon
**作用：** 显示全局健康、当前时间窗、活跃 command cycle。

- 常驻位置：页面最顶部
- 关键输入：global health、active cycle、freshness、incident/release context
- 必备状态：stable / elevated / critical / stale
- 不应变成：全局导航条 + 普通 KPI 顶栏

### 2. Situation Frame
**作用：** 用一句话和一个局势框架回答“为什么我在这里”。

- 常驻位置：页面首屏第一块内容
- 关键输入：risk scope、inaction cost、affected audiences、current owner gap
- 必备状态：calm / emerging / overdue / blocked / recovery-incomplete
- 不应变成：说明文字或 marketing hero

### 3. Command Spine
**作用：** 让用户知道自己处在 Observe / Frame / Route / Change / Propagate / Verify 的哪一段。

- 常驻位置：左 rail 或顶部流程带
- 关键输入：current phase、current command origin、next unresolved phase
- 不应变成：普通 stepper 或 breadcrumb

### 4. Command Ribbon
**作用：** 在跨页移动中保持 unresolved command 的连续感。

- 常驻位置：底部横条或右下悬浮条
- 关键输入：active command shadow、highest-risk unresolved issue、return target
- 不应变成：command palette 或通知中心

---

## 4.2 战情观察组件（Situation Intelligence Family）
这些组件负责让用户看见支持系统哪里在动。

### 1. Priority Stack
**作用：** 把“最值得介入的变化”压成清晰优先顺序。

- 典型页面：Command Center
- 核心问题：今天哪 3 件事最该出手？
- 必备状态：stable / emerging / incident-linked / overdue
- 不应变成：普通卡片列表

### 2. Movement Grid
**作用：** 展示 queue / topic / audience / channel 的多维变化。

- 典型页面：Command Center
- 核心问题：变化是在局部发生还是跨面扩散？
- 不应变成：静态报表矩阵

### 3. Decision Constellation
**作用：** 展示对象、队列、audience、source、owner 的关系聚集。

- 典型页面：Coordination Board
- 核心问题：这个风险区为什么值得控制塔介入？
- 必备状态：ambiguous ownership / cross-team / audience conflict / blocked propagation
- 不应变成：炫技网络图

### 4. Drift Weather Layer
**作用：** 把 drift 变成“正在压过来”的趋势，而不是离散红点。

- 典型页面：Coverage & Drift
- 核心问题：哪里快出问题了？
- 不应变成：heatmap 装饰层

### 5. Reality Check Strip
**作用：** 把 downstream rewrite / reject / escalate 变成控制塔可读的现实回声。

- 典型页面：Copilot / Downstream Reality Check
- 核心问题：上游治理有没有改变一线现实？
- 不应变成：客服绩效条

### 6. Signal Loss Layer
**作用：** 把 source failure 翻译成“系统失明”的感受。

- 典型页面：Source Integrity
- 核心问题：系统现在看不清哪里？
- 不应变成：技术异常面板

---

## 4.3 发令与治理组件（Governance Action Family）
这些组件负责把观察转成治理动作。

### 1. Intervention Ladder
**作用：** 让用户在多种动作类型之间选：route / assign / escalate / hold / review / constrain。

- 典型页面：Coordination Board
- 核心问题：此刻最合适的治理动作是哪一类？
- 不应变成：一排平权按钮

### 2. Decision Footer
**作用：** 在 review 上下文里承载 approve / reject / request evidence / reroute。

- 典型页面：Review Queue
- 核心问题：这批对象现在该如何处理？
- 不应变成：表格尾部工具栏

### 3. Command Actions Strip
**作用：** 在对象页承载 revise / split / restrict / escalate / send to review。

- 典型页面：Object Workspace
- 核心问题：我该改内容、改变体、还是改边界？
- 不应变成：CMS editor toolbar

### 4. Channel Gate Matrix
**作用：** 显示 publish / unpublish / restrict / partial rollout 的渠道与 audience 边界。

- 典型页面：Audience / Publish Command Center
- 核心问题：谁被允许看到什么？
- 不应变成：权限设置表单

### 5. Closure Judge
**作用：** 帮用户决定本轮命令是 close 还是 continue。

- 典型页面：Recovery Window
- 核心问题：这次改善够不够形成闭合？
- 不应变成：成功确认弹窗

---

## 4.4 证据与信任组件（Evidence Trust Family）
这些组件负责让命令与证据绑定，避免“看起来能动，但其实没依据”。

### 1. Consequence Lens / Blast Radius Preview
**作用：** 在动作前显示影响范围、受影响 audience、下游 surface、owner 变化。

- 常见位置：右 dock 或主动作前置区
- 不应变成：动作后的 summary 卡

### 2. Source Evidence Drawer
**作用：** 展示对象证据来源、时间、置信度、冲突来源。

- 典型页面：Object Workspace
- 不应变成：埋很深的附件面板

### 3. Command-origin Tag
**作用：** 在 review / propagation / recovery 页面中标记该项来自哪条命令。

- 典型页面：Review Queue、Ledger
- 不应变成：弱提示小标签

### 4. Audience Scope Summary
**作用：** 先说明“这条 truth 当前对谁成立”。

- 典型页面：Publish Command Center、Object Workspace
- 不应变成：筛选器摘要

### 5. Owner & Load Strip
**作用：** 在治理决策前把责任与负载显性化。

- 典型页面：Coordination Board
- 不应变成：纯资源利用率图表

---

## 4.5 传播与恢复组件（Propagation & Recovery Family）
这些组件是 Cygnus 与普通知识后台的差异核心。

### 1. Propagation Theater
**作用：** 展示一次命令如何穿过 review、publish、copilot、external surface。

- 典型页面：Publish、Propagation Ledger
- 核心问题：动作穿过去了吗？
- 不应变成：toast + activity log

### 2. Command Timeline
**作用：** 组织一次命令的阶段顺序与关键转折。

- 典型页面：Propagation Ledger
- 不应变成：审计日志时间线

### 3. Blocked Stage Column
**作用：** 明确指出传播卡住在哪一层，以及为什么。

- 典型页面：Propagation Ledger
- 不应变成：错误清单

### 4. Recovery Snapshot
**作用：** 在首页或局部页压缩显示最近命令是否有效。

- 典型页面：Command Center
- 不应变成：正负百分比 KPI 砖块

### 5. Before / After Alignment View
**作用：** 在 Recovery Window 中比较 drift、rewrite、escalation、conflict 变化。

- 典型页面：Recovery Window
- 不应变成：漂亮收尾页

---

## 4.6 支撑镜像组件（Supporting Mirror Family）
这些组件负责让用户看到下游现实、受影响面和剩余残差。

### 1. Mismatch by Audience View
**作用：** 将错误或 rewrite 按 audience 层分开看。

### 2. Affected Surfaces Preview
**作用：** 显示 internal copilot、human support UI、external help center 等受影响面。

### 3. Supporting-surface Status Mirror
**作用：** 在控制塔页上回显“下游是否真的同步”。

这些组件都应服务主战场，而不是自己成为主角。

---

## 5. 组件优先级层级（Implementation Priority）

| 优先级 | 含义 | 第一批必须实现 |
|---|---|---|
| P0 | 没它就不像 Cygnus | Situation Frame、Command Spine、Priority Stack、Decision Constellation、Consequence Lens、Propagation Theater、Recovery Snapshot / Recovery Window |
| P1 | 没它会削弱控制塔判断力 | Command Ribbon、Intervention Ladder、Channel Gate Matrix、Owner & Load Strip、Reality Check Strip |
| P2 | 没它仍能跑，但辨识度和效率下降 | Signal Loss Layer、Blocked Stage Column、Audience Scope Summary、Supporting-surface Status Mirror |

---

## 6. 语义 Token 轴（供后续设计 token 使用）

在真正落视觉 token 前，应先锁语义轴，而不是先锁颜色值。

### Token Axis A — Severity
- stable
- emerging
- elevated
- critical

### Token Axis B — Propagation
- local
- routed
- partial
- blocked
- landed

### Token Axis C — Confidence
- confirmed
- usable-with-caution
- degraded
- blind

### Token Axis D — Lifecycle
- draft
- review
- approved
- published
- superseded
- archived

### Token Axis E — Authority
- observe-only
- route-ready
- command-ready
- confirmation-required
- locked

这些轴会比“蓝色 500 / 红色 600”更早决定产品体验语言。

---

## 7. 反模式清单

以下情况意味着组件开始偏离 Cygnus：

1. 页面上多个 G1 主战场并列抢注意力
2. 所有动作按钮都被做成平权小按钮
3. 传播结果只以 toast 或 activity feed 表示
4. audience 被做成筛选条件，而不是 truth boundary
5. recovery 被做成成功收尾，而不是治理判断
6. copilot / downstream 页面看起来像客服工作台主界面
7. source integrity 页面看起来像纯技术监控页

---

## 8. 使用规则
后续设计或实现任一页面前，都应先回答：
1. 该页面的 G1 主战场组件是什么？
2. G2 动作组件是否紧贴主战场？
3. G3 证据/传播/恢复组件是否占到应有位置？
4. 该组件如果搬到普通后台还成立吗？如果成立，说明它还不够 Cygnus。

如果组件没有明确服务“观察、发令、传播、恢复”中的至少一个，它就不应进入第一批 Cygnus 设计系统。
