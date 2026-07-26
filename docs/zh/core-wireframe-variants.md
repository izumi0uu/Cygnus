# Support Brain for SaaS — 核心线框三方案

## 1. 这份文档是什么
这份文档把 `Command Center` 与 `Queue / Topic Coordination Board` 做成了 **3 套结构级差异明显** 的 low-fi 线框方案。

它们不是一版微调三次，而是 3 个完全不同的视觉组织逻辑：
- **Variant A — Briefing Stack**
- **Variant B — Command Corridor**
- **Variant C — Risk Atlas**

对应图稿文件：
- `docs/diagrams/cygnus-core-variant-briefing-stack.excalidraw`
- `docs/diagrams/cygnus-core-variant-command-corridor.excalidraw`
- `docs/diagrams/cygnus-core-variant-risk-atlas.excalidraw`

---

## 2. 三套方案的核心差异

| 方案 | 结构主角 | 适合什么场景 | 风险 | 我的判断 |
|---|---|---|---|---|
| Briefing Stack | 晨间简报层级 | 日常 leadership scan、日常运营 | 容易滑向 smart dashboard | 最稳的 baseline |
| Command Corridor | 单条指挥走廊 | 强调连续 command cycle、治理编排 | 可能偏“流程感” | 最强 command 感 |
| Risk Atlas | 风险地形 / 战区地图 | incident、drift、spread reasoning | 认知负担更高 | 最有辨识度 |

---

## 3. Variant A — Briefing Stack

### 核心想法
把首页做成真正的晨间战情 brief。
用户先看今天最值得介入的 3 件事，再看扩散面与恢复状态。

### 强项
- 最容易理解
- 最适合 support lead 每天早上打开
- 最不容易做坏

### 风险
- 如果视觉太保守，会逐渐长成高级 BI 首页

### 适合保留的东西
- 首页的 Priority Stack 层级
- Coordination 页的“左关系 / 右后果”结构

---

## 4. Variant B — Command Corridor

### 核心想法
把核心页面都做成一条连续 command runway。
用户不是在“浏览模块”，而是在沿一条指挥走廊往下走。

### 强项
- 最能体现 Observe → Frame → Route → Change 的连续性
- 最不像普通 dashboard
- 很适合和 future command history / propagation 统一

### 风险
- 如果做过头，会太像 workflow orchestrator
- 对地图式风险理解不如 Variant C 强

### 适合保留的东西
- 中轴 command runway
- 左右 sidecar 承载 evidence / recovery / owner

---

## 5. Variant C — Risk Atlas

### 核心想法
把“支持系统正在失衡的地形”做成第一主角。
不是先看列表，而是先看风险地貌。

### 强项
- 最有 mission-control 个性
- 最适合 release drift、incident spread、audience conflict 这类空间型问题
- 最不容易被误解为 CMS 或 review queue 产品

### 风险
- 设计难度最高
- 初次上手成本更高
- 如果没有足够好的信息抽象，可能显得炫而不实

### 适合保留的东西
- 首页 atlas + floating command islands
- Coordination 页的 battlefield + authority dock 结构

---

## 6. 我的建议
如果现在就要往真实产品推进，我建议：

### 推荐组合
- **Command Center：Variant A 与 Variant C 混合**
  - 用 A 的 briefing hierarchy
  - 借 C 的 atlas 感，但不要让 atlas 抢走所有可读性

- **Coordination Board：Variant B 与 Variant C 混合**
  - 用 B 的 command 连续性
  - 用 C 的 battlefield 感和 authority dock

### 不建议直接整套照搬
因为：
- A 全套太稳，辨识度可能不够
- B 全套太强流程，可能被误读成 orchestrator
- C 全套太强空间感，第一版实现风险最高

---

## 7. 下一步建议
如果你认可其中一版或一个混合方向，下一步最值的是：
1. 把选中的版本继续压成 **单页细化蓝图**
2. 再做 **Excalidraw 的局部高密版**（尤其首页 hero 区）
3. 然后才能进入前端 component contract
