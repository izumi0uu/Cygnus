# Support Brain for SaaS — Wireframe Architecture

## 1. 这份文档解决什么问题
`page-story-map.md` 定义了页面叙事，`screen-spec.md` 定义了逐屏职责。

这份文档继续往下一层，定义：
**这些页面在 wireframe 层到底应该怎么长。**

它回答的不是视觉风格，而是：
- 哪些区域必须持续存在
- 哪些区域是页面专属主场
- 关键创意对象在不同页面如何“变形”
- 用户视线应该先落哪里，再落哪里
- 一个 command cycle 在页面骨架里如何被看见

---

## 2. Wireframe 的核心原则

### 原则 1：先看局势，再看对象
页面不应先把用户推进单个文档或单个草稿。
第一视点必须先让用户知道：
- 当前 tension 是什么
- 这件事影响谁
- 为什么现在值得动作

### 原则 2：先定指挥位，再给操作位
关键页面上，命令上下文必须先于局部编辑器和局部表格出现。

### 原则 3：传播与恢复必须占到版面
Cygnus 不只是让用户做动作，还要让用户看见动作是否穿过系统。
因此每个关键屏都要有位置容纳：
- Consequence Lens
- Propagation Theater
- Recovery signal

### 原则 4：持续对象应跨页变形，而不是每页重造
同一创意对象需要在不同页面以不同密度存在。
例如：
- `Decision Constellation` 在首页可以是压缩版，在协调页应展开成主场
- `Recovery Snapshot` 在首页是摘要，在 Recovery Window 里应成为完整比对结构

### 原则 5：桌面端不是“响应式加宽”，而是指挥视野
桌面布局应优先保证：
- 左右之间有真正的战略层 / 执行层差异
- 上下之间有真正的“局势 -> 决策 -> 后果”层差异

---

## 3. 全局骨架：Command Frame

建议所有关键页面共享以下宏观骨架。

```text
┌──────────────── Command Horizon ────────────────┐
│ global health / active command / global time    │
├──────────────── Situation Frame ────────────────┤
│ why this matters / affected scope / current risk│
├──── Command Spine Rail ────┬──── Main Field ────┤
│ observe~verify position    │ page-specific arena│
│ active route / owner       │ judgment or action │
├──── Consequence / Evidence Dock ────────────────┤
│ blast radius / citations / audience impact      │
├──────────── Propagation + Recovery Band ────────┤
│ propagation theater / recovery signal / gaps    │
└──────────────── Command Ribbon ─────────────────┘
```

### A. Command Horizon
页面最顶层的薄带。
职责：
- 告诉用户当前整个系统是不是稳定
- 显示是否有 active command cycle 尚未闭合
- 显示当前时间窗（release week / incident / postmortem / drift spike）

### B. Situation Frame
进入页面后第一块真正读内容的区域。
职责：
- 把页面从“模块”变成“当前有意义的战情面”
- 显示风险范围、影响 audience、未处理成本

### C. Command Spine Rail
建议优先作为左侧持久 rail，窄屏可折叠成顶部 step strip。
职责：
- 告诉用户当前动作属于 Observe / Frame / Route / Change / Propagate / Verify 哪一段
- 保持对当前 command cycle 的连续感
- 提供回到上游 tension / 下游 propagation 的快速跳转

### D. Main Field
当前页面的主舞台。
职责：
- 承担该页面最核心的判断或治理动作
- 不被辅助面板夺走视线主权

### E. Consequence / Evidence Dock
建议默认为右侧 dock，在对象深钻页面可以展开。
职责：
- 在动作前展示 consequence
- 在动作中展示 evidence confidence
- 在动作后展示被影响的 surface 和 audience

### F. Propagation + Recovery Band
建议靠近页面底部，但不能隐藏太深。
职责：
- 告诉用户动作有没有真正传播
- 如果没有传播，卡在哪一层
- 如果传播了，是否真的降低了 drift / rewrite / escalation

### G. Command Ribbon
跨页轻量条。
职责：
- 让用户无论在哪页，都记得自己仍在一个命令闭环中
- 提醒最危险的未闭合回路
- 提供“一键回到本轮 command cycle”的能力

---

## 4. 持久区 vs 上下文区

