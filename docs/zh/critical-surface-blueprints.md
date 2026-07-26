# Support Brain for SaaS — Critical Surface Blueprints

## 1. 这份文档解决什么问题
`wireframe-architecture.md` 解决的是“页面大骨架”。

这份文档再往前推进一步，解决：
**最关键的几个页面，在真正开始画 low-fi 或写前端前，到底该如何被导演。**

它不是高保真视觉稿，而是关键屏幕蓝图：
- 用户在前 7 秒先看到什么
- 哪块区域是主战场
- 哪些组件必须同时同屏出现
- 哪些状态下页面结构要变形
- 哪些错误会把产品重新拉回普通 dashboard

---

## 2. Blueprint 使用规则

每个 blueprint 都包含：
1. 当前屏属于 command cycle 的哪一段
2. 用户此刻要完成什么判断
3. 首屏必须出现哪些组件
4. 默认视觉路径
5. 异常状态时布局如何变化
6. 哪些交互优先级不可被破坏

---

## 3. Blueprint 01 — Command Center / Morning Command Brief

### 所属阶段
**See movement → Frame what matters**

### 核心决策
今天哪些系统变化值得控制塔介入？

### 首屏必须同时出现
- Command Horizon
- Situation Frame
- Priority Stack
- Movement Grid
- Recovery Snapshot
- Command Ribbon

### 首屏蓝图
```text
┌──────────────────────────────────────────────────────────────┐
│ Command Horizon                                              │
├──────────────────────────────────────────────────────────────┤
│ Situation Frame                                              │
│ “今天最重要的 tension 是什么；不动作会怎样”                    │
├───────────────────────┬──────────────────────────────────────┤
│ Priority Stack        │ Movement Grid                        │
│ 1. 最高价值介入       │ queue/topic/audience/channel 变化     │
│ 2. 第二介入           │                                      │
│ 3. 第三介入           │                                      │
├───────────────────────┼──────────────────────────────────────┤
│ Command Queue Preview │ Recovery Snapshot                    │
├──────────────────────────────────────────────────────────────┤
│ Command Ribbon                                               │
└──────────────────────────────────────────────────────────────┘
```

### 前 7 秒视觉路径
1. Situation Frame 的一句话 tension
2. Priority Stack 第一项
3. Priority Stack 第二、第三项
4. Movement Grid 判断扩散面
5. Recovery Snapshot 看最近治理是否有效

### 异常状态变形

#### 当 `Leadership Intervention Overdue`
- Priority Stack 第一项拉大
- Movement Grid 降低视觉权重
- Situation Frame 直接写出不作为成本

#### 当 `Calm / Stable`
- Recovery Snapshot 上移更显眼
- Priority Stack 收缩成低噪声 briefing

#### 当 `Stale but Usable`
- Command Horizon 必须强调 freshness gap
- 所有“实时感”动画和自动刷新提示降低

### 绝对不能犯的错误
- 首屏像 BI 首页
- Priority Stack 与 Movement Grid 权重平均
- Recovery Snapshot 被压成一个小数字角标

---

## 4. Blueprint 02 — Queue / Topic Coordination Board

### 所属阶段
**Frame what matters → Issue command**

### 核心决策
这个风险区应该由谁接球、先动哪里、动成什么类型？

### 首屏必须同时出现
- Situation Frame
- Command Spine
- Decision Constellation
- Intervention Ladder
- Owner & Load Strip
- Consequence Lens
- Command Ribbon

### 首屏蓝图
```text
┌──────────────────────────────────────────────────────────────┐
│ Command Horizon                                              │
├──────────────────────────────────────────────────────────────┤
│ Situation Frame                                              │
│ “这条战线为什么值得你出手；不动作会扩大到哪里”                  │
├──────────────┬───────────────────────────────────────────────┤
│ Command Spine│ Decision Constellation                        │
│ phase        │ queue/topic/object/audience/source relations  │
│ current cmd  │                                               │
├──────────────┼───────────────────────────────────────────────┤
│ Owner/Load   │ Intervention Ladder                           │
├──────────────┴───────────────────────────────────────────────┤
│ Consequence Lens                                              │
├──────────────────────────────────────────────────────────────┤
│ Command Ribbon                                               │
└──────────────────────────────────────────────────────────────┘
```

### 前 7 秒视觉路径
1. Situation Frame 的风险战线定义
2. Decision Constellation 中最密集的风险聚集区
3. Owner & Load Strip 看责任和负载
4. Intervention Ladder 选动作类型
5. Consequence Lens 看 blast radius

### 异常状态变形

#### 当 `Ambiguous Ownership`
- Owner & Load Strip 升格为更显眼位置
- Intervention Ladder 中 route / escalate 强化

#### 当 `No Safe Route Yet`
- Consequence Lens 提前上移
- Ladder 中危险动作显式禁用并解释原因

#### 当 `Conflict Across Audiences`
- Constellation 内 audience 关系高亮
- 页面应更像“边界协调台”而不是任务派发台

### 绝对不能犯的错误
- 把 Constellation 做成装饰图
- 把动作区放到很远的角落
- 让责任、负载、后果都靠 hover 才看见

---

## 5. Blueprint 03 — Audience / Publish Command Center

### 所属阶段
**Issue command → Watch propagation**

### 核心决策
谁应该看到什么；我这次发令的 blast radius 是什么？

### 首屏必须同时出现
- Situation Frame
- Audience Scope Summary
- Channel Gate Matrix
- Blast Radius Preview
- Conflict Warnings
- Propagation Theater
- Command Ribbon

