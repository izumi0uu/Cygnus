# Cygnus — Jira 项目配置反向设计方案

## 1. 文档用途
这份文档不是在定义产品本身，而是在说明：
**为了让 CYG Jira 同时承载“治理产品 stories”与“Arkon 全量迁移工程主线”，项目需要怎样的配置与使用约定。**

它服务于三件事：
- 解释为什么当前看板暂时退化成了 “Task + Relates”
- 给后续 Jira 项目配置提供一份低风险调整顺序
- 保证 backlog 同时容纳 **support governance mission control** 与 **full-port baseline engineering lane**，而不漂成 generic PM board

## 2. 当前观察状态（基于 2026-06-18 的 CYG 项目实测）
当前已验证到的现实是：
- Jira 项目：`CYG`
- 板：`68 / CYG面板`
- 通过当前 MCP 创建 issue 时：
  - `Task` 可正常创建
  - `Epic` / `Story` 创建会返回“指定有效的事务类型”
  - 给 Task 直接设置 `parent` 也可能返回“请选择有效的父事务”
- 因此当前采用的临时落板方式是：
  - `CYG-2 ~ CYG-5` 作为治理主题父票（仍然是 Task）
  - `CYG-6 ~ CYG-17` 作为治理 story 叶子票（仍然是 Task）
  - `CYG-23 ~ CYG-25` 作为 full-port / runability / shell parity 主题父票（仍然是 Task）
  - 通过 `Relates` 建立主题与叶子票的弱连接

## 3. 这说明了什么
### 3.1 已确认事实
已确认的不是“Jira 不支持 Epic / Story”，而是：
**当前 CYG 项目在本次创建上下文里，没有把 Epic / Story 暴露成可用 work type，且 Task parent hierarchy 也未稳定开放。**

### 3.2 高概率推断
从项目行为看，`CYG` 很像一个 **team-managed / next-gen 风格项目**，但这一点仍应以 Jira 项目设置页为准。

> 这里的“team-managed”是基于当前行为的推断，不是管理员页面已确认的结论。

## 4. 我们现在其实有两套 backlog 结构
Cygnus 不再只有一套 Jira 叙事。

### 4.1 治理产品线
- `CYG-2 ~ CYG-5`：治理主线父票
- `CYG-6 ~ CYG-17`：用户可感知的治理能力变化

这套结构服务：
- 产品叙事
- 页面 story map
- 视觉与交互设计
- 后续 P3 support verticalization

### 4.2 工程迁移线
- `CYG-23`：P1 full-port baseline 父线
- `CYG-24`：P2 runability recovery 父线
- `CYG-25`：P4 optional shell parity 父线
- 与之关联的迁移子票：runtime/database/services/protocol/MRP/knowledge/surface/wiring/boot/boundary

这套结构服务：
- 当前真正的工程主线
- Arkon 全量迁移的控制面
- 跑通与修复的后续排程

## 5. 为什么不能把两套结构再混回去
如果长期混在一起：
- 产品故事会被误读成当前代码主线
- 全量迁移票会吞掉治理主语
- board 会退化成“全是 Task 的大杂烩”
- support governance mission control 与 engineering migration lane 都会失焦

因此当前最小正确做法是：
- **结构上并存两条线**
- **语义上明确不同父票**
- **通过 labels + links 明确 phase 与 lane**

## 6. 理想层级（未来可升级）
理想结构仍然应该是：
- **Epic** = 一条治理主线 / 一条迁移主线
- **Story** = 一个用户可感知能力变化 / 一个清晰工程切片
- **Task** = 杂项、研究、临时补充
- **Subtask** = 真正需要更细执行拆解时才使用

### 6.1 对应到当前两条线
#### 治理产品线
- `CYG-2 ~ CYG-5` → Epic
- `CYG-6 ~ CYG-17` → Story

#### 工程迁移线
- `CYG-23 ~ CYG-25` → Epic
- 新迁移子票 → Story

## 7. 当前推荐配置方案

### 7.1 短期：继续接受 Task + Relates
在 issue type 与 hierarchy 未修好前：
- 继续使用 Task 建票
- 继续用 `Relates` 建立父线关系
- 不要因为 hierarchy 不完美就停止 backlog 建设

### 7.2 中期：补齐 Epic / Story / Subtask
无论 CYG 最终是 team-managed 还是 company-managed，目标都应是：
1. 让 Epic / Story / Subtask 可用
2. 让 backlog 能识别真实层级
3. 让治理产品线与工程迁移线都能回到真正 hierarchy

### 7.3 最小迁移原则
不要在补 hierarchy 时同时做这些事：
- 不要重写全部 story 内容
- 不要把治理 story 改写成纯技术任务
- 不要把工程迁移票改写成页面需求

最小目标只是：
**让现有两条 backlog 真相回到正确层级。**

## 8. 当前标签约定
### 8.1 治理产品线
- `cygnus`
- `governance-loop`
- `migration`
- `review-publish`
- `support-brain`
- `theme-review` / `theme-publish` / `theme-pressure` / `theme-recovery`
- `story-leaf`
- `seq-01 ~ seq-12`

### 8.2 工程迁移线
- `arkon-full-port`
- `full-port-baseline`
- `migration`
- `support-brain`
- `phase-01-full-port`
- `phase-02-runability`
- `phase-04-shell-parity`
- 以及更细的 substrate 标签，如：
  - `runtime-backbone`
  - `database-layer`
  - `service-layer`
  - `protocol-layer`
  - `mrp-pipeline`
  - `knowledge-substrate`
  - `integration-surface`

### 8.3 延期 shell parity lane
- `phase-04-deferred`
- `shell-parity`
- `support-relevant-candidate`
- `generic-shell-reference`
- `non-support-excluded`

使用规则：
- `support-relevant-candidate` 只给那些**直接承载或解除 support governance surface 阻塞**的壳层候选
- `generic-shell-reference` 用于 auth / admin / wiki 这类仍可参考、但不属于当前主线的 generic-product shell
- `non-support-excluded` 用于已明确隔离出当前 P1/P2/P3 的页面或壳层
- shell lane 的票如果没有明确 support blocker，只能停留在 deferred / reference 语义，不能重写当前工程优先级

## 9. 推荐的 board 使用约定
### 9.1 看板解释顺序
看板使用者首先要能区分：
1. 这是治理产品线，还是工程迁移线
2. 这张票是父线，还是叶子 story
3. 这张票属于 P1、P2、P3 还是 P4

### 9.2 当前默认规则
- 治理 product stories 默认属于 **P3**
- `CYG-23+` 默认属于 **P1/P2/P4**
- 当前工程执行优先级高于 P3 页面/交互实现

## 10. 对现有票的迁移建议
### 10.1 `CYG-6 ~ CYG-17`
保留原语义，后续升级为 P3 stories。

### 10.2 `CYG-18 ~ CYG-22`
保留已完成状态，但通过 comment / label 标记为：
- bootstrap history
- selective-extraction reconnaissance
- superseded-by-full-port

### 10.3 `CYG-23+`
继续作为当前工程主线维护，不要降级成说明性票据。

## 11. 一句话结论
**CYG 现在不是一条 backlog，而是两条并存的 backlog：一条服务治理产品叙事，一条服务 Arkon 全量迁移与跑通修复。**
