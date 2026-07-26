# Support Brain for SaaS — Loop Boundaries

## 1. 目的
本文件用于防止 Cygnus 演化成“三套通用 agent loop”同时存在的复杂系统。

它要明确回答：
- 哪一层允许开放式推理
- 哪一层只允许确定性业务逻辑
- 哪一层保存哪种状态
- 哪一层拥有审批真相
- Cygnus 内部工作流编排到底是 workflow engine 还是第二个 agent runtime

## 2. 核心结论
Cygnus 的正确结构不是三套 agent loop，而是：

1. **Nanobot**：唯一的通用会话型 agent loop
2. **Cygnus Harness**：领域控制层，不是第二个通用 agent
3. **Cygnus Workflow Orchestration**：业务工作流引擎，不是第三个聊天大脑

一句话：
**1 个 agent loop + 1 个 domain harness + 1 个 workflow engine**

## 3. 非目标
本文件不定义：
- UI 细节
- 数据库表结构
- 具体模型选型
- 详细 SDK 实现

本文件只定义 runtime 边界与职责归属。

## 4. 三层运行时模型

## 4.1 Layer A — Nanobot Loop
### 角色
唯一的 **开放式会话 agent loop**。

### 负责内容
- 多轮对话
- session continuity
- workspace / workbench context
- memory / sustained goals
- general tool proposal
- user-facing planning / decomposition
- tool result synthesis

### 可以做的推理
- 根据用户请求决定下一步该搜、该读、该问、该调什么工具
- 决定何时需要调用 Cygnus domain tools
- 生成 user-facing explanation / clarification / proposal

### 不该负责的业务真相
- 哪个 draft 允许 external publish
- 哪个 audience variant 合法
- 哪个 policy rule 可以绕过审批
- 哪个 evidence 足以构成已批准知识

## 4.2 Layer B — Cygnus Domain Harness
### 角色
业务控制面，不是第二个通用 agent。

### 负责内容
- typed domain tools
- schema validation
- permission / approval enforcement
- audit trail
- retrieval orchestration
- domain invariants
- draft / review / publish guardrails

### 可以做的“推理”类型
这里只允许：
- 受控、局部、目标明确的 domain validation
- 风险明确的小型 drafting 或 classification 调用
- deterministic 或 bounded 业务判断

### 不该变成什么
它不应该变成：
- 一个新的 open-ended chat agent
- 一个新的 persistent session brain
- 一个重新实现 Nanobot memory / planning / workspace 的系统

## 4.3 Layer C — Cygnus Workflow Orchestration
### 角色
业务工作流编排器。

### 负责内容
- workflow state transitions
- branch / retry / rollback routing
- human approval gates
- step-level resumability
- workflow-level observability

### 不应该负责
- 通用聊天
- session memory
- user-facing开放式会话
- 作为另一个独立 agent shell 长时间自由游走

## 5. 哪一层可以有 loop

## 5.1 允许存在的 loop
### A. 主 loop：Nanobot loop
这是唯一的通用 agent loop。

### B. Workflow loop：Cygnus workflow state progression
这是 workflow loop，不是聊天式 agent loop。

### C. 局部 mini-loop：Cygnus bounded task loop
例如：
- draft object writer 2-5 步小 loop
- critic/reviewer bounded retry
- evidence insufficiency retry

这些 mini-loop 必须满足：
- 有固定目标
- 有严格步数上限
- 不拥有全局 session memory
- 不拥有审批最终真相
- 失败后返回结构化状态，而不是无限继续

## 5.2 不允许存在的 loop
以下形态应明确避免：

### 反模式 1：Nanobot 有一套 planner，Cygnus 再有一套 planner
这会形成双重规划真相。

### 反模式 2：工作流引擎的每个步骤都再嵌一个开放式 agent
这会把 workflow engine 变成 agent swarm runtime。

### 反模式 3：Cygnus 自己维护第二套 session memory
这会导致 memory truth 分裂。

### 反模式 4：审批既在 Nanobot 里判断，又在 Cygnus 里判断
审批真相只能有一个地方持久化与裁决。

