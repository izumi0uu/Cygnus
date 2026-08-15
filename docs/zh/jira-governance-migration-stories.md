# Cygnus — Jira 治理迁移 Story Pack

## 1. 文档用途
这份文档用于把 **CYG Jira 看板**里的“迁移 stories”写成一套可直接落板的产品故事包。

它服务的是：
- 产品叙事对齐
- 设计推进对齐
- 后续执行排期对齐

它**不服务于**：
- backend / schema / worker 迁移拆解
- agent runtime backlog
- generic PM board 搭建

这组 story 的核心命题必须始终保持：
**Cygnus 正在从 Arkon 的知识基座之上，长成一个 support knowledge governance center。**

## 2. 使用边界
### 2.1 这组 story 在讲什么迁移
它讲的是：
- 从“知识编译能力存在”
- 迁移到“support lead 真正获得治理控制力”

因此每条 story 都应描述：
- 谁获得了新的判断位置
- 谁获得了新的命令权力
- 哪种风险第一次变得可见
- 哪个错误传播点可以被更早阻断

### 2.2 这组 story 明确不写成什么
不要把它写成：
- 技术迁移层级票
- AI agent workflow 票
- 页面开发 checklist
- 更漂亮的流程图可视化

### 2.3 Jira 使用建议
- 先创建 Epic，再创建 Story。
- Epic 表示一条 **治理闭环迁移线**。
- Story 表示一个 **用户可感知的治理控制力变化**。
- 只有当一条 Story 能讲清“新的控制力”时，它才应该存在。

### 2.4 建议标签
- `migration`
- `governance-loop`
- `review-publish`
- `support-brain`
- `cygnus`

## 3. 每条 Story 的检验规则
任何一条合格的迁移 story，都必须能回答：
1. **谁**获得了新的治理位置？
2. **什么风险**第一次被提早看见？
3. **什么命令**可以被发出，而不只是被观察？
4. **什么传播后果**被明确显示出来？
5. 为什么这不是一次“流程展示”，而是一次“控制力迁移”？

如果答不上来，这条票应被删掉或重写。

## 4. Epic 总览与推荐顺序

| 顺序 | Epic 标题 | 迁移命题 | 主要用户 | 视觉北极星 | 交互北极星 |
|---|---|---|---|---|---|
| E1 | Governance Loop Migration — Review Becomes Command Brief | 审阅不再是草稿列表，而是治理指挥的第一入口 | Support Lead / Support Ops / Knowledge Manager | Situation Frame + Priority Re-stack | 先判断、后审阅 |
| E2 | Governance Loop Migration — Publish Becomes Blast-Radius Control | 发布不再是通过动作，而是带范围意识的外溢控制 | Support Ops / Knowledge Manager | Blast Radius Preview + Propagation Theater | 先看后果、再发命令 |
| E3 | Governance Loop Migration — Ticket & Drift Become Review Pressure | ticket、drift、source 信号不再只是数据，而是审阅压力来源 | Support Ops / Escalation Lead | Drift Weather Layer + Signal Loss Layer | 从风险信号直接进入治理 |
| E4 | Governance Loop Migration — Propagation Becomes Recovery Proof | 治理动作不止要执行，还要证明系统是否重新同步 | Head of Support / Support Lead | Recovery Window + Reality Check | 先验证恢复，再决定下一步 |

---

## 5. Epic E1 — Review Becomes Command Brief

### Epic 定义
- **Issue type:** Epic
- **Epic title:** Governance Loop Migration — Review Becomes Command Brief
- **Epic summary:** 把审阅从“草稿处理流程”迁移成“支持治理指挥入口”，让 support lead 在进入对象细节前就能看见最值得介入的风险、责任空缺与队列后果。
- **为什么这个 Epic 必须先做：** 如果 Review 还只是内容审批台，Cygnus 就会退化成文档后台，而不是 mission control。
- **视觉北极星：** Morning Command Brief、Situation Frame、Priority Re-stack
- **交互北极星：** 先看系统 tension，再决定审阅顺序与协调动作

