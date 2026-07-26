# Cygnus — Story 到 Substrate 的映射计划

> **状态：映射仍可作参考，但阶段账已收口（2026-07）。** P1/P2/P2.5 与 CYG-6~17 的三个 P3 波次均已关闭；§9 的「当前工程入口」结论已过时。当前主线是会话接缝（CYG-92~96），其工程前置是 governed 平面从 sample fixtures 切换到内化 substrate 真相；见 `docs/README.md`。

## 1. 文档用途
这份文档用于把 **Jira 上的治理产品 stories** 与 **Arkon → Cygnus 的工程迁移阶段** 重新对齐。

它回答的不是“产品是什么”，也不是“某个模块怎么编码”，而是：

**一条治理 story 什么时候才真正值得开发，它之前必须先完成哪一层 Arkon 基底迁移。**

## 2. 为什么这份文档必须重写
Cygnus 的工程主线已经变化：

- 旧主线：`domain-first selective extraction`
- 新主线：**Arkon full-port baseline → runability recovery → support verticalization**

因此，这份映射文档也不能再把 `CYG-6 ~ CYG-17` 当成“当前第一批代码主线”。

新的正确关系是：
- `CYG-23+` 代表当前工程主线
- `CYG-6 ~ CYG-17` 代表后续 **P3 support verticalization** 的治理 surfaces
- `CYG-18 ~ CYG-22` 保留为 bootstrap 历史，而不是当前迁移真相

## 3. 两条顺序线必须分开看

### 3.1 产品顺序线
这是 support lead 最终应先感知到的治理迁移顺序：
1. Review 变成 Command Brief
2. Publish 变成 Blast-Radius Control
3. Ticket / Drift 变成 Review Pressure
4. Propagation 变成 Recovery Proof

### 3.2 工程顺序线
这是当前 Cygnus 必须先遵守的工程顺序：
1. **P0 — Migration Manifest & Boundary Freeze**
2. **P1 — Source Parity Import**
3. **P2 — Repair / Runability Recovery**
4. **P2.5 — Internalization & Upstream Cutover**
5. **P3 — Support Verticalization**
6. **P4 — Optional Product-Shell Parity**

### 3.3 正确理解
因此，正确关系不是：
- `CYG-6` 在 Jira 里排得早，所以先做它的页面

而是：
- `CYG-6 ~ CYG-17` 是未来 support verticalization 的产品主线
- 但它们必须建立在 **P1/P2 的 Arkon 基底已经迁入并重新接通** 的前提上

## 4. 各阶段在映射中的作用

### P0 — Migration Manifest & Boundary Freeze
提供：
- 迁移范围定义
- 非迁移范围定义
- import / runability / verticalization 的边界定义

没有它时，Jira 很容易再次把：
- 产品 story
- 全量迁移任务
- 跑通修复任务

混成同一类票。

### P1 — Source Parity Import
提供：
- Arkon backend/runtime/worker 的源码版图
- provider-neutral protocol 与 providers
- MRP pipeline、wiki/compiler/retrieval、routers/mcp/services/database 的 upstream 拓扑

没有它时，任何治理 UI 都容易漂成：
- 假命令面
- 假传播回显
- 假压力入口

### P2 — Repair / Runability Recovery
提供：
- dependency/config/storage/queue/db wiring 的重新接通
- API/worker/MRP resume path 的最小可启动能力

没有它时，P3 的 story 仍然只能停留在：
- fixture
- static frontends
- 无法回证运行真相的控制面

### P2.5 — Internalization & Upstream Cutover
提供：
- runtime identity residue cleanup
- app assembly convergence
- namespace / ownership freeze
- docs/tests/handoff truth sync
- 删除独立 Arkon 代码基座前的明确切口

没有它时，团队很容易继续卡在：
- 双入口 / 双真相
- 运行时仍暴露 `arkon` 身份残留
- 以为“全量迁移完成”就等于“Cygnus 已完全接管 substrate”

### P3 — Support Verticalization
提供：
- support-native object 主语
- review/publish/recovery 的治理 surfaces
- Cygnus 自己的 support 领域控制面

现有 `CYG-6 ~ CYG-17` 归属于这个阶段。

### P4 — Optional Product-Shell Parity
提供：
- Arkon 壳层 parity 的后续决策空间

它不是当前 P1/P2/P3 的前置条件。

## 5. Story 到阶段的总映射

