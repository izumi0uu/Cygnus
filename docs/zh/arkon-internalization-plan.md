# Cygnus — Arkon 内化与上游切断计划

> **状态：✅ 本计划已完结（2026-07 收口）。** 内化与上游切断 lane 已全部关闭（Jira CYG-69~75、CYG-88~90），外部 checkout 的保存/审计/删除停机线由 `scripts/external_checkout_{preserve,audit}.py` 与 `scripts/upstream_cutover_gate.py` 固化。本文档保留为决策档案；当前主线见 `docs/README.md`（会话接缝 CYG-92~96）。

## 1. 文档用途
这份文档用来冻结一个新的工程决策：

**当目标不只是“把 Arkon 迁入 Cygnus”，而是要把它完整内化为 Cygnus 的一部分、并最终删除外部 Arkon 代码基座时，必须开启一条独立的 post-P2 内化迁移线。**

它回答的是：
- P1/P2 完成之后，Cygnus 是否长期保留 Arkon 的上游身份残留
- 哪些工作属于“内化 / 去上游化”，而不是被误塞回 P1 源码迁入
- 在不把 shell parity 拉回主线的前提下，怎样把 Arkon 真正吸收到 Cygnus 里

它不回答的是：
- Cygnus 产品是否仍然是 support knowledge operating system
- Nanobot 是否仍然是 session layer
- optional shell parity 是否要立刻变成 roadmap 主线

这些边界都没有改变。

## 2. 当前 settled decision
当前新增的 settled decision 是：

1. **P1 / P2 完成后，不再把“长期保留 Arkon 上游命名”视为默认终态**
2. **如果目标是完整吸收 Arkon 并最终删除独立上游代码基座，就要进入一条独立的 P2.5 内化迁移线**
3. **内化迁移线不等于 shell parity，也不等于 support verticalization**
4. **任何重命名、入口收敛、身份切换、删除准备，都必须在 P2.5 中进行，而不是回写成 P1 import 行为**
5. **Cygnus 仍然保留“Arkon = 内部 substrate”的产品关系，但工程所有权会收敛到 Cygnus 自己**

## 3. 这条线为什么必须单独存在
如果没有这条线，团队最容易再次混淆三件事：

- **P1**：源码是否按上游实码迁入
- **P2**：最小运行与 smoke-run 是否恢复
- **P2.5**：Cygnus 是否已经接管这套 substrate 的命名、入口、边界与删除准备

没有 P2.5 时，常见漂移是：
- 把 `arkon` 身份残留长期留在 runtime / MCP / 默认配置里
- 一边说“已经全量迁入”，一边又保留双入口 / 双真相
- 过早把注意力拉到 product shell parity，而不是先完成基底所有权切换

## 4. 阶段定位
### P2.5 — Internalization & Upstream Cutover
这条线位于：
- **P2 之后**：因为它依赖最小 runability 已恢复
- **P3 之前或与早期 P3 并行**：当目标是“删除独立 Arkon 基座”时，应优先让 substrate ownership 清晰下来
- **P4 之前**：因为它不是产品壳 parity，而是基底归属切换

### 它的完成不代表
- support verticalization 已完成
- optional shell parity 已决定
- Cygnus 要复制 Arkon 的全部 UI

### 它真正代表
- Arkon substrate 作为“外部上游项目”的身份开始被 Cygnus 内化
- Cygnus 获得对这套基底的工程命名权、入口控制权、边界解释权
- 后续若删除独立 Arkon 仓库，不再缺少迁移语义与验收边界

## 5. 强制工作切口
### 5.1 Identity residue cleanup
必须清理仍在代码中暴露“Arkon 仍是运行时主体”的残留，例如：
- 默认发件人 / 示例配置名 / server alias
- 仍以 `arkon` 命名的权限哨兵或 runtime 标识
- 对外暴露时会误导使用者的字符串身份残留

### 5.2 App assembly convergence
必须决定并收敛：
- 公共入口已经收口到 `cygnus.runtime.main`
- `cygnus/api/*` 旧包已移除
- 哪个 app 是对外主入口
- 哪些只是基底保留层，哪些已经是 Cygnus 自己的控制面

### 5.3 Namespace & ownership freeze
必须写清：
- 哪些 upstream topology 仍保留在 `cygnus/runtime/*` 作为 substrate 对照层
- 哪些能力已经成为 Cygnus 自有命名与自有边界
- 哪些命名残留只是过渡债务，必须继续收敛