### Story E1-S1 — 审阅入口先呈现“今天最值得介入的治理风险”
- **Primary user:** Support Lead / Support Ops
- **User story:** 作为支持负责人，我希望一进入 Review 面就先看到今天最值得介入的治理风险，而不是一排静态草稿，这样我能先决定组织应该把注意力放在哪里。
- **用户行为：** 进入 Review 面后先扫描今日 tension，识别哪几个 draft / topic / audience 冲突最值得先动。
- **系统预期行为：** 系统先按治理风险、影响范围、错误传播速度和 owner 缺口重排入口，而不是按创建时间展示草稿。
- **视觉效果：** 首屏像一场晨间 command brief；顶部是 Situation Frame，中段是按风险重排的 Priority Stack，而不是普通 table。
- **交互效果：** 用户可以直接从高优项跳入 route、assign、urgent review，而不必先打开对象全文。
- **为什么这条迁移重要：** 它把用户的第一判断位置从“读草稿”迁移到“指挥优先级”。
- **Acceptance signals:**
  - 审阅入口首屏默认展示系统级风险排序，而不是最近草稿列表。
  - 每个高优项都同时显示受影响 audience、下游 surface、当前 owner 状态。
  - 用户可以从该视图直接发起协调动作，而不是只能进入详情页。
- **Critical boundary:** 这不是审阅页皮肤升级，而是审阅主语从“内容”变成“治理风险”。

### Story E1-S2 — 每条审阅项在内容之前先解释“为什么现在重要”
- **Primary user:** Knowledge Manager / Support Ops
- **User story:** 作为知识负责人，我希望每条审阅项在正文之前先说明它为什么现在重要，这样我不会把系统级风险当成普通内容修订处理掉。
- **用户行为：** 在打开某条 draft 前，先判断它关联的是 release、incident、policy 冲突，还是 audience mismatch。
- **系统预期行为：** 系统先展示该项的 risk frame、证据强度、影响 audience、下游污染面，再进入正文差异。
- **视觉效果：** 每条审阅项像一个待处理的治理包，顶部带有 Command-origin Tag、Evidence Strength、Audience Impact，而不是只有标题和更新时间。
- **交互效果：** 用户可以在不离开队列的情况下完成“理解重要性 → 进入细看 → 回到全局排序”的连续动作。
- **为什么这条迁移重要：** 它防止 Review 再次坍缩成“逐条审批 AI 建议”。
- **Acceptance signals:**
  - 打开审阅项后，风险背景先于正文 diff 呈现。
  - 用户能直接看到这条变更在解决哪类系统 tension。
  - 用户不需要依赖外部上下文，也能理解为什么此项优先级高。

### Story E1-S3 — 审阅顺序可以被重排、转交、升级，而不丢失上游指挥链
- **Primary user:** Support Lead / Knowledge Manager
- **User story:** 作为支持负责人，我希望审阅任务可以根据新的系统压力被重排、转交或升级，同时保留它来自哪次指挥动作的上下文，这样执行层不会失去为什么要先做这件事的原因。
- **用户行为：** 面对多个待审项时，重新定义谁先做、谁接手、谁需要紧急介入。
- **系统预期行为：** 系统允许批量 re-stack、reroute、urgent review，并保留每条任务与上游风险事件之间的关联。
- **视觉效果：** 队列里应有明显的 Priority Re-stack Lane 与 Command-origin Tag，让“顺序被重新定义”成为可见动作。
- **交互效果：** 用户改变顺序后，系统立即回显受影响 owner、执行压力和下游等待关系。
- **为什么这条迁移重要：** 没有这条 story，Review 仍是静态工作队列，而不是被 command 驱动的治理执行面。
- **Acceptance signals:**
  - 用户可以在队列层重排优先级，而不需要进入每条详情单独修改。
  - 每条任务都能追溯到其来源风险或上游命令。
  - 顺序变化后，相关 owner 与等待项的状态会被同步回显。

---

## 6. Epic E2 — Publish Becomes Blast-Radius Control

### Epic 定义
- **Issue type:** Epic
- **Epic title:** Governance Loop Migration — Publish Becomes Blast-Radius Control
- **Epic summary:** 把发布从“通过/不通过”迁移成“有范围意识的传播控制动作”，让团队在发出 publish 命令前先看见 audience、channel 与 downstream 后果。
- **为什么这个 Epic 是主轴的一半：** Review 解决“该不该动”，Publish 解决“动了以后会污染谁、帮助谁、限制谁”。
- **视觉北极星：** Audience Scope Summary、Channel Gate Matrix、Blast Radius Preview、Propagation Theater
- **交互北极星：** 先理解后果，再发命令，再看传播

