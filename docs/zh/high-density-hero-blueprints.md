# Support Brain for SaaS — 高密 Hero 蓝图

## 1. 这份文档解决什么问题
前一轮已经做完：
- 3 套差异很大的 low-fi 核心方案
- 哪些部分值得混合

这份文档继续向前推进一层，直接回答：
**如果现在进入真正的产品推进，首页 hero 区和协调页 hero 区应该长成什么样。**

这里不再讨论三选一，而是落地推荐混合方向：
- **Command Center = Briefing Stack + Risk Atlas**
- **Coordination Board = Command Corridor + Risk Atlas**

---

## 2. 为什么是这两个混合体

### Command Center 选择 A + C
因为首页需要同时满足两件事：
1. support lead 必须能在 10 秒内看懂今天最该出手的事
2. 产品又必须长得不像普通运营首页

所以首页 hero 区的结构逻辑是：
- 用 **A** 的 briefing hierarchy 保证可读性
- 用 **C** 的 atlas 感保证辨识度

### Coordination Board 选择 B + C
因为协调页的本质不是看列表，而是：
- 进入一条明确 command path
- 在风险战场里判断关系、责任、动作和后果

所以协调页 hero 区的结构逻辑是：
- 用 **B** 的 corridor 保证动作连续性
- 用 **C** 的 battlefield 保证 risk reasoning 的空间感

---

## 3. Hero 01 — Command Center / Briefing Atlas

## 3.1 结构命题
首页不应该是：
- 数据总览
- KPI 首页
- 卡片墙

首页 hero 应该像：
**“晨间战情简报压在一张风险地图之上。”**

也就是说：
- 简报决定用户先看什么
- 地图决定用户如何理解这不是孤立事件

## 3.2 Hero 区必须同时出现
- Command Horizon
- Situation Frame
- Priority Stack
- Atlas Field
- Active Command Shadow
- Recovery Tower
- Command Ribbon

## 3.3 主战场规则

### 主战场
`Atlas Field`

### 主阅读顺序
1. Situation Frame
2. Priority Stack 第一项
3. Atlas 中最危险的风险地貌
4. Recovery Tower
5. Active Command Shadow

### 结构重点
- `Priority Stack` 不是页面主战场，而是主战场入口
- `Atlas Field` 才是首页 hero 的空间中心
- `Recovery Tower` 不应被压扁成 KPI 小块
- `Command Shadow` 必须让用户感知“系统还有未闭合战线”

## 3.4 Hero 区块定义

### A. Situation Frame
一句话写明：
- 今天最重要 tension 是什么
- 为什么它比其他 front 更优先

### B. Priority Stack
保留 3 层，但第一项显著大于其余两项。
第一项应直接对应 atlas 上的最强风险带。

### C. Atlas Field
Atlas 不是装饰背景，而是支持下面几种阅读：
- queue pressure → topic conflict → audience split → surface spread
- 哪个 front 在扩大
- 哪个 front 已有 active command
- 哪个 front 只是正在成形

### D. Recovery Tower
右侧垂直塔形结构。
它的作用不是显示结果，而是显示：
- 最近几轮命令是 closed / partial / blocked 哪种状态
- 控制塔是否真的在扭转系统

### E. Active Command Shadow
告诉用户：
- 哪些问题还没闭合
- 下一条命令大概率要回到哪里

## 3.5 状态变形

### 当 `Leadership Intervention Overdue`
- Priority Stack 第一项高度增加
- Atlas 中主风险带变得更集中
- Recovery Tower 降低存在感，让当前 front 接管

### 当 `Calm / Stable`
- Atlas 变浅
- Recovery Tower 更突出
- Active Command Shadow 收缩为细条

### 当 `Multi-surface Spread`
- Atlas 中 surface 区域必须被显式点亮
- Priority Stack 与 Atlas 之间的对应关系更强

---

## 4. Hero 02 — Coordination Board / Battle Corridor

## 4.1 结构命题
协调页不应该像：
- 队列派发台
- 责任分派页
- 一个更复杂的 review queue

它应该像：
**“一条命令走廊穿过一片风险战场。”**

也就是说：
- 用户不是先看任务，而是先进入战区
- 一旦进入战区，动作路径是连续的

## 4.2 Hero 区必须同时出现
- Command Horizon
- Horizontal Command Spine
- Situation Frame
- Battlefield Graph
- Corridor Path
- Owner / Load Dock
- Intervention Dock
- Consequence Dock
- Command Ribbon

## 4.3 主战场规则

### 主战场
`Battlefield Graph`

### 主动作连续层
`Corridor Path`

### 主阅读顺序
1. Situation Frame
2. Battlefield 中的冲突中心
3. Owner / Load
4. Intervention
5. Consequence

### 结构重点
- Battlefield 是“为什么值得出手”的空间证明
- Corridor 是“应该怎么动”的连续结构
- 右侧 dock 不是附属说明，而是 authority wall

## 4.4 Hero 区块定义

### A. Horizontal Command Spine
比左侧 rail 更适合这个混合版。
因为这里用户已经进入一条动作链，顶部连续条更能强调节奏推进。

### B. Battlefield Graph
Battlefield 要展示至少四类节点：
- object
- audience
- source
- affected surface / owner pressure

节点之间不是静态关系，而是：
- 哪个边界正在撕裂
- 哪个 source 正在拉低置信度
- 哪个 surface 会被错误传播击中

### C. Corridor Path
在 battlefield 下方或中轴处，清楚给出：
- Route
- Restrict
- Review
- Publish Gate
- Propagate

它像一条即将执行的战术命令带。

### D. Authority Dock
右侧分成三层：
1. Owner / Load
2. Intervention Ladder
3. Consequence Lens

这样用户在一次视线移动中就能完成：
“谁来动 → 怎么动 → 后果是什么”

## 4.5 状态变形

### 当 `Ambiguous Ownership`
- Owner / Load Dock 扩大
- Battlefield 上 owner pressure 节点更突出

### 当 `No Safe Route Yet`
- Corridor Path 中危险动作被压暗
- Consequence Lens 抬升为更强视觉层

### 当 `Conflict Across Audiences`
- Battlefield 中 audience 节点分裂显著化
- Interventions 更偏向 split / hold，而非 publish

---

## 5. 两个 Hero 的共同密度原则

### 原则 1：信息密度高，但命令路径更高
可以有很多信息，但用户必须迅速知道：
- 现在最危险的 front 是什么
- 该不该动
- 下一步怎么动

### 原则 2：地图 / 战场不是装饰，而是判断工具
只要风险地貌不能帮助用户决定动作，它就不该占主战场。

### 原则 3：恢复必须持续可感知
即使在首页 hero，也要能感觉到过去命令的结果与残留。

### 原则 4：一切支撑面都服务 control tower
copilot、surface、source、owner 都是 support lead 决策的支撑证据，不是主角。

---

## 6. 对后续实现的意义
这两个高密 hero 一旦定下来，后续：
- 组件树
- token 语义
- 布局系统
- loading / stale / blocked 状态

都会更容易锁定。

因为最难的不是“画得好看”，而是：
**让 Cygnus 首页和协调页从第一眼就不像别的产品。**
