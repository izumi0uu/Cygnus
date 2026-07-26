# Cygnus — Arkon 全量迁移基线计划

> **状态：✅ 本计划已完结（2026-07 收口）。** P1 全量迁移 / P2 跑通恢复 / P2.5 内化与上游切断均已关闭（Jira CYG-23、CYG-24、CYG-69~91），停机线由 guard 测试套件与 `scripts/upstream_cutover_gate.py` 固化。本文档保留为迁移期决策档案，不再描述当前主线；当前主线见 `docs/README.md`（会话接缝 CYG-92~96）。

## 1. 文档用途
这份文档用来冻结当前已经改变的工程真相：

**Cygnus 当前不再沿用 `domain-first selective extraction` 作为主迁移策略，而是改为先建立 Arkon full-port baseline。**

它回答的是：
- 当前到底要迁 Arkon 的哪些代码
- 哪些暂时不迁
- 迁入、跑通、support 化三者之间如何分阶段

它不回答的是：
- 最终产品是不是 support knowledge operating system
- Nanobot 是否还是 session layer

这些产品边界都没有改变。

## 2. 当前 settled decision
当前 settled decision 是：

1. **先把 Arkon backend / runtime / worker / AI pipeline / retrieval / protocol 迁入 Cygnus**
2. **先尽量保留 upstream 模块拓扑**
3. **当前不强制迁入 Arkon 产品壳 / admin 壳 / 非 support 主语页面**
4. **把 runability recovery 从 source parity import 中拆出来**
5. **把现有 `CYG-6 ~ CYG-17` 保留为 support verticalization stories**
6. **如果目标是把 Arkon 完整吸收进 Cygnus 并最终删除独立上游代码基座，必须在 P2 之后开启独立的内化迁移线**

## 3. 当前强制范围
### 3.1 必须进入 baseline 的层
对应 Arkon 路径：

- `app/main.py`
- `app/config.py`
- `app/worker.py`
- `app/database/*`
- `app/services/*`
- `app/ai/*`
- `app/ai/mrp/*`
- `app/ai/providers/*`
- `app/routers/*`
- `app/mcp/*`
- `app/utils/*`

### 3.2 当前不作为强制范围
- Arkon 产品壳
- admin 壳
- 非 support 主语页面
- 任何只是为了“看起来更完整”而补迁的 UI 层

## 4. 当前阶段模型
### P0 — Migration Manifest & Boundary Freeze
先把：
- 迁移范围
- 非迁移范围
- 完成态定义

写死，避免 Jira 和文档漂移。

### P1 — Source Parity Import
先把 Arkon 的代码版图整体镜像进 Cygnus。

这个阶段的完成，不代表：
- 系统可运行
- 依赖已修复
- 业务已 support 化

它只代表：
- baseline 已进入 repo
- upstream topology 有了稳定对照面

### P2 — Repair / Runability Recovery
把以下能力重新接通：
- dependency wiring
- config wiring
- storage / queue / db wiring
- API / worker / MRP resume path

这个阶段的完成，不代表：
- Cygnus 产品已经做完

它只代表：
- baseline 开始具备最小运行能力

### P2.5 — Internalization & Upstream Cutover
如果 Cygnus 的目标是“保留 Arkon 作为内部 substrate，但删除独立 Arkon 代码基座”，就必须在 P2 之后额外推进：
- runtime identity residue cleanup
- app assembly convergence
- namespace / ownership freeze
- docs/tests/handoff truth sync
- deletion-readiness gate

这个阶段的完成，不代表：
- support verticalization 已完成
- optional shell parity 已完成

它只代表：
- Cygnus 开始真正接管这套 substrate 的工程身份与入口边界

### P3 — Support Verticalization
在 P1 / P2 / P2.5 的基础上，再推进：
- support knowledge objects
- governance surfaces
- support-domain review / publish / recovery

现有 `CYG-6 ~ CYG-17` 属于这个阶段。

### P4 — Optional Product-Shell Parity
如果后续真的需要，再决定：
- 哪些 Arkon 壳层值得补迁
- 哪些只保留 backend parity 即可

#### P4 当前候选分类
当前只允许先做**壳层候选分类**，不允许把 shell parity 直接伪装成当前主线实现。