### Story E2-S1 — 发布前先预览 audience 与 channel 的 blast radius
- **Primary user:** Knowledge Manager / Support Ops
- **User story:** 作为知识治理负责人，我希望在发布前先看见哪些 audience 和 channel 会立即受到影响，这样我不会把看似正确的答案错误地扩散到不该看到的人群。
- **用户行为：** 在准备 publish、republish 或 restrict 时，先确认 free / enterprise / region / version / internal-external 的受影响范围。
- **系统预期行为：** 系统在确认动作前提供明确的 Blast Radius Preview，展示会新增、继续、停止或冲突的传播面。
- **视觉效果：** 发布区不是表单，而像一个 gate control 面板；Blast Radius Preview 应显著大于提交按钮。
- **交互效果：** 用户在发命令前可展开每个 audience / channel 的后果，并能快速切换查看 internal 与 external 差异。
- **为什么这条迁移重要：** 它把 Publish 从“审批通过”迁移成“传播后果判断”。
- **Acceptance signals:**
  - 发布前必须展示 audience scope 与 channel impact。
  - 用户能区分“新增曝光”“继续曝光”“停止曝光”“存在冲突”的不同状态。
  - 用户无需依赖记忆，也能知道此动作的外溢范围。

### Story E2-S2 — 发布动作可以是放开、收紧、拆分，而不只有通过/驳回
- **Primary user:** Support Ops / Knowledge Manager
- **User story:** 作为治理负责人，我希望发布动作可以是开放、限制、延迟或拆分 audience，而不是只有 approve / reject，这样我能在答案部分正确时先控制传播，而不是被迫二选一。
- **用户行为：** 面对一个部分正确、部分危险的对象时，决定只对内部开放、只对部分 audience 发布，或先暂停外部暴露。
- **系统预期行为：** 系统将 publish action 表达为一组治理动作：publish, restrict, split variant, hold external, republish internal only。
- **视觉效果：** 发布面像一个带闸门和分流路径的控制区，而不是单一确认框。
- **交互效果：** 用户调整动作时，系统同步更新 consequence lens，让“限定发布”成为自然动作，而不是高级配置。
- **为什么这条迁移重要：** 这让 Publish 真正具有 support governance 的细粒度，而不是文档后台式的“上线/不上线”。
- **Acceptance signals:**
  - 发布层存在超过 approve/reject 的控制动作。
  - 用户可以在一次动作中同时处理 internal/external 与 audience variant 的差异。
  - 系统将部分放开、部分收紧视为正常路径，而不是异常流程。

### Story E2-S3 — 发布后系统必须显示传播到了哪里、卡在了哪里
- **Primary user:** Support Lead / Support Ops
- **User story:** 作为支持负责人，我希望发布之后系统明确告诉我哪些 supporting surfaces 已同步、哪些还在阻塞，这样我才能判断这次命令到底有没有真正改变支持系统。
- **用户行为：** 在执行 publish / restrict / republish 后，回看 internal copilot、review queue、external surface、feedback 面是否已更新。
- **系统预期行为：** 系统提供 Propagation Theater / Ledger，显示命令已传播、待传播、传播失败、需要人工补位的环节。
- **视觉效果：** 发布成功状态不只是 toast，而是一张清晰的传播路径图与状态带。
- **交互效果：** 用户可以从传播结果直接跳入阻塞点继续处置，而不是重新从首页寻找。
- **为什么这条迁移重要：** 没有传播回显，Publish 仍只是一次按钮事件，而不是一次系统级命令。
- **Acceptance signals:**
  - 发布后能看到各个 supporting surfaces 的同步状态。
  - 系统明确区分“已传播”“等待传播”“传播失败”“需要人工动作”。
  - 用户可以从传播结果继续进入后续治理动作。

---

## 7. Epic E3 — Ticket & Drift Become Review Pressure

### Epic 定义
- **Issue type:** Epic
- **Epic title:** Governance Loop Migration — Ticket & Drift Become Review Pressure
- **Epic summary:** 把 ticket cluster、frontline rewrite、release/incident drift 和 source 异常，从“观察信号”迁移成“可直接推动治理队列变化的审阅压力”。
- **为什么这个 Epic 必须存在：** 如果 Review / Publish 只消费人工创建的草稿，Cygnus 就失去 support system 的动态入口。
- **视觉北极星：** Drift Weather Layer、Decision Constellation、Signal Loss Layer
- **交互北极星：** 风险信号直接转成治理动作入口