| Jira | Story 简述 | 最早可启动阶段 | 真正成型阶段 | 主要依赖 |
|---|---|---:|---:|---|
| CYG-6 | Review 首屏先呈现治理风险 | P3（晚） | P3 | review substrate、risk ranking、retrieval trace、command surface |
| CYG-7 | 每条审阅项先解释 why-now | P3（晚） | P3 | evidence context、source trace、lifecycle context |
| CYG-8 | 审阅顺序可重排/转交/升级 | P3（晚） | P3 / P4 | review queue semantics、command chain、residual trace |
| CYG-9 | Publish 前预览 blast radius | P3 | P3 / P4 | audience model、publish policy、propagation surfaces |
| CYG-10 | Publish 不只 approve/reject | P3 | P3 / P4 | action granularity、variant routing、governance commands |
| CYG-11 | Publish 后显示传播成功/阻塞 | P3 | P3 / P4 | publish ledger、propagation state、supporting surfaces |
| CYG-12 | rewrite/ticket 上升为审阅压力 | P3（早） | P3 | evidence clustering、object proposal、pressure intake |
| CYG-13 | drift 强制打开 urgent review path | P3 | P3 / P4 | drift model、freeze/restrict path、refresh governance |
| CYG-14 | source failure 被解释为治理失明 | P3（早） | P3 | source trace、evidence health、object impact mapping |
| CYG-15 | supporting surfaces 回报行为变化 | P3（中后） | P3 / P4 | downstream trace、feedback ingestion、command-result linkage |
| CYG-16 | Recovery Window 判断系统是否更一致 | P3（后） | P4 | workflow trace、metrics、before/after recovery signals |
| CYG-17 | 比较多个 open loops 决定下一步 | P3（后） | P4 | multi-loop state、residual risk comparison、governance overview |

## 6. 工程先决条件映射

### 6.1 P1 直接支撑的能力
P1 全量迁入后，Cygnus 至少应该拥有：
- main/config/worker topology
- database / services / routers / mcp baseline
- ai/providers/agent protocol baseline
- ai/mrp pipeline baseline
- wiki/compiler/retrieval/source trace baseline

这不是为了“立刻跑通”，而是为了让 P3 不再空心。

### 6.2 P2 直接支撑的能力
P2 跑通修复后，Cygnus 才开始具备：
- API/worker 的 smoke-run 能力
- queue / storage / db 的最小可接线能力
- pipeline phase / resume truth 的运行验证能力

这意味着：
- P3 的 command surface 才能引用真实状态
- P3 的 propagation / recovery 才能逐步摆脱纯静态表达

### 6.3 P2.5 直接支撑的能力
P2.5 内化完成后，Cygnus 才开始具备：
- 以 `Cygnus` 自己的工程身份持有这套 substrate
- 更少的 runtime identity residue 与更清晰的 public entry 边界
- 删除独立 Arkon 代码基座前可验证的 cutover readiness

这意味着：
- 后续 P3 不再建立在“仍依赖外部 Arkon 身份”的过渡真相上
- 任何 support-native 重构都能建立在更稳定的 Cygnus-owned substrate 之上

## 7. `CYG-6 ~ CYG-17` 的推荐开发波次

### 第一批（P3 early wave）
1. **CYG-12** — ticket / rewrite 变成审阅压力
2. **CYG-14** — source failure = governance blindness
3. **CYG-6** — review 首屏 command brief
4. **CYG-7** — why-now frame

原因：
- 这四条最能体现 Cygnus 是从 Arkon substrate 长出来的 support governance center
- 它们更强调 intake / trace / review，而不是最复杂的恢复编排

### 第二批（P3 middle wave）
5. **CYG-9**
6. **CYG-10**
7. **CYG-11**
8. **CYG-15**

原因：
- 这批开始要求 publish consequences 与 downstream result linkage
- 需要 P1/P2 已经让 publish / propagation 拥有真实基底

### 第三批（P3 late / P4-ready wave）
9. **CYG-13**
10. **CYG-16**
11. **CYG-17**
12. **CYG-8**

原因：
- 这批最接近 durable governance orchestration
- 容易被过早做成假 dashboard 或假 command center
- 更适合在 P3 成熟后、必要时再吸收 P4 的壳层/编排能力

## 8. `CYG-23+` 与 `CYG-6~17` 的关系

### `CYG-23`
代表：
- **P1 full-port baseline** 的主题父线

### `CYG-24`
代表：
- **P2 repair/runability** 的主题父线

### `CYG-25`
代表：
- **P4 optional shell parity** 的延后父线

### `CYG-6 ~ CYG-17`
代表：
- **P3 support verticalization / governance surfaces**

因此当前执行顺序应是：
- 先把 `CYG-23/24` 相关迁移票推进
- 如果目标是完整吸收 Arkon 并删除独立上游代码基座，再进入 P2.5 内化迁移线
- 再开始真正把 `CYG-6~17` 作为项目开发主线

## 9. 一句话结论
**治理 story 依然成立，但它们不再是当前第一个工程入口；当前工程入口已经扩展为 Arkon full-port baseline import → runability recovery →（当目标是完整吸收上游时）internalization。**

