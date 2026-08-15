# Support Brain for SaaS — Command Flows

## 1. 这份文档解决什么问题
前面的文档说明了页面、骨架和状态。

这份文档定义：
**当真实支持风险发生时，用户在 Cygnus 中如何走完一条完整 command cycle。**

这里不讲实现细节，只讲：
- 用户先看到什么
- 为什么决定动作
- 系统如何接住这个动作
- 动作如何传播
- 什么情况下需要继续下一轮命令

---

## 2. Command Flow 的统一语法

每条 flow 都使用同一套节奏：
1. **Signal** — 哪个异常把用户带进系统
2. **Frame** — 用户如何理解这不是局部噪声
3. **Command** — 用户下达哪类治理命令
4. **Propagation** — 系统如何回显这条命令穿过哪些层
5. **Recovery** — 用户如何判断是否闭环
6. **Next Command or Close** — 是否继续下一轮

---

## 3. Flow 01 — Release Drift Recovery

### 场景
一个新版本上线后，帮助中心更新了部分内容，但内部 SOP、copilot 推荐和部分 enterprise variant 没有同步。

### 用户起点
用户在 `Command Center` 看到：
- release 相关 topic 短时间内 escalation 上升
- Coverage & Drift 出现 freshness 前线
- Copilot rewrite 开始集中出现在某一版本群体

### 用户行为 + 系统预期行为

#### Step 1 — 看见 drift front
- 用户打开 `Coverage & Drift Radar`
- 系统把 drift 显示成“版本迁移带”而不是孤立告警
- 系统同时指出受影响 audience：enterprise + legacy version

#### Step 2 — 判断问题属于对象还是传播
- 用户查看 `Source vs Object Attribution Panel`
- 系统明确：release notes 已进入，部分 Answer Card 已更新，但 publish propagation 不完整
- 用户因此不会误判成“文档根本没写”

#### Step 3 — 进入协调页
- 用户跳到 `Queue / Topic Coordination Board`
- 系统用 Decision Constellation 展示：同一问题牵连对象、queue、audience、copilot surface
- 用户看到这是 cross-surface 问题，不是单对象编辑问题

#### Step 4 — 发出第一条命令
- 用户选择：
  - urgent review enterprise variant
  - constrain external rollout for legacy version
  - route a knowledge owner to check affected cards
- 系统在 Consequence Lens 中提前显示：哪些用户会继续看到旧答案，哪些 surface 会被暂时收紧

#### Step 5 — 看传播
- 用户进入 `Propagation Ledger`
- 系统把命令拆成：review -> publish gate -> copilot sync -> external answer surface
- 系统明确哪一段已经通过，哪一段仍 blocked

#### Step 6 — 看恢复
- 用户打开 `Recovery Window`
- 系统对比命令前后：
  - rewrite 是否下降
  - escalations 是否减弱
  - drift 是否仍压在 legacy variant 上
- 如果 enterprise 已恢复但 legacy 仍偏移，系统明确标注 `Recovery Incomplete`

#### Step 7 — 决定是否继续
- 用户追加第二轮命令：
  - 更明确地拆分 variant
  - 对某个 audience 继续保持 rollout hold
- 或在恢复足够后关闭本轮命令

### Flow 的设计重点
- 这个流程必须让用户感受到：问题不是“缺一篇文档”，而是“一个 release 让多个 truth plane 脱节”。

---

## 4. Flow 02 — Incident Spread Containment

### 场景
某功能出现 incident，状态页已更新，但知识对象、copilot 建议、外部帮助中心中的旧 workaround 仍在传播。

### 用户起点
- `Command Center` 顶部出现 incident-linked spike
- `Reality Check Strip` 显示 rewrite 与升级同时攀升

### 用户行为 + 系统预期行为

#### Step 1 — 进入 war room 视角
- 用户从首页进入 `Queue / Topic Coordination Board`
- 系统的 Situation Frame 明确：如果不动作，将继续扩大错误指导

#### Step 2 — 判断 containment 比修正文更优先
- 用户在 Intervention Ladder 中看到多种动作
- 系统优先突出：
  - hold external propagation
  - mark known issue banner
  - route urgent review