## 6. 状态归属表
| 状态类型 | 归属层 | 说明 |
|---|---|---|
| session chat history | Nanobot | 用户对话与会话上下文 |
| workspace / workbench state | Nanobot | 会话工作区状态 |
| long-session memory | Nanobot | 会话持续性记忆 |
| active user task decomposition | Nanobot | 开放式任务拆解 |
| retrieved business objects | Cygnus | 领域对象事实 |
| draft object state | Cygnus | 草稿与版本状态 |
| review queue state | Cygnus | 审核流程状态 |
| approval records | Cygnus | 审批真相 |
| publication records | Cygnus | 发布真相 |
| workflow step state | Cygnus workflow engine | workflow 内部状态 |
| eval traces | Cygnus | 域内质量与业务 traces |
| session-level tool traces | Nanobot + Cygnus refs | Nanobot 记录会话，Cygnus 保留业务 trace refs |

## 7. 审批归属
### 原则
**审批真相必须在 Cygnus。**

原因：
- publish 是业务动作
- audience / visibility / policy 是领域规则
- 审批记录必须和 draft / object / publication 一起可审计

### Nanobot 的角色
Nanobot 可以：
- 发起审批请求
- 向用户展示审批预览
- 接收用户确认

但 Nanobot 不应：
- 成为审批记录唯一存储地
- 代替 Cygnus 写最终批准状态
- 绕过 Cygnus 直接执行高风险 publish

## 8. Memory 归属
### Nanobot memory
适合存：
- 用户偏好
- 当前会话上下文
- 长时持续目标
- 当前 workbench 进度

### Cygnus domain state
适合存：
- draft object
- review notes
- source trace
- publication records
- feedback signals
- drift alerts

### 不变量
**业务对象状态不是聊天记忆。**

## 9. Planning 归属
### Nanobot planning
负责：
- user-facing task planning
- 会话内下一步选择
- 是否需要调用哪些 domain tools

### Cygnus planning
只允许在 domain workflow 中出现局部 planning，例如：
- 对象类型判定
- evidence sufficiency judgement
- draft completeness judgement

### 不变量
Cygnus 不应承担一整套“用户任务计划器”的角色。

## 10. RAG 归属
### Cygnus 负责
- object retrieval
- evidence retrieval
- metadata filtering
- audience gating
- rerank
- source traceability

### Nanobot 负责
- 决定什么时候需要检索
- 解释检索结果
- 把 retrieval result 纳入会话流程

### 不变量
**RAG truth lives in Cygnus, not in Nanobot memory.**

## 11. 工作流编排放置原则
Cygnus 内部工作流编排只应该服务于那些“已经明显是业务流程”的治理流，例如：
- knowledge object creation
- freshness refresh
- publish governance

内部工作流编排不该做：
- general chat orchestration
- session memory manager
- generic copilot runtime
- second planning shell

## 12. 受控 mini-loop 规则
如果某个 workflow step 内部需要 LLM 小循环，必须满足：
1. 目标单一
2. 工具集合极小
3. 最大步数固定
4. timeout 固定
5. 失败返回结构化 error/result
6. 不生成新的全局会话状态
7. 不覆盖 approval truth

## 13. 实现时的机械不变量
后续实现应强制保留：
- 只有 Nanobot 维护通用 session loop
- 只有 Cygnus 保存审批真相
- 只有 Cygnus 拥有业务对象真相
- Cygnus workflow orchestration 只编排业务状态迁移
- 所有高风险 external publish 都必须在 Cygnus 域内校验并记录

## 14. 快速判断法
如果一个新能力主要是在回答这些问题，它属于 Nanobot：
- 用户下一步想做什么？
- 这轮会话该调哪个工具？
- 如何组织回复？

如果一个新能力主要是在回答这些问题，它属于 Cygnus：
- 这个对象是否合法？
- 这个 audience variant 是否允许？
- 这个 publish 是否需要审批？
- 这个 trace 是否完整？

如果一个新能力主要是在回答这些问题，它属于 Cygnus workflow orchestration：
- 这个 workflow 当前卡在哪个节点？
- 下一条边应该走哪条？
- 哪个节点需要重试/回退/等待审批？

## 15. 当前结论
为了避免维护三套通用 agent loop，Cygnus 必须坚持：

- **Nanobot = 唯一通用 agent loop**
- **Cygnus Harness = 领域控制层，不是第二个 agent**
- **Cygnus workflow orchestration = workflow engine，不是第三个 agent**

这就是后续实现的 runtime 边界基线。
