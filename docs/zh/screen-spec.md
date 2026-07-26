# Support Brain for SaaS — Screen Spec

## 1. 用途
这份文档把页面级 story map 进一步压实成逐屏规格。

它定义：
- 这块屏幕为什么存在
- 用户来到这里时在解决什么问题
- 页面应该由哪些区域组成
- 用户能发出哪些关键动作
- 系统需要回显哪些状态

## 2. 跨所有关键页面的统一屏幕骨架

### A. Situation Frame
位于页面首屏顶部，回答：
- 你为什么来到这里
- 当前最重要的 tension 是什么
- 如果什么都不做，会发生什么

### B. Command Spine
位于页面上方或侧边的持续导航/状态带，显示当前处于：
Observe / Frame / Route / Change / Propagate / Verify 的哪一段。

### C. Main Field
当前页面最主要的判断区或操作区。

### D. Consequence Lens
在用户发起关键动作前，显示 blast radius、受影响 audience、下游 surface、owner 变化。

### E. Propagation Theater
在动作后显示：
- 是否已传播
- 传播到哪里
- 哪里卡住
- 是否触发二次风险

## 3. Screen 01 — Command Center / Morning Command Brief

### 核心任务
把“今天支持系统里最值得领导介入的变化”组织成一场 briefing。

### 用户进入条件
- 登录后默认进入
- 处理完一次命令后返回全局
- release / incident / drift spike 后重新审视全局

### 用户核心问题
- 现在全局哪里在动？
- 今天我最该先介入哪三件事？

### 页面关键区域
1. **Briefing Header**
   - 一句话概括今日系统 tension
2. **Priority Stack**
   - 当前最高优先级的系统变化列表
3. **Movement Grid**
   - 队列、topic、audience、channel 的变化视图
4. **Command Queue Preview**
   - 当前已经在执行的关键命令
5. **Recovery Snapshot**
   - 最近命令是否让系统恢复一致

### 主要动作
- 打开某个高优先级变化
- 把某个变化标记为必须介入
- 进入 Queue / Topic Coordination
- 进入 Propagation Ledger 回看上次命令

### 关键状态
- Calm / Stable
- Emerging risk
- Multi-surface spread
- Incident-linked spike
- Leadership intervention overdue

### 必须避免的感觉
- BI 总览页
- 工单报表页
- 大量卡片无主次

## 4. Screen 02 — Queue / Topic Coordination Board

### 核心任务
让用户围绕一个队列/主题做“谁该动、先动哪里、怎么动”的判断。

### 用户核心问题
- 这个风险区到底影响谁？
- 我应该把它路由给谁？
- 是走 review、publish、source 修复，还是 escalation？

### 页面关键区域
1. **Situation Frame**
2. **Decision Constellation**
   - 展示 queue/topic 与 object/audience/source 的关系
3. **Intervention Ladder**
   - 呈现可选动作梯度：route / assign / escalate / review / publish constraint
4. **Owner & Load Strip**
   - 展示哪个团队已有负载，哪个团队更适合接球
5. **Consequence Lens**

### 主要动作
- route to reviewer/team
- escalate route
- push to urgent review
- open object control room
- pause / constrain external propagation

### 关键状态
- Single-zone issue
- Cross-audience issue
- Cross-team issue
- Ambiguous ownership
- No-safe-route-yet

### 创意要求
Decision Constellation 不应只是图，而要帮助用户真实做优先级与责任判断。

## 5. Screen 03 — Coverage & Drift Radar

### 核心任务
在问题彻底爆发前，让用户看见 drift 正在累积的地方。

### 用户核心问题
- 哪些地方正在变旧？
- 哪些 topic 看似还行，但已经开始偏了？

### 页面关键区域
1. **Drift Weather Layer**
2. **Coverage Gap Matrix**
3. **Audience Risk Strip**
4. **Source vs Object Attribution Panel**
5. **Suggested Intervention Entry**

### 主要动作
- 深入某一类 drift
- 打开对应 source / object / publish 面
- 发起 refresh / review / source fix 命令

### 必须避免的感觉
- 静态 coverage 报表
- KPI 运营台

## 6. Screen 04 — Knowledge Review Queue

### 核心任务
将 review 作为命令之后的治理执行队列，而不是草稿堆。

### 用户核心问题
- 哪些草稿现在最值得被处理？
- 哪些草稿实际上是系统级风险的应答？

### 页面关键区域
1. **Command-origin Tag**
   - 每条任务来自哪条上游命令
2. **Priority Re-stack Lane**
   - 命令改变后的审阅顺序
3. **Evidence Strength Column**
4. **Audience Impact Column**
5. **Decision Footer**
   - approve / reject / request evidence / reroute