### Story E3-S1 — 重复改写与重复工单应直接上升为审阅压力，而不只是统计洞察
- **Primary user:** Support Ops / Escalation Lead
- **User story:** 作为支持运营负责人，我希望重复被人工改写的答案和重复出现的工单模式能直接上升为待治理压力，而不是停留在分析页里，这样真正浪费团队时间的问题会更早进入审阅闭环。
- **用户行为：** 发现某类 ticket 或 copilot suggestion 被持续重写后，决定是否应触发 draft、urgent review 或 ownership reroute。
- **系统预期行为：** 系统将 rewrite clusters 和 recurring ticket patterns 直接转化为 review pressure，并附带建议对象类型与影响范围。
- **视觉效果：** 这些信号应像正在升温的 pressure line，而不是只在图表里闪一下。
- **交互效果：** 用户可从 cluster 或 rewrite signal 直接进入 route to review、assign owner、mark urgent。
- **为什么这条迁移重要：** 它把 frontline friction 变成治理入口，而不是事后复盘材料。
- **Acceptance signals:**
  - rewrite / recurring ticket signals 可以直接进入 review queue。
  - 系统会同时显示该信号对应的对象建议和影响范围。
  - 用户不必先手动新建知识任务，才能推动治理动作。

### Story E3-S2 — release / incident drift 必须能强制打开紧急审阅路径
- **Primary user:** Support Lead / Knowledge Manager
- **User story:** 作为支持负责人，我希望 release 或 incident 引发的知识漂移能直接强制打开紧急审阅路径，这样错误答案不会在文档更新前先扩散到所有下游面。
- **用户行为：** 在 release week 或 incident 期间，识别哪些对象、哪些 audience 正在快速失配，并选择紧急 refresh / urgent review。
- **系统预期行为：** 系统把 drift 从“过期提示”提升为可发令的治理状态：open urgent review, freeze external publish, force audience recheck。
- **视觉效果：** Coverage & Drift 面应像天气前线一样，显示风险正在压向哪些 topic / audience，而不是静态 freshness badge。
- **交互效果：** 用户从 drift warning 进入命令路径时，应保留 release / incident 上下文，不丢失为什么现在必须动。
- **为什么这条迁移重要：** 它让“Freshness matters”真正变成产品动作，而不是旁观指标。
- **Acceptance signals:**
  - drift warning 可以直接触发治理动作，而不仅是打开详情。
  - release / incident 关联会持续显示到 review / publish 后续环节。
  - 紧急路径支持“先限制传播，后补内容”的治理节奏。

### Story E3-S3 — source 异常必须被理解成“治理失明”，而不是单纯同步错误
- **Primary user:** Support Ops / Knowledge Manager
- **User story:** 作为知识治理负责人，我希望 source 异常被解释为哪些对象与判断正在失去可信度，这样我可以决定先修来源还是先限制传播，而不是只看到一个技术错误提示。
- **用户行为：** 发现某个 source parse 失败、同步中断或内容异常后，判断它影响的是哪些对象、哪些 publish 决策和哪些下游面。
- **系统预期行为：** 系统把 source failure 翻译为受影响对象、受影响 audience 与潜在错误发布风险，并给出“修 source / 限制传播 / 转人工审核”的治理入口。
- **视觉效果：** Source health 页应带有 Signal Loss Layer，让用户感到系统某些区域正在失明，而不是仅显示红色报错。
- **交互效果：** 用户可从 source 问题直接切到对象或发布控制，而不是在后台日志与业务页面之间来回切换。
- **为什么这条迁移重要：** 它把基座故障重新定义为决策故障，守住 control tower 的可信度。
- **Acceptance signals:**
  - source failure 能映射到具体对象与传播风险。
  - 用户能从 source 视图直接发起治理动作。
  - 系统不会把 source 异常仅呈现为技术状态，而会呈现业务后果。

---

## 8. Epic E4 — Propagation Becomes Recovery Proof

### Epic 定义
- **Issue type:** Epic
- **Epic title:** Governance Loop Migration — Propagation Becomes Recovery Proof
- **Epic summary:** 把治理动作的“已执行”迁移成“已证明系统重新同步”，让 leadership 能根据 recovery evidence 决定下一次命令，而不是只看已完成列表。
- **为什么这个 Epic 是最后闭环：** 如果产品不能证明动作是否真的改变了系统，它仍只是一个指挥幻觉。
- **视觉北极星：** Recovery Window、Reality Check、Recovery Snapshot
- **交互北极星：** 先验证恢复，再决定下一步动作