| 区域 | 持久性 | 默认位置 | 说明 |
|---|---|---|---|
| Command Horizon | 全局持久 | 顶部 | 所有关键页面都保留 |
| Command Ribbon | 全局持久 | 底部或右下悬浮条 | 所有关键页面都保留 |
| Situation Frame | 页面持久 | 页面首屏 | 页面进入理由必须明确 |
| Command Spine Rail | 流程持久 | 左侧 | 关键 flow 页面保持连续 |
| Main Field | 页面专属 | 中央 | 每页唯一主场 |
| Consequence / Evidence Dock | 上下文型 | 右侧 | 可折叠，但关键动作前必须可见 |
| Propagation + Recovery Band | 流程持久 | 下部 | 命令页必须保留 |

---

## 5. 创意对象的跨页变形规则

## 5.1 Situation Frame 的变形
- 在 `Command Center`：是战情 briefing 头部
- 在 `Coordination Board`：是“为什么这条战线值得投入”的判断框
- 在 `Object Workspace`：是“这个对象为什么不是普通文档”的系统角色框
- 在 `Recovery Window`：是“本轮命令是否仍值得继续”的总结框

## 5.2 Decision Constellation 的变形
- 在首页：作为 compressed risk cluster map
- 在协调页：升级为主工作区
- 在对象页：缩成 object gravity 旁的关系示意

## 5.3 Propagation Theater 的变形
- 在 publish 页：作为 action 后立即反馈
- 在 Propagation Ledger：扩展成完整 stage map
- 在 Recovery Window：缩成“传播是否转化成恢复”的证据条

## 5.4 Recovery Signal 的变形
- 在首页：是 `Recovery Snapshot`
- 在 Ledger：是 `still-open vs closing` 指示
- 在 Recovery Window：成为 before/after 主比较结构

---

## 6. 逐屏 Wireframe Architecture

## Screen 01 — Command Center / Morning Command Brief

### 视线顺序
1. 今日 tension
2. 最值得介入的 3 个 movement
3. 正在进行中的 command cycle
4. 最近一次 recovery 是否有效

### 推荐骨架
```text
┌ Command Horizon ─────────────────────────────────────────────┐
├ Situation Frame: 今日支持系统最重要 tension + 影响范围 ───────┤
├ Left: Priority Stack ────────┬ Right: Movement Grid ────────┤
│ top 3 interventions          │ queue/topic/audience shifts  │
├ Left: Command Queue Preview ─┼ Right: Recovery Snapshot ────┤
├ Propagation/Recovery Band: 近期命令闭环状态 ─────────────────┤
└ Command Ribbon ─────────────────────────────────────────────┘
```

### 布局规则
- `Priority Stack` 必须比 `Movement Grid` 更先抓眼。
- `Recovery Snapshot` 不能变成埋在角落的统计块；它是“我最近的治理到底有没有用”的第一回显。

---

## Screen 02 — Queue / Topic Coordination Board

### 视线顺序
1. 当前风险战线定义
2. Decision Constellation
3. 可选 Intervention Ladder
4. owner / load / consequence

### 推荐骨架
```text
┌ Command Horizon ─────────────────────────────────────────────┐
├ Situation Frame: 风险战线说明 + 不动作的代价 ────────────────┤
├ Spine Rail ─┬ Main Field: Decision Constellation ───────────┤
│ stage       │ queue/topic/object/audience/source map         │
│ owner state │                                               │
├ Spine Rail ─┼ Intervention Ladder + Owner/Load Strip ───────┤
├ Consequence Dock: blast radius / affected owners / channels ┤
├ Propagation Band: 已发命令 / 待发后续 / blocked routes ─────┤
└ Command Ribbon ─────────────────────────────────────────────┘
```

### 布局规则
- `Decision Constellation` 必须占主舞台；不能变成角落图表。
- `Intervention Ladder` 应位于 constellation 的紧邻位置，保证用户在理解关系后立刻动作。

---

## Screen 03 — Coverage & Drift Radar

### 视线顺序
1. drift 正在从哪里压过来
2. 是 coverage 缺口还是 freshness 漂移
3. 该从 source / object / publish 哪边切入