### 5.3.1 Package boundary freeze（当前长期解释）
在完成 `identity` 与 `assembly` 收敛后，P2.5 现在将三层包语义冻结为：

- `cygnus/runtime/*` = **runtime / app shell / imported upstream topology reference**
  - 这里继续保留 FastAPI app、worker、database、services、routers、mcp、utils、scripts 等上游对照拓扑
  - 它的职责是承载已迁入的运行壳与基础设施接线，不等于“Cygnus 的全部后端真相”
  - 该层已在 `CYG-75` 中收敛为 `runtime`；后续若继续重组，只能作为新的架构收敛动作推进，不属于 P1 source parity 迁入动作

- `cygnus/substrate/*` = **Cygnus-owned substrate contracts**
  - 这里只放 provider-neutral protocol、tool runtime、pipeline phase / checkpoint、durable workflow primitives 这类底层契约
  - 它不是第二套 app shell，也不承载 FastAPI / worker / database 入口
  - `substrate` 是长期保留层，不是临时 facade
  - 当前已冻结的 source compilation primitive cluster 包括 `cygnus.substrate.source_outline`、`cygnus.substrate.source_images`、`cygnus.substrate.source_text`
  - `runtime` 仍可调用这些 primitive 进行 worker / router / storage 装配，但不再拥有它们的提取语义

- `cygnus/api/*` = **removed legacy package**
  - `cygnus/api/` 下不应再有 Python 模块
  - `cygnus.api.*` 不得重新出现为内部或外部 import 路径

- `cygnus/domain/*` = **support-domain contracts / object vocabulary**
  - Answer Card / Policy Rule / Troubleshooting Flow / Escalation Route 这类 support object truth 在这里冻结

- `cygnus/evidence/*` = **evidence normalization and record layer**
  - 原始支持证据、freshness、source record 的归一化和记录层放在这里

- `cygnus/retrieval/*` = **object/evidence retrieval and source-trace query layer**
  - 对象检索、证据检索、source trace 解析，以及 semantic embedding persistence 都属于这里，不属于 runtime shell owner

- `cygnus/review/*` / `cygnus/publish/*` / `cygnus/recovery/*` = **governance control-plane modules**
  - review、publish、recovery 是 Cygnus 自有治理控制面，不是“未来应塞回 runtime 的散落残片”

- `cygnus/integrations/*` = **external/session-facing integration adapters**
  - 面向 Nanobot、MCP、外部调用方的适配层放在这里，而不是混成产品主语

- `cygnus/workflows/*` = **workflow composition layer, not generic runtime shell**
  - 这里只承载治理工作流组合，不得重新长成第二套自由游走 session runtime

### 5.3.2 Import policy freeze（当前长期执行约束）
在 package owner 已冻结后，内部 import 也必须收敛到单一约定：

- `cygnus.runtime.main` 是 canonical app owner
- `cygnus.runtime.governance_router` 是治理路由唯一 owner
- `cygnus.runtime.config` 与 `cygnus.runtime.services.auth_service` 是认证/配置 owner
- `cygnus.api.*` 不得重新出现为内部默认 import
- `cygnus.api.auth`、`cygnus.api.config`、`cygnus.api.governance_router`、`cygnus.api.app` 不再允许被内部代码依赖
- 任何新的内部实现不得重新引入 `app.*` 旧命名空间

这意味着：
- 兼容 facade 可以保留最小壳，但不能再长出第二套 owner
- 测试必须锁住禁止回流路径，而不是只靠约定
- 冗余 facade 若已无内部调用，必须进入删除或进一步收缩

补充解释：
- `review / publish / recovery / retrieval / domain / evidence / integrations / workflows` 代表 Cygnus 自有领域与控制面模块，不因为位于 `runtime` 之外就被视为“越层”
- 当前真正需要收敛的不是“所有包都塞进 runtime”，而是避免 `runtime` 被误读成“整个产品后端”
- 首轮 package rename 已在 `CYG-75` 中完成；后续若继续调整树形结构，应以新的架构收敛票推进 deeper convergence

### 5.4 Docs / tests / handoff truth sync
必须同步：
- handoff
- smoke / boundary tests
- agent execution context
- Jira 叙事

否则仓库会再次出现“代码已经内化、但文档还在讲两套真相”的漂移。

### 5.5 Upstream deletion readiness
必须定义删除独立 Arkon 代码基座之前的最小验收：
- 无外部 Arkon 源码导入依赖
- 无关键运行时身份残留
- 入口关系、命名关系、边界关系都有明确文档
- Jira 不再把“继续依赖外部 Arkon”当成默认前提