1. **support-relevant shell candidate**
   - 直接承载 support governance mission control 的 operator shell / chrome
   - 只有在它真实承载 review / publish / recovery / evidence 阅读时才成立的 support reader shell
   - 为 support lead / support ops 进入治理控制面而存在的最小 sign-in / entry gate

2. **generic-product shell candidate**
   - 通用 auth / account center
   - admin / system settings shell
   - wiki 首页 / library / editor 这类以 generic knowledge work 为主语的产品壳

3. **non-support shell work that stays excluded by default**
   - marketing / landing / showcase 页面
   - 与 support governance 无关的 project / workspace / onboarding 页面
   - 只是为了“看起来更完整”的 parity-only UI

#### P4 当前排除 / 隔离原则
- `auth / admin / wiki` 这类壳层现在只能先被分类，不自动进入 P1/P2/P3 强制范围
- 只有当某个 shell 候选**直接解除 support verticalization 阻塞**时，才允许作为 future P4 候选继续推进
- “视觉完整度”或“上游以前有这个页面”都不是补迁理由
- 非 support 主语页面必须继续隔离在 deferred shell lane，不能回流改写当前 substrate migration 主线

## 5. 当前建议的 Jira 拆法
### Parent lanes
1. **[全量迁移] Arkon Full-Port Baseline**
2. **[修复跑通] Repair & Runability Recovery**
3. **[内化迁移] Arkon Internalization & Upstream Cutover**
4. **[延期] Optional Product-Shell Parity**

### 当前 10 张迁移票
1. Runtime topology import
2. Database import
3. Services import
4. Protocol import
5. MRP import
6. Knowledge substrate import
7. MCP / routers / backend surfaces import
8. Wiring recovery
9. Boot / smoke-run recovery
10. Import-vs-runability boundary freeze

## 6. 与现有治理 stories 的关系
### `CYG-6 ~ CYG-17`
保留，不删。

它们代表的是：
**Cygnus support verticalization / governance surface**

它们不再代表：
- 当前第一个工程主线
- Arkon 基底迁移票
- backend parity 票

### `CYG-18 ~ CYG-22`
这些票保留为：
- bootstrap history
- selective-extraction reconnaissance

但不再代表当前主迁移策略。

## 7. completion truth
必须分清四个完成态：

### A. Source parity completed
意味着：
- Arkon baseline 代码已迁入

不意味着：
- 系统已启动
- Cygnus 已完成

### B. Runability recovered
意味着：
- baseline 最小可接线、可启动、可 smoke-run

不意味着：
- support verticalization 已完成

### C. Internalization completed
意味着：
- Cygnus 已开始以自己的工程身份接管这套 substrate
- 关键 runtime identity residue 已被切掉或明确隔离

不意味着：
- support verticalization 已完成
- optional shell parity 已完成

### D. Cygnus verticalization completed
意味着：
- support-domain 主语、治理闭环、产品 surfaces 已开始真正建立

### 7.1 状态汇报契约
后续在 Jira 评论、handoff、日志、结项说明里，必须显式带阶段语义：

- **P1** 只允许表述为：`source parity imported` / `baseline mirrored` / `upstream topology preserved`
- **P2** 只允许表述为：`runability recovered` / `wiring restored` / `boot or smoke-run regained`
- **P2.5** 只允许表述为：`internalized substrate` / `upstream cutover started` / `Cygnus-owned runtime identity established`
- **P3** 只允许表述为：`support verticalization implemented` / `governance surface established`

禁止把下面四句话当成同义词混用：
- 代码已迁入
- 系统已跑通
- 基底已内化
- 产品已 support 化

### 7.2 Jira 父子票解释契约
- `CYG-23` 代表 **P1 full-port baseline 父线**，其子票完成表示对应基底已镜像，不表示系统可运行
- `CYG-24` 代表 **P2 runability recovery 父线**，其子票完成才允许宣称某条接线或启动路径恢复
- `CYG-6 ~ CYG-17` 仍然是 **P3 support verticalization stories**，不能因为 P1 子票完成就被视为已实现
- `CYG-23 ~ CYG-25` 这类父线票不能因为单张子票完成就被误读成整条迁移线完成

## 8. 一句话结论
**Cygnus 的产品真相没有变；变的是工程落地顺序。**

现在正确顺序是：
**先 full-port baseline，再 runability recovery，再 support verticalization。**