### 推荐骨架
```text
┌ Command Horizon ─────────────────────────────────────────────┐
├ Situation Frame: 当前 drift front + 高风险 audience ─────────┤
├ Main Field Top: Drift Weather Layer ────────────────────────┤
├ Left: Coverage Gap Matrix ───┬ Right: Source vs Object Panel┤
├ Left: Audience Risk Strip ───┼ Right: Suggested Intervention│
├ Recovery Band: 过去干预是否压低 drift ───────────────────────┤
└ Command Ribbon ─────────────────────────────────────────────┘
```

### 布局规则
- `Drift Weather Layer` 应横跨顶部主区域，形成“风险前线”的感觉。
- `Suggested Intervention` 不能像 recommendation widget，而是像下一条建议发令入口。

---

## Screen 04 — Knowledge Review Queue

### 视线顺序
1. 当前 review queue 属于哪条命令
2. 哪些任务被重排到前面
3. 哪些任务证据不足或 owner 缺位
4. 如何快速批准 / 退回 / 改派

### 推荐骨架
```text
┌ Command Horizon ─────────────────────────────────────────────┐
├ Situation Frame: 当前 review queue 在应答什么系统风险 ───────┤
├ Spine Rail ─┬ Main Field: Priority Re-stack Lane ───────────┤
│ upstream    │ reordered review items                         │
│ command     │                                               │
├ Spine Rail ─┼ Table: evidence / audience impact / owner ────┤
├ Decision Footer Strip: approve / reject / request / reroute ┤
├ Propagation Band: 审核通过后将同步到哪些 surface ────────────┤
└ Command Ribbon ─────────────────────────────────────────────┘
```

### 布局规则
- 列表第一列不应是标题，而应优先显露 `command-origin`。
- Decision Footer 应在多选/批量操作时始终可达。

---

## Screen 05 — Knowledge Object Workspace / Control Room

### 视线顺序
1. 这个对象当前吸附着哪些风险与 surface
2. 它当前处于什么生命周期与版本状态
3. audience variant 是否冲突
4. 再进入正文或结构编辑

### 推荐骨架
```text
┌ Command Horizon ─────────────────────────────────────────────┐
├ Situation Frame: 该对象在系统中的当前角色 ───────────────────┤
├ Spine Rail ─┬ Main Field Top: Object Gravity Panel ─────────┤
│ lifecycle   │                                               │
│ nav         ├ Main Field Bottom: content / structure editor │
├ Spine Rail ─┼ Right Dock: audience variant + evidence drawer│
├ Command Actions Strip: revise / split / restrict / escalate ┤
├ Propagation/Recovery Band: 该对象的 downstream alignment ───┤
└ Command Ribbon ─────────────────────────────────────────────┘
```

### 布局规则
- 内容编辑器不能占据首屏全部主权。
- `Object Gravity Panel` 必须先出现，提醒用户它不是普通文档后台。

---

## Screen 06 — Audience / Publish Command Center

### 视线顺序
1. 现在谁会看到它
2. 如果发令，会影响哪些 surface
3. 哪些 audience / channel 存在冲突
4. 发布后传播是否闭合

### 推荐骨架
```text
┌ Command Horizon ─────────────────────────────────────────────┐
├ Situation Frame: 当前开放边界与风险说明 ─────────────────────┤
├ Spine Rail ─┬ Main Field Left: Audience Scope Summary ──────┤
│ publish     ├ Main Field Right: Channel Gate Matrix         │
│ state       │                                               │
├ Consequence Dock: Blast Radius Preview + Conflict Warnings ┤
├ Propagation Theater: rollout / blocked / partial / mismatch │
└ Command Ribbon ─────────────────────────────────────────────┘
```

### 布局规则
- `Blast Radius Preview` 在发令前必须默认可见。
- 发布动作按钮不能远离 consequence 区域。

---

## Screen 07 — Source Integrity / Evidence Health

### 视线顺序
1. 哪些 source 失明了
2. 失明影响了哪些对象和 surface
3. 是修复还是先遏制外溢

### 推荐骨架
```text
┌ Command Horizon ─────────────────────────────────────────────┐
├ Situation Frame: 当前 source blindness 对治理的影响 ─────────┤
├ Main Field Top: Signal Loss Layer ──────────────────────────┤
├ Left: Source Health Table ─────┬ Right: Affected Objects    │
├ Left: Repair Actions ──────────┼ Right: Affected Surfaces   │
├ Recovery Band: 修复后可信度是否恢复 ─────────────────────────┤
└ Command Ribbon ─────────────────────────────────────────────┘
```