- 系统不鼓励先做长编辑，再等传播

#### Step 3 — 进入 Publish Command Center
- 用户选择临时限制外部答案
- 系统在 Blast Radius Preview 中显示：
  - 哪些 external surfaces 将被切断
  - 哪些 internal surfaces 保留供人工客服使用

#### Step 4 — 发布遏制命令
- 用户确认 containment
- 系统不只提示成功，而是在 Propagation Theater 中显示：
  - status page aware
  - copilot partially aware
  - external FAQ still cached in one channel

#### Step 5 — 检查 source 与对象是否需同步修复
- 用户打开 `Source Integrity / Evidence Health`
- 系统指出 incident note 进入正常，但旧对象尚未 supersede
- 用户再发 review / supersede 命令

#### Step 6 — 验证是否止血
- 用户进入 `Recovery Window`
- 系统对比 containment 前后 escalation 和 wrong-answer surface
- 若 escalation 降了但 cached external channel 仍错误，系统保持 cycle open

### Flow 的设计重点
- 这个流程要体现 Cygnus 的指挥感：
  **先止血，再校正，再恢复。**

---

## 5. Flow 03 — Policy Conflict Across Audiences

### 场景
退款或权限政策对 enterprise、self-serve、EU 用户存在差异，但多个 Answer Card 被错误合并为同一答案。

### 用户起点
- `Copilot / Reality Check` 出现某类回答被人工频繁重写
- `Coverage & Drift` 出现 audience mismatch

### 用户行为 + 系统预期行为

#### Step 1 — 先确认不是个案
- 用户打开 `Reality Check Strip`
- 系统按 audience 分层展示 rewrite cluster
- 用户发现问题集中在 EU + enterprise

#### Step 2 — 查看对象重力
- 用户跳到 `Knowledge Object Workspace`
- 系统的 Object Gravity Panel 显示：一个对象正在覆盖多个政策域
- 用户意识到问题不在措辞，而在 variant 结构错误

#### Step 3 — 打开 Audience / Publish Command Center
- 用户查看当前 gate matrix
- 系统清楚展示：internal copilot 和 external help center 共享了错误 truth plane

#### Step 4 — 发出拆分命令
- 用户选择 `split variant`
- 系统在 Consequence Lens 中显示：
  - 哪些 audience 将获得新变体
  - 哪些 channel 暂时进入 hold
  - 哪些旧引用会成为 superseded link

#### Step 5 — 审核与传播
- 用户把新 variant 路由到 `Review Queue`
- 系统在 queue 中保持 `command-origin` 上下文
- 通过后，Propagation Theater 展示 variant 逐层进入 copilot 与 external surfaces

#### Step 6 — 恢复判断
- 用户在 `Recovery Window` 看见：
  - EU rewrite 大幅下降
  - enterprise escalation 下降
  - self-serve 保持稳定
- 系统因此支持闭环

### Flow 的设计重点
- 这个流程必须让 audience-aware 成为产品英雄能力，而不是筛选器。

---

## 6. Flow 04 — Copilot Rewrite Spike → Governance Intervention

### 场景
人工客服在 copilot 侧频繁重写 AI 建议，但这些改写分散在多个队列中，尚未形成单个显而易见的 bug。

### 用户起点
- `Command Center` 上出现“rewrite acceleration”
- `Copilot / Downstream Reality Check` 出现多队列 rewrite cluster

### 用户行为 + 系统预期行为

#### Step 1 — 从噪声变成模式
- 用户进入 `Copilot / Downstream Reality Check`
- 系统把离散改写聚成 cluster，并按 topic、audience、version 重新整理

#### Step 2 — 提升为控制塔问题
- 用户点击 `mark as systemic`
- 系统把这个 cluster 拉升为新的 command candidate，而不是留在一线反馈流里

#### Step 3 — 进入协调页
- 用户跳到 `Queue / Topic Coordination Board`
- 系统展示：多个 queue 虽然案型不同，但共用同一组对象和变体