### 首屏蓝图
```text
┌──────────────────────────────────────────────────────────────┐
│ Command Horizon                                              │
├──────────────────────────────────────────────────────────────┤
│ Situation Frame                                              │
│ “当前 truth boundary 是什么；这次发令会放开还是收紧哪里”        │
├──────────────┬───────────────────────────────────────────────┤
│ Audience     │ Channel Gate Matrix                           │
│ Scope        │ channels × audiences × current gate state     │
├──────────────┴───────────────────────────────────────────────┤
│ Blast Radius Preview + Conflict Warnings                     │
├──────────────────────────────────────────────────────────────┤
│ Propagation Theater                                           │
├──────────────────────────────────────────────────────────────┤
│ Command Ribbon                                               │
└──────────────────────────────────────────────────────────────┘
```

### 前 7 秒视觉路径
1. Situation Frame 看本次边界动作
2. Audience Scope Summary 看 truth 对谁成立
3. Channel Gate Matrix 看当前闸门
4. Blast Radius Preview 看动作后果
5. Propagation Theater 看落地状态

### 异常状态变形

#### 当 `Conflict Risk`
- Blast Radius Preview 抢占更多空间
- 发令按钮与警告信息紧邻

#### 当 `Partial Rollout`
- Propagation Theater 拉大
- Matrix 中已落地/未落地必须并置展示

#### 当 `Split-Brain Publish`
- internal 与 external truth plane 必须被明确视觉分层

### 绝对不能犯的错误
- 页面像权限设置后台
- 用户先点 publish，后看后果
- internal/external 边界只靠小标签说明

---

## 6. Blueprint 04 — Propagation Ledger

### 所属阶段
**Watch propagation**

### 核心决策
命令卡在哪里？我要追加哪条命令？

### 首屏必须同时出现
- Situation Frame
- Command Spine
- Command Timeline
- Propagation Theater
- Blocked Stage Column
- Follow-up Command Strip
- Command Ribbon

### 首屏蓝图
```text
┌──────────────────────────────────────────────────────────────┐
│ Command Horizon                                              │
├──────────────────────────────────────────────────────────────┤
│ Situation Frame                                              │
│ “本轮命令为什么还没闭合；卡在第几层”                           │
├──────────────┬───────────────────────────────────────────────┤
│ Command Spine│ Command Timeline                              │
│ current cycle│                                               │
├──────────────┼───────────────────────────────────────────────┤
│ Blocked Stage│ Propagation Theater                           │
│ Column       │                                               │
├──────────────┴───────────────────────────────────────────────┤
│ Follow-up Command Strip                                      │
├──────────────────────────────────────────────────────────────┤
│ Command Ribbon                                               │
└──────────────────────────────────────────────────────────────┘
```

### 前 7 秒视觉路径
1. Situation Frame 识别未闭合原因
2. Timeline 看命令走到哪
3. Blocked Stage Column 看阻塞点
4. Propagation Theater 看影响面
5. Follow-up Command Strip 直接再发令

### 异常状态变形

#### 当 `Propagation Blocked`
- Blocked Stage Column 升格为主读点
- Follow-up Command Strip 固定可见

#### 当 `Secondary Conflict`
- Theater 内新增二次冲突标注
- Situation Frame 明确这是“命令副作用”，不是纯失败

### 绝对不能犯的错误
- 页面中心变成日志列表
- follow-up actions 远离 blocked stage
- 传播被写成“success / failed”二元结果

---

## 7. Blueprint 05 — Recovery Window

### 所属阶段
**Verify recovery**

### 核心决策
这轮命令值得关闭吗，还是只是暂时好了一点？

### 首屏必须同时出现
- Situation Frame
- Before / After Alignment View
- Drift Delta
- Rewrite Delta
- Escalation Delta
- Closure Judge
- Command Ribbon

### 首屏蓝图
```text
┌──────────────────────────────────────────────────────────────┐
│ Command Horizon                                              │
├──────────────────────────────────────────────────────────────┤
│ Situation Frame                                              │
│ “本轮命令后，系统到底恢复了多少”                               │
├──────────────────────────────────────────────────────────────┤
│ Before / After Alignment View                                │
├───────────────────────┬──────────────────────────────────────┤
│ Drift / Rewrite /     │ Closure Judge                        │
│ Escalation Deltas     │ close / continue / monitor           │
├──────────────────────────────────────────────────────────────┤
│ Command Ribbon                                               │
└──────────────────────────────────────────────────────────────┘
```

### 前 7 秒视觉路径
1. Situation Frame 读恢复判定
2. Before / After 看结构变化
3. Delta 区看哪里只是局部改善
4. Closure Judge 决定下一步

### 异常状态变形

#### 当 `Recovery Incomplete`
- Closure Judge 默认偏向 continue
- Delta 区强调 remaining mismatch

#### 当 `Recovery Confirmed`
- before/after 保持可读，但不再喧宾夺主
- close rationale 需要可回看

#### 当 `False Recovery`
- 页面必须明确阻断“看起来漂亮就关掉”的路径
- Situation Frame 直接指出尚未恢复的 truth plane

### 绝对不能犯的错误
- 把它做成庆功页
- 没有 continue 的明确路径
- 让用户只看总分，不看 residual mismatch

---

## 8. Blueprint 之间的连贯要求

这 5 个关键屏之间必须满足：
1. 用户从首页进入协调页时，能感觉自己仍在同一命令链
2. 用户从 publish 页进入 ledger 时，能看见同一条命令的延续
3. 用户从 ledger 进入 recovery 时，传播与恢复不能断开
4. 用户从 recovery 回首页时，系统应沉降为“最近一轮治理结果”，而不是把历史清空

---

## 9. 使用规则
后续如果进入 Figma、Excalidraw 或前端实现，优先按这 5 个 blueprint 落地。

因为这 5 屏共同决定了 Cygnus 最重要的一件事：
**它到底像不像一个 support leader 的 mission-control，而不是一个内容后台或 agent 工作台。**
