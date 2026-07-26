# Support Brain for SaaS — 完整产品 Story

## 1. 这份文档的作用
这不是 PRD 的重复版，也不是页面 IA 的扩写版。

这份文档回答的是：
- 这款产品在完整叙事里，谁是主角
- 它面对的不是“一个页面问题”，而是一种什么样的持续张力
- 为什么产品必须长成 control tower，而不是客服工作台或 generic agent tool
- supporting surfaces 应该怎样围绕主叙事存在

## 2. 核心命题
**Support Brain for SaaS** 不是让 AI 去“更像客服”。

它的更大命题是：
**让 support lead 能够看见、判断、协调并改变一个已经失去同步的支持系统。**

这里的“系统”不是单一工单队列，而是同时包括：
- 文档与帮助中心
- 内部 SOP 与知识库
- 工单与聊天中反复出现的问题模式
- release / incident / known issue 的变化
- 不同 plan / region / version 的 audience 差异
- AI copilot 与人工客服正在实际使用的回答

## 3. 主角是谁
主角不是：
- 前线客服
- 单个 AI copilot
- customer-facing bot
- 一个“帮你自动写答案”的工作流

主角是：
**support lead / support ops / knowledge manager 的决策台。**

这意味着产品叙事的第一镜头，不应该从“某个客服正在处理一个 ticket”开始，
而应该从“整个支持系统哪里正在失去同步”开始。

## 4. 这个主角在和什么对抗
这款产品的敌人不是“知识太少”，而是下面这些更棘手的失配：

1. **知识与现实不同步**
   - 文档还没更新，但 release 已经变了
   - 已知问题已经升级，但 copilot 还在给旧答案

2. **同一个答案不适合所有人**
   - free 用户、enterprise 用户、EU 用户、旧版本用户，得到的回答不该一样

3. **重复问题在不同地方爆发，却没人能全局看见**
   - 工单里在爆
   - chatbot 里在爆
   - 帮助中心没覆盖
   - 主管却只能零散看到症状

4. **支持系统正在消耗人，但没有形成指挥视角**
   - 客服一直在改写答案
   - escalations 在升高
   - AI 置信度在下降
   - 但是没人知道先修哪里最有价值

## 5. 为什么必须是 control tower
如果把产品写成“客服 + AI 共享工作台”，会产生两个严重后果：

### 5.1 产品重心会滑向执行台，而不是决策台
这会让系统看起来像：
- 回答建议工具
- 对话辅助工具
- 工单处理效率工具

而不是：
- 优先级判断工具
- 知识治理工具
- 支持系统协调工具

### 5.2 全局能力会被稀释
一旦主叙事错了，以下能力就会弱化：
- 全局优先级
- 风险预警
- 跨队列调度
- 跨团队路由
- 发布影响判断
- audience 影响判断

## 6. 完整 Story 的五幕结构

### 第一幕：See the system move
用户不是来“打开一个对象”的。

他们进入产品时，先看到的是：
- 哪些 topic 正在升温
- 哪些队列压力在变化
- 哪些答案正在漂移
- 哪些 audience 正在被错误覆盖
- 哪些知识对象开始成为风险中心

这不是一个静态文档首页。
这是一个**支持系统正在发生什么**的入口。

### 第二幕：Understand what matters now
产品接下来要做的，不是一次性展示更多数据。

而是帮助用户回答：
**“如果我现在只能介入一件事，最该动哪里？”**

因此系统必须把以下信息编排成可以判断的上下文：
- 影响范围
- 受影响 audience
- 涉及的知识对象
- 是否与 release / incident / policy change 相关
- 当前负责人与处理状态
- downstream surfaces 是否已受污染

### 第三幕：Coordinate and command
这是完整 story 与普通 dashboard 的分水岭。

用户不只是“看到问题”，而是要**下达系统性的动作**：
- 把某个 cluster 路由给知识管理员
- 要求某条 Policy Rule 进入紧急审阅
- 暂停某个答案对 external surface 的发布
- 优先处理某个 plan / region 的 audience mismatch
- 要求支持团队临时改走某条 Escalation Route

所以产品核心感觉不是被动 triage，而是：
**我正在指挥一个分布式支持系统重新同步。**

### 第四幕：Propagate through supporting surfaces
Control tower 不是终点。

它的命令会改变 supporting surfaces：
- Review queue 的优先级
- Knowledge object 的审阅顺序
- Publish rules 的开放/收紧
- Copilot 看到的推荐答案
- customer-facing surface 是否还应继续暴露某类回答

完整 story 必须让这种“命令已传播出去”的感觉成立。
否则它就只是一个看板。

### 第五幕：See whether the system realigned
产品最后要回答的，不是“刚才是否执行了动作”，
而是：
**“这个系统有没有因为我的动作重新变得更一致、更安全、更可控？”**

因此产品要回显：
- rewritten answers 是否下降
- escalations 是否回落
- drift 是否收敛
- coverage 是否补齐
- 下游 surface 是否恢复一致

## 7. supporting surfaces 在叙事里的位置

### Agent copilot surface
它不是主角。
它是 control tower 决策的消费面。

它存在的意义是验证：
- 已治理知识是否能被一线使用
- 一线是否仍在改写答案
- 哪些建议仍然不可信

### Human support surface
它也不是主角。
它是控制层影响 frontline 的地方。

### Customer-facing answer surface
它是最下游的消费层。
在完整 story 里，它重要，但不应该抢走控制层叙事。

## 8. 四种高价值场景

### 场景 A：Release 之后的答案漂移
新版本刚发，help center 未更新，ticket volume 上升。
control tower 先看到风险，再协调 review / publish / audience 修正。

### 场景 B：Incident 期间的已知问题扩散
系统发现多个队列、多个语言面同时出现同类误答。
用户需要统一路由、统一 workaround、统一外部可见性。

### 场景 C：Policy change 引发的多 audience 冲突
某项退款/权限规则改变，但不同 plan、不同 region 的说法不一致。
产品必须支持从规则变化出发，协调多个对象更新。

### 场景 D：Copilot 被反复人工改写
表面上 AI 还在工作，实际上 frontline 一直在纠偏。
control tower 要把这些局部重写上升成全局知识治理任务。

## 9. 这套 Story 的气质要求
完整 story 不应该让人感觉：
- “这是个更高级的文档后台”
- “这是个 AI 建议审批器”
- “这是个客服效率插件”

它应该让人感觉：
- “这是支持团队的 mission control”
- “这里能看见系统级的变化”
- “这里不是聊天，而是指挥”

## 10. 这份产品 Story 的落点
这份 story 最终要为后续三个产物服务：
1. 前端行为 story
2. 视觉语言方案
3. 交互原则

它必须持续守住一个边界：
**Cygnus / Support Brain 是 support knowledge operating system 的控制层，而不是 agent workflow desktop。**