#### Step 4 — 发出治理命令
- 用户选择：
  - open review for impacted Answer Cards
  - lower evidence confidence on one suspect source
  - route to knowledge manager

#### Step 5 — 查看回响
- `Propagation Ledger` 展示：
  - review 已开始
  - source confidence 已降级
  - copilot 还在使用上一个 published variant

#### Step 6 — 判断是否真实改变一线行为
- `Recovery Window` 对比 rewrite delta
- 若 rewrite 降低但人工仍在关键高价值队列改写，系统不允许轻率闭合

### Flow 的设计重点
- 这个流程必须证明：
  **frontline rewrite 在 Cygnus 里不是杂音，而是治理雷达。**

---

## 7. Flow 05 — Blocked Propagation → Second Command Cycle

### 场景
一条关键发布命令在 review 完成后，成功进入 internal copilot，但 external surface 因 channel rule 或 audience gate 冲突而未同步。

### 用户起点
- Command Ribbon 显示 unresolved command shadow
- `Propagation Ledger` 标注 partial rollout

### 用户行为 + 系统预期行为

#### Step 1 — 回到命令现场
- 用户从任意页点击 Command Ribbon
- 系统将用户带回 `Propagation Ledger` 当前 blocked stage

#### Step 2 — 识别阻塞位置
- 系统明确指出：
  - review 已通过
  - publish rule 冲突
  - external channel gate 卡住
- 用户不需要跨多个页面拼图

#### Step 3 — 打开 Publish Command Center
- 用户检查 gate matrix
- 系统显示 conflict 是 audience overlap，而不是技术失败

#### Step 4 — 发起第二轮命令
- 用户选择：
  - restrict one audience temporarily
  - republish to safe channels
  - keep internal variant live

#### Step 5 — 重新观察传播
- 系统在 Propagation Theater 中把第一次失败与第二次修正并列呈现
- 用户看到“新命令是否真正越过旧阻塞”

#### Step 6 — 再做恢复判断
- 如果外部已同步，但 rewrite 仍未下降，Recovery Window 保持 open
- 如果外部同步且下游 mismatch 也下降，则允许 close

### Flow 的设计重点
- 这里必须体现 Cygnus 区别于“按钮成功提示”：
  **传播失败本身也是一个新的可指挥对象。**

---

## 8. Flow 06 — Recovery Verification and Close

### 场景
若干轮命令后，系统看上去已经平静，但用户需要判断是“真的恢复”还是“只是暂时没有更多信号”。

### 用户起点
- Command Ribbon 中某条 command cycle 处于 almost-closed
- Recovery Snapshot 变好，但仍存在少量 residual mismatch

### 用户行为 + 系统预期行为

#### Step 1 — 进入 Recovery Window
- 用户打开当前 cycle 的 Recovery Window
- 系统默认呈现 before/after，对比：
  - drift delta
  - rewrite delta
  - escalation delta
  - publish conflict delta

#### Step 2 — 查看 residual risk
- 用户看到某个低量级 audience 仍有尾部 mismatch
- 系统必须区分：
  - 可接受 residual
  - 不可接受 residual

#### Step 3 — 做 closure judgment
- 用户根据页面中的 Closure Judge 决定：
  - close and monitor
  - continue with lightweight follow-up
- 系统记录 closure rationale，而不是只记“已完成”

#### Step 4 — 回到首页
- 用户回到 `Command Center`
- 系统把本轮命令沉降为 recent recovered cycle
- Recovery Snapshot 不只是数字下降，而是形成可回看的治理案例

### Flow 的设计重点
- 关闭动作必须有“恢复判据”，而不是疲劳式结束。

---

## 9. 使用规则
后续若扩展更多 flow，每条 flow 都要确认：
1. 触发它的 signal 是系统级，不是一线桌面级噪声
2. 中间至少有一次明确的 command decision
3. 系统必须回显 propagation，而不是只回显 success
4. 结尾必须回答“恢复了吗”，而不是只回答“完成了吗”

如果一个 flow 只是在描述任务处理，而不是支持控制塔如何理解、发令、传播、恢复，它就还不够像 Cygnus。