### Story E4-S1 — supporting surfaces 必须回报“治理命令是否真的改变了一线行为”
- **Primary user:** Head of Support / Support Lead
- **User story:** 作为支持负责人，我希望 copilot 与人工 support surface 能回报治理命令是否真的改变了一线行为，这样我能知道系统是在重新同步，还是只是改了后台状态。
- **用户行为：** 在一次 review / publish / restrict 后，检查 frontline suggestion、rewrite、escalation 是否发生变化。
- **系统预期行为：** 系统将 copilot 和 downstream surface 的使用变化回流为治理结果，而不是孤立事件。
- **视觉效果：** Downstream Reality Check 面应像一面镜子，反映控制层动作在一线产生的真实结果。
- **交互效果：** 用户可以从某次命令直接打开对应的下游反馈，而不用重新搜索 topic。
- **为什么这条迁移重要：** 它让 supporting surfaces 变成治理结果回报面，而不是独立产品中心。
- **Acceptance signals:**
  - 下游使用变化能按具体治理命令回看。
  - rewrite / reject / escalate 被组织成治理反馈，而不是零散日志。
  - 用户能看出一线行为是否已向最新治理状态收敛。

### Story E4-S2 — Recovery Window 必须回答“系统有没有因为这次动作变得更一致”
- **Primary user:** Head of Support / Support Ops
- **User story:** 作为支持负责人，我希望系统能在一个 Recovery Window 里明确告诉我：因为这次动作，系统有没有更一致、更安全、更少误答，这样我能判断刚才的指挥是否真正有效。
- **用户行为：** 在关键命令后回看 rewrites、escalations、coverage gap、drift 和 publish conflict 的变化。
- **系统预期行为：** 系统围绕一次治理动作回显恢复信号，说明哪些指标收敛、哪些风险依旧、哪些环节仍待补位。
- **视觉效果：** Recovery Window 应呈现前后对比与未闭合点，而不是普通 activity log。
- **交互效果：** 用户能从恢复视图直接继续下一个命令，而不丢失当前上下文。
- **为什么这条迁移重要：** 没有 recovery proof，command center 会沦为“做过很多动作但无法判断是否有效”的繁忙幻觉。
- **Acceptance signals:**
  - 系统可以围绕一次治理动作展示恢复结果。
  - 视图同时显示改善项与未闭合项。
  - 用户可从 Recovery Window 继续发起后续治理动作。

### Story E4-S3 — 指挥层应能比较多个未闭合治理回路并决定下一步最高杠杆动作
- **Primary user:** Head of Support / Support Lead
- **User story:** 作为支持负责人，我希望系统能把多个尚未闭合的治理回路放在一起比较，并帮助我决定下一步最有杠杆的命令，这样我不会回到原始 dashboard 重新手动拼接全局状态。
- **用户行为：** 在完成一轮干预后，比较哪些 loop 已收敛、哪些仍扩散、下一步应该继续压哪一条线。
- **系统预期行为：** Command Center 汇总 open loops、residual risk、pending propagation 和 recovery proof，帮助用户形成下一次优先级判断。
- **视觉效果：** 首页应像一张持续更新的治理战情板，而不是每次都从零开始看报表。
- **交互效果：** 用户可以从 recovery state 直接回到新的 command brief，形成完整 Observe → Frame → Route → Change → Propagate → Verify 节奏。
- **为什么这条迁移重要：** 它把 Cygnus 从“执行了几次治理动作”提升为“持续指挥支持系统的控制台”。
- **Acceptance signals:**
  - 指挥层能同时看到多个 open loops 的剩余风险与恢复状态。
  - 用户可以在一个视图内决定下一步 highest-leverage action。
  - 系统不会要求用户回到原始数据页重新拼接局势。

---

## 9. Jira 录入模板（复制用）
下面模板用于把任意 Story 录入 Jira。

```md
Title: <Story title>
Issue Type: Story
Parent Epic: <Epic title>
Labels: migration, governance-loop, review-publish, support-brain, cygnus

Primary user:
User story:
User behavior:
Expected system behavior:
Visual effect:
Interaction effect:
Why this migration matters:
Acceptance signals:
- ...
- ...
- ...
Critical boundary (optional):
```

## 10. 录板时的最后检查
在真正创建 Jira 票前，逐条确认：
- 这条票有没有把 Cygnus 讲成 support governance center，而不是 agent tool？
- 这条票有没有让某个角色获得新的判断位置或命令权力？
- 这条票有没有把风险可见性、传播后果或恢复证明写清？
- 这条票是不是 accidentally 退化成页面搭建任务或技术任务？

如果最后读下来更像：
- 流程图
- 审批台升级清单
- generic dashboard backlog

那就说明这组 stories 还没有真正完成迁移对齐。