#### 5.5.1 Readiness gate checklist
只有当下面所有 gate item 都为 green，才允许把“删除独立 Arkon 代码基座”视为可执行动作：

1. **Code residue gate**
   - `cygnus/` 与 `frontend/` 下不再出现外部 `arkon` runtime residue
   - 不再出现 `__arkon_requires__`、`arkon@localhost`、`import arkon` 一类残留

2. **Compat shrink gate**
   - `cygnus/api/*` 已移除
   - `cygnus/api/` 下不应再有 Python 模块
   - 不允许 `cygnus/api/__init__.py`、`cygnus/api/app.py`、`cygnus/api/auth.py`、`cygnus/api/config.py`、`cygnus/api/governance_router.py` 这类过渡 owner 回流

3. **Owner truth gate**
   - `cygnus.runtime.main` 仍是 canonical public app owner
   - `cygnus.runtime.governance_router`、`cygnus.runtime.config`、`cygnus.runtime.services.auth_service` 的 owner 解释没有回退

4. **Narrative gate**
   - agent / Jira / handoff 继续把 cutover 表述为 `internalized substrate` / `upstream cutover started`
   - 不能把 cutover 叙事写成 shell parity 已完成或 support verticalization 已完成

5. **Executable verification gate**
   - `scripts/upstream_cutover_gate.py` 通过
   - 与 P2.5 边界相关的 targeted tests 通过

#### 5.5.2 外部 checkout 删除纪律
- 如果磁盘上仍存在独立的外部 Arkon checkout，先用 `scripts/external_checkout_preserve.py` 保全本地 ahead commits、dirty worktree 与 untracked files，再讨论物理删除动作
- `scripts/external_checkout_audit.py --fail-if-found` 才是“外部 checkout 已不存在”的物理删除证明；preserve 只负责保全，不等于删除证明
- 如果 audit 仍能找到独立 checkout，就只能说 `upstream cutover started`，不能说“外部基座已可删除完毕”

这条 gate 的意义不是“证明产品已经做完”，而是证明：
- 删除独立上游代码基座的动作已经有明确停机线
- downstream 不再建立在“继续依赖外部 Arkon 只是默认现状”的前提上
- cutover 结项语言不会漂移成 P3 或 P4

## 6. completion truth
现在必须区分四种完成态：

### A. Source parity completed
意味着：
- Arkon baseline 代码已迁入

不意味着：
- 系统已启动
- Cygnus 已接管这套 substrate 的工程身份

### B. Runability recovered
意味着：
- baseline 最小可接线、可启动、可 smoke-run

不意味着：
- Cygnus 已完成命名/入口/边界的所有权切换

### C. Internalization completed
意味着：
- Cygnus 已开始以自己的工程身份接管这套 substrate
- 关键 runtime identity residue 已被切掉或明确隔离
- 后续删除独立 Arkon 基座已经具备明确切口

不意味着：
- support verticalization 已完成
- optional shell parity 已完成

### D. Cygnus verticalization completed
意味着：
- support-domain 主语、治理闭环、产品 surfaces 已开始真正建立

### 6.1 状态汇报契约
后续在 Jira 评论、handoff、日志、结项说明里，必须显式带阶段语义：

- **P1**：`source parity imported` / `baseline mirrored` / `upstream topology preserved`
- **P2**：`runability recovered` / `wiring restored` / `boot or smoke-run regained`
- **P2.5**：`internalized substrate` / `upstream cutover started` / `Cygnus-owned runtime identity established`
- **P3**：`support verticalization implemented` / `governance surface established`

禁止把下面四句话混成同义词：
- 代码已迁入
- 系统已跑通
- 基底已内化
- 产品已 support 化

## 7. 当前建议的 Jira 拆法
### Parent lanes
1. **[全量迁移] Arkon Full-Port Baseline**
2. **[修复跑通] Repair & Runability Recovery**
3. **[内化迁移] Arkon Internalization & Upstream Cutover**
4. **[延期] Optional Product-Shell Parity**

### 当前推荐的第一批内化叶子票
1. runtime identity residue cleanup
2. public app assembly convergence
3. namespace / ownership freeze
4. docs / tests / handoff truth sync
5. deletion-readiness gate

## 8. 一句话结论
**如果 Cygnus 的目标是“把 Arkon 彻底吸收进来，然后删除独立上游代码基座”，那 P1/P2 还不够；必须再走一条明确的 P2.5 内化迁移线。**