### 主要动作
- 批量改审阅顺序
- 批量分派 owner
- 审核单条草稿
- 回到上游风险背景

### 关键状态
- Needs decision now
- Evidence incomplete
- Waiting on owner
- Safe to defer

## 7. Screen 05 — Knowledge Object Workspace / Control Room

### 核心任务
让一个对象先作为“系统节点”被理解，再作为内容被编辑。

### 用户核心问题
- 这个对象现在影响哪些队列、audience、surface？
- 我是要改内容，改 audience，还是改可见性？

### 页面关键区域
1. **Object Gravity Panel**
2. **Version / State Rail**
3. **Audience Variant Pane**
4. **Source Evidence Drawer**
5. **Command Actions Area**
   - revise / split / restrict / escalate / send to review

### 主要动作
- 修改对象
- 调整 audience variant
- 改变 external visibility
- 发起紧急审阅
- 查看传播影响

### 必须避免的感觉
- CMS 编辑页
- 文档后台

## 8. Screen 06 — Audience / Publish Command Center

### 核心任务
让 publish 变成“有范围意识的发令动作”。

### 用户核心问题
- 谁应该看到这个？
- 如果我现在开放/收紧，会波及哪里？

### 页面关键区域
1. **Audience Scope Summary**
2. **Channel Gate Matrix**
3. **Blast Radius Preview**
4. **Conflict Warnings**
5. **Propagation Theater**

### 主要动作
- publish
- unpublish
- restrict audience
- split variant
- hold propagation

### 关键状态
- Internal only
- External ready
- Conflict risk
- Propagation blocked
- Partial rollout

## 9. Screen 07 — Source Integrity / Evidence Health

### 核心任务
把 source 健康度翻译成 command 风险，而不是技术指标。

### 用户核心问题
- 系统是不是因为 source 失效而看不清了？
- 我现在应该先修 source，还是先控下游影响？

### 页面关键区域
1. **Signal Loss Layer**
2. **Source Health Table**
3. **Affected Objects List**
4. **Affected Surfaces Preview**
5. **Repair vs Contain Actions**

### 主要动作
- trigger resync / repair
- contain downstream publish
- escalate to source owner
- mark evidence confidence low

## 10. Screen 08 — Copilot / Downstream Reality Check

### 核心任务
验证控制层命令是否改变了一线真实行为。

### 用户核心问题
- 一线还在改写吗？
- 哪些 surface 仍然没有同步？

### 页面关键区域
1. **Reality Check Strip**
2. **Rewrite / Reject / Escalate Feed**
3. **Mismatch by Audience View**
4. **Upstream Object Links**
5. **Send Back to Command**

### 主要动作
- 标记某类反馈需要上升为系统级问题
- 回到对象 / 队列 / publish 面
- 打开 Recovery Window

## 11. Screen 09 — Propagation Ledger

### 核心任务
让命令传播成为一个可追踪、可二次介入的页面，而不是日志。

### 用户核心问题
- 我上次发出的命令走到了哪？
- 哪一层卡住了？
- 我还要追加什么动作？

### 页面关键区域
1. **Command Timeline**
2. **Propagation Theater**
3. **Blocked Stage Column**
4. **Affected Surface Checklist**
5. **Follow-up Command Actions**

### 创意要求
页面要像“看一条命令穿过系统”，而不是看 audit trail。

## 12. Screen 10 — Recovery Window

### 核心任务
帮助用户判断一次命令是否真的让系统更一致。

### 用户核心问题
- 这次干预有没有值回成本？
- 问题是已经闭合，还是只是暂时压住？

### 页面关键区域
1. **Before / After Alignment View**
2. **Rewrite Delta**
3. **Drift Delta**
4. **Escalation Delta**
5. **Continue or Close Decision Area**

### 主要动作
- 继续发命令
- 标记本轮闭合
- 转入长期监控

## 13. 全局交互快捷层（可创造性发挥）
建议加入一个横跨多页的全局轻量 command 层：

### Command Ribbon
它不是传统 command palette，而是一个“当前系统指挥上下文条”。

它可以显示：
- 当前最活跃命令
- 当前最危险的未闭合问题
- 当前需要你重新判断的 route / publish / source 冲突

它的意义是让用户无论在哪一页，都仍然记得自己处在同一条指挥链上。

## 14. Screen Spec 的使用规则
后续进入 wireframe 或实现前，每一屏都必须确认：
- 它是否属于 Command Spine 某一段
- 它是否帮助用户发出明确的观察/协调/治理动作
- 它是否回显传播与恢复，而不是只回显动作成功
- 它是否仍然把 control tower 维持为主角
