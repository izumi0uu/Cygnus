# Support Brain for SaaS — 页面级 Story Map

## 1. 这份文档解决什么问题
前面的文档已经定义了：
- 产品是谁的控制层
- 视觉应该是什么气质
- 交互应该是什么姿态

这份文档继续往下走一步，定义：
**整套页面如何围绕一个“指挥支持系统”的叙事被组织起来。**

它不只是页面列表，而是：
- 用户先看什么
- 接着判断什么
- 在哪里下达协调动作
- 如何看到动作传播
- 如何判断系统是否重新同步

## 2. 北极星创意骨架：Command Spine
为了让产品不沦为“多个页面的集合”，整套体验需要一个跨页面持续存在的创意主骨架：

## Command Spine
Command Spine 不是某一个组件名，而是一套贯穿多页面的体验机制：

1. **Situation Frame**
   - 每个关键页面顶部都要回答：
     - 为什么我现在会来到这里？
     - 这件事为什么重要？
     - 它正在影响谁？

2. **Command Spine**
   - 每个关键流程都要让用户感觉自己处于一条连续的指挥链上：
     - Observe
     - Frame
     - Route
     - Change
     - Propagate
     - Verify

3. **Propagation Theater**
   - 每次协调动作之后，系统都不应该只回“成功”。
   - 它要让用户看见：
     - 哪些对象变了
     - 哪些队列被改写了优先级
     - 哪些 surface 已同步
     - 哪些地方仍未闭合

4. **Recovery Window**
   - 用户需要能够回看“我刚才那次动作，到底有没有让系统更一致”。
   - 这不是 activity log，而是 alignment 回显。

## 3. 页面 Story 的总路径
整套体验应被组织成五个连续阶段：

1. **See movement**
2. **Frame what matters**
3. **Issue command**
4. **Watch propagation**
5. **Verify recovery**

这五个阶段不是 wizard，而是整个产品中反复出现的同一节奏。

## 4. Page Story Map 总览

| 阶段 | 用户核心问题 | 主页面族 | 页面输出 | 创意特征 |
|---|---|---|---|---|
| See movement | 现在整个支持系统哪里在动？ | Command Center | 值得介入的系统变化 | Morning Command Brief |
| Frame what matters | 为什么这件事值得我动？ | Queue / Topic Coordination、Coverage & Drift | 风险范围与协调背景 | Situation Frame |
| Issue command | 我现在应该改变谁、改哪里？ | Review Queue、Object Workspace、Publish Control | 路由 / 审阅 / 发布 / 升级命令 | Command Spine |
| Watch propagation | 我的动作传播到了哪里？ | Propagation Ledger、Downstream Feedback | 传播状态与剩余缺口 | Propagation Theater |
| Verify recovery | 系统真的变得更一致了吗？ | Recovery / Feedback surfaces | 对齐程度变化 | Recovery Window |

## 5. 页面族与叙事角色

### A. Command Center / Morning Command Brief
**叙事角色：** 开场镜头

这是完整体验的入口。
它不应该像 dashboard 首页，而应该像一个“今天支持系统发生了什么”的 command briefing。

#### 用户要完成什么
- 看见哪些队列、topic、audience、channel 正在变化
- 判断今天哪几件事最值得指挥层介入
- 选择一个进入协调链

#### 系统要做到什么
- 把最重要的变化先呈现
- 不让用户先陷入对象细节
- 用一句话说明每个变化的 operational consequence

#### 创意发挥点
**Morning Command Brief**
- 系统像在给 support lead 做一场晨间战情 briefing
- 不是汇报所有数据，而是汇报“哪三件事值得你现在出手”

### B. Queue / Topic Coordination Board
**叙事角色：** 战区判断台

这里不是“队列列表”。
它是用户理解一个风险区为什么值得动、该由谁动、怎么动的地方。

#### 用户要完成什么
- 对比不同 topic / queue / audience 的影响
- 判断哪条线先处理
- 选择 route、assign、escalate 还是发起 review

#### 系统要做到什么
- 把来源、对象、队列、audience 的关系编排出来
- 让“谁该接球”成为显式信息
- 让用户看到队列之间不是平行事件，而是相互竞争指挥注意力

#### 创意发挥点
**Decision Constellation**
- 将队列、topic、audience、object 的关系做成“决策星图”感
- 不是炫技图，而是让用户感知哪里正在形成风险聚集

### C. Coverage & Drift Radar
**叙事角色：** 远程预警层

它的作用不是展示 KPI，而是帮助用户更早发现“今天还没爆，但很快会爆”的知识漂移。

#### 用户要完成什么
- 看见 coverage 缺口和 freshness 漂移
- 判断这是局部内容问题、版本问题，还是传播问题
- 决定该从 source、object 还是 publish 侧介入

#### 系统要做到什么
- 让 drift 比静态 coverage 更先被感知
- 呈现 risk accumulation，而不是孤立告警

#### 创意发挥点
**Drift Weather Layer**
- 像天气图层一样，呈现风险不是点状，而是“正在压过来”的趋势

### D. Knowledge Review Queue
**叙事角色：** 协调后的治理执行面

这里要呈现的不是“有一堆草稿”，而是“哪些治理动作正在等待被组织推进”。