### 布局规则
- 错误不能只以“同步失败”文案出现。
- 必须立刻把 blindness 翻译为下游治理代价。

---

## Screen 08 — Copilot / Downstream Reality Check

### 视线顺序
1. 下游哪里仍在改写/拒绝/升级
2. 这些偏差是否集中在某 audience 或某对象
3. 是否需要回到控制塔再发令

### 推荐骨架
```text
┌ Command Horizon ─────────────────────────────────────────────┐
├ Situation Frame: 当前下游现实与上游治理的落差 ───────────────┤
├ Main Field Top: Reality Check Strip ────────────────────────┤
├ Left: Rewrite/Reject/Escalate Feed ─┬ Right: Mismatch View  │
├ Left: Upstream Object Links ────────┼ Right: Send Back Cmd  │
├ Recovery Band: 是否已经回归一致 ─────────────────────────────┤
└ Command Ribbon ─────────────────────────────────────────────┘
```

### 布局规则
- 这里不是客服桌面，而是“控制层对现实的回声监听面”。
- 用户应能一键把局部异常提升回系统级问题。

---

## Screen 09 — Propagation Ledger

### 视线顺序
1. 本轮命令从哪里发出
2. 穿过了哪些 stage
3. 卡在哪一层
4. 还需要追加哪条命令

### 推荐骨架
```text
┌ Command Horizon ─────────────────────────────────────────────┐
├ Situation Frame: 当前命令链为何仍未完全闭合 ─────────────────┤
├ Spine Rail ─┬ Main Field Top: Command Timeline ─────────────┤
│ cycle map   ├ Main Field Main: Propagation Theater          │
│ stage nav   │                                               │
├ Spine Rail ─┼ Right Dock: blocked stages + affected surface │
├ Follow-up Command Strip: reroute / republish / contain ─────┤
└ Command Ribbon ─────────────────────────────────────────────┘
```

### 布局规则
- 页面中心必须是传播本身，而不是日志表格。
- Blocked stages 应与 follow-up command 紧邻，缩短“看见问题 -> 再发令”的距离。

---

## Screen 10 — Recovery Window

### 视线顺序
1. 干预前后发生了什么
2. 是否真的减少 drift / rewrite / escalation
3. 问题是闭合还是暂压
4. 是否继续新一轮命令

### 推荐骨架
```text
┌ Command Horizon ─────────────────────────────────────────────┐
├ Situation Frame: 本轮命令的恢复判定 ─────────────────────────┤
├ Main Field Top: Before / After Alignment View ──────────────┤
├ Left: Drift/Rewrite/Escalation Delta ─┬ Right: Closure Judge│
├ Continue or Close Decision Area ────────────────────────────┤
└ Command Ribbon ─────────────────────────────────────────────┘
```

### 布局规则
- 这里不是“成功页”。
- 必须允许用户明确看到“看起来改善了，但仍未真正恢复”的中间态。

---

## 7. 跨页面视觉重心规则

### 规则 1：每一屏只有一个主战场
不要让页面同时有两个并列主区域争抢注意力。

### 规则 2：右侧 dock 服务于判断，不服务于堆信息
Consequence / Evidence / Blockers 都应帮助用户缩短决策路径。

### 规则 3：底部 band 承载系统回声
底部不是杂项区，而是“动作之后系统怎么回应我”的专属位置。

### 规则 4：持续对象要在用户脑中形成方位感
- 顶部：系统层
- 左侧：流程层
- 中央：判断/治理层
- 右侧：影响/证据层
- 底部：传播/恢复层

---

## 8. 使用规则
后续进入更细 screen design、prototype 或前端实现前，每个页面都要先确认：
1. 这个页的主战场到底在哪里？
2. Situation Frame 是否真的说明“为什么现在值得停留”？
3. 用户能否在一个视线回合内同时看到：局势、动作、后果？
4. Propagation 与 Recovery 是否在骨架中占到了明确位置？
5. 这页是否仍然把 support lead 的 control tower 视角放在主角位？

如果以上问题答不上来，这个 wireframe 还不够像 Cygnus。