#### 用户要完成什么
- 决定哪批草稿先审
- 判断哪些需要补证据、哪些该紧急通过、哪些该转交
- 处理因为上游命令而改变顺序的任务

#### 系统要做到什么
- 把 review queue 作为 command 后的执行队列，而不是独立列表
- 让用户清楚知道这批任务是为了解决哪个系统级问题

#### 创意发挥点
**Priority Re-stack**
- 当上游下达命令后，review queue 的栈顺序会被“重排”并可视化回显

### E. Knowledge Object Workspace / Control Room
**叙事角色：** 单对象控制室

这里不是传统编辑器页。
它应让用户先理解“这个对象当前在整个系统里扮演什么角色”。

#### 用户要完成什么
- 理解当前对象状态、版本、证据、audience 和传播面
- 决定修改、拆分 audience、限制发布，或进入更深治理

#### 系统要做到什么
- 让对象的系统影响先于正文显示
- 让对象像一个有 operational gravity 的节点，而不是一篇文档

#### 创意发挥点
**Object Gravity Panel**
- 强调该对象当前吸附着哪些 queue、audience、surface 和风险

### F. Audience / Publish Command Center
**叙事角色：** 传播闸门

这是控制“谁被允许看到什么”的页面族。
它应该像 airlock / gate，而不是普通设置页。

#### 用户要完成什么
- 判断某个对象该对谁开放、对谁关闭、对谁变体化
- 在动作前理解 blast radius
- 在动作后看到传播是否成功

#### 系统要做到什么
- 在发布动作前先显示 downstream consequence
- 让 internal / external 的差异具有强烈操作语义

#### 创意发挥点
**Blast Radius Preview**
- 改动不是表单提交，而像在执行一次有范围后果的“发令”

### G. Source Integrity / Evidence Health
**叙事角色：** 基座可信度面

这不是后台运维页，而是 support command 的可信度层。

#### 用户要完成什么
- 判断 source 问题是否正在污染知识系统
- 决定先修 source 还是先修 object

#### 系统要做到什么
- 把 source failure 翻译为治理影响
- 呈现“这不是同步错误，而是 command blindness”

#### 创意发挥点
**Signal Loss Layer**
- 某些来源失效时，不只是报错，而是让用户感到系统部分“失明”

### H. Copilot / Downstream Reality Check
**叙事角色：** 下游现实回报面

这是验证 control tower 是否真的改变了一线行为的地方。

#### 用户要完成什么
- 看哪些建议仍被重写、拒绝、升级
- 看哪些下游面仍在偏离已治理知识
- 判断系统是否恢复同步

#### 系统要做到什么
- 把 frontline 改写看成治理反馈，而不是一线噪声
- 让“控制层命令是否生效”变得清晰

#### 创意发挥点
**Reality Check Strip**
- 展示“上游命令”与“下游真实行为”之间的落差

### I. Propagation Ledger
**叙事角色：** 命令传播台

这是本次设计里新增的创造性页面族。

它不只是历史记录，而是：
- 每一条重要 command 传播到哪里
- 哪些地方已同步
- 哪些地方卡住了
- 哪些地方产生了二次冲突

#### 用户要完成什么
- 回看某次关键动作是否真正到达各 surface
- 识别传播链中断点
- 再次追加协调动作

#### 系统要做到什么
- 让传播成为一等信息
- 让“命令已发出但系统未对齐”成为可见状态

#### 创意发挥点
**Propagation Theater**
- 用类似 stage cue 的感觉呈现命令如何逐层落入 review、publish、copilot、external surfaces

### J. Recovery Window
**叙事角色：** 对齐恢复窗

这是另一个新增的创造性页面族。

它不是 KPI 总结，而是让用户回答：
**“我做的事到底让系统恢复了吗？”**

#### 用户要完成什么
- 对比干预前后
- 看 rewrite、drift、coverage、escalation、publish conflict 的变化
- 决定是否结束本轮命令，或继续发出新动作

#### 系统要做到什么
- 用恢复程度而不是完成状态组织信息
- 让用户判断“继续指挥”还是“本轮闭合”

#### 创意发挥点
**Before / After Alignment View**
- 不是漂亮的报告，而是可操作的恢复判定

## 6. 跨页面持续存在的创意对象
以下不是某一页专属，而是贯穿多个页面的体验对象：

### 1. Situation Frame
一句话说明当前页面为什么值得你停留。

### 2. Command Spine
显示你当前处在 Observe / Frame / Route / Change / Propagate / Verify 的哪一段。

### 3. Consequence Lens
任何关键动作前，先看影响范围。

### 4. Propagation Theater
任何关键动作后，先看传播结果。

### 5. Recovery Window
任何一轮干预结束后，先看系统恢复程度。

## 7. 页面 Story Map 的使用方法
后续如果进入 wireframe / screen design，每个页面都应先回答：
1. 它属于五阶段中的哪一段？
2. 它是否和 Command Spine 的连续体验相连？
3. 它让用户发出的是观察、协调还是治理动作？
4. 它是否让传播结果和恢复程度可见？

如果答案是否定的，这个页面就还不够像 Cygnus。