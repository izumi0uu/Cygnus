# Cygnus 前端设计系统 — Restrained Ops（现行）

> **基调文档(UI / UX)。现行设计语言为 Restrained Ops;下方"Command Brutalism"原文已废弃(superseded),仅作历史参考。**
> 实现真相以 `frontend/src/index.css` 的 token 为准;术语见根目录 `CONTEXT.md`。

## 0. 一句话基调（Restrained Ops）
**Restrained Ops** —— 给"支持治理指挥塔"用的、**克制、信号优先、可长时间盯**的 ops 界面语言。取代早先的 Command Brutalism(满屏硬阴影 + 满屏 2px 黑描边 + 高饱和),因为后者像 demo/dribbble,且违反 `visual-language.md` 的"避免花哨阴影、语义色是信号不是装饰"。

**核心规则**
1. **表面靠层级与发丝边分隔,不靠阴影**:`background / surface / surface-muted` 三层 + 1px hairline `--border`;**无硬阴影**;仅覆盖层(抽屉/模态)用一层极淡软阴影 `--overlay-shadow`。
2. **双主题跟随系统**:深/浅都做到位(`:root` = 浅 "paper",`.dark` = 深);组件不写 `dark:` 变体,全走 CSS 变量。landing 营销页仍固定深色。
3. **紫色 `#A826FF` 稀用**:仅主命令按钮 / 选中 / focus 环。
4. **语义/风险色仅作信号**:`trust/aligned/caution/critical` + `heat-urgent/high/medium/low`,只用于 chip(tint+描边)、风险卡左缘 3px 细条、计数色——不作大色块背景。
5. **唯一触感签名**:主命令按钮 `:active { translate(1px,1px) }`;其余 flat。尊重 `prefers-reduced-motion`。
6. **排版**:display=Space Grotesk(标题克制使用)/ sans=Inter / mono=JetBrains Mono(ID·enum·命令·数字)。间距 4px 基,卡片 padding 12–16,命令路径周边 ≥20。

**组件**:`.panel`/`.panel-lead`、`.btn-command`(flat 紫 + 轻按压)、`.btn-secondary`、`.icon-btn`、`.chip`(扁平,heat 为 tint 信号)、`.cmd-pill`(outline 预览态命令)、`.drawer`(唯一软阴影)、`.rail`(Command Horizon 带)、`.ribbon`(底栏)。

**UX 原则**(沿用 `interaction-principles.md`):System before Object / Coordinate before Edit / Every Action Has Scope(命令前先看 Consequence Lens 作用域)/ Drill-down 保持指挥姿态。

---

<!-- ===== 以下为已废弃的 Command Brutalism 原文(superseded,历史参考)===== -->

# （已废弃）Cygnus 前端设计系统 — Command Brutalism

> 基调文档(UI / UX)。本文是前端的**唯一基调来源**;实现时所有颜色、阴影、间距、动效都从这里取令牌。
> 它**取代** `visual-language.md` 的美学方向(原"sober mission control / 不要紫色 / 不要发光"),但**保留**其治理语义与信息密度要求。冲突以本文为准,`visual-language.md` 应标记为 superseded。

---

## 0. 一句话基调
**Command Brutalism** —— 给"支持治理指挥塔"用的、**有触感、敢用色、命令感强**的界面语言。
- 参考来源:紫色硬阴影按钮(`#A826FF` + `5px 5px 0 #8C20D4` + 按下位移 + 悬停揭示)。
- 把那种"按下去有实体反馈"的手感,变成本产品**发出治理命令**时的核心体验。

### 融合三件事(为什么是这个基调)
1. **品牌层 = 紫色 + 硬阴影**(参考件):身份、主操作、命令按钮、聚焦的指挥卡片。让"发命令"像按下一个实体键。
2. **治理语义层**(沿用旧文档,功能必需):urgent/drift/audience/source/recovery 的红黄蓝绿,作为状态色与 chip,不抢品牌。
3. **指挥密度层**(沿用 wireframe 文档):Command Frame 布局、风险重排、爆炸半径、恢复证明 —— 信息密度高,但命令路径更高。

---

## 1. 画布决策:Light "Paper" 为默认,Dark 为长时作业变体
参考件是 **light + 硬阴影** 的 neo-brutalism,所以:
- **默认 = Light "Paper"**:暖白纸面 + 近黑墨水描边(2px)+ 硬阴影。最忠实于参考,且区别于"满屏深色 dashboard"。
- **Dark = 长时 ops 变体**:近黑画布,紫色提亮,硬阴影改为紫/边框抬升。保留同一品牌身份。
- 两套都用 CSS 变量切换(见 §9),组件不写 `dark:` 变体。

---

## 2. 色彩系统(令牌)

### 2.1 Primary — 品牌紫(hue ≈ 276)
| Token | Hex | HSL | 用途 |
|---|---|---|---|
| `primary-50` | `#F6ECFF` | `276 100% 97%` | 极浅底/hover 背景 |
| `primary-100` | `#EBD6FF` | `276 100% 94%` | 选中底 |
| `primary-200` | `#D9B3FF` | `276 100% 87%` | 浅描边 |
| `primary-300` | `#C285FF` | `276 100% 78%` | disabled 主色 |
| `primary-400` | `#B55CFF` | `276 100% 68%` | hover 主色 |
| **`primary-500`** | **`#A826FF`** | `276 100% 57%` | **品牌主色(参考件)** |
| **`primary-600`** | **`#8C20D4`** | `276 74% 48%` | **硬阴影色 / active(参考件)** |
| `primary-700` | `#7019AA` | `276 75% 38%` | 按下描边 |
| `primary-800` | `#551480` | `276 70% 30%` | 深底 |
| `primary-900` | `#3B0E5A` | `276 65% 22%` | 极深 |
| `primary-950` | `#25073B` | `276 70% 14%` | dark 画布点缀 |

> 关键关系:**硬阴影色就是 `primary-600`**。命令按钮的 `box-shadow: 4px 4px 0 var(--primary-600)` 是签名。

### 2.2 Neutrals — Paper / Ink(暖中性)
| Token | Hex | 用途 |
|---|---|---|
| `paper` | `#FBFAF6` | Light 画布(暖白) |
| `surface` | `#FFFFFF` | 卡片面 |
| `ink-900` | `#16110F` | 正文/描边(近黑暖) |
| `ink-700` | `#3A332F` | 次要正文 |
| `ink-500` | `#6B635D` | 辅助/metadata |
| `ink-300` | `#A9A199` | 占位/分隔 |
| `ink-100` | `#ECE8E2` | 浅分隔/底 |
| `night` | `#141017` | Dark 画布(微紫黑) |
| `night-surface` | `#1E1822` | Dark 卡片面 |

### 2.3 治理语义色(必须共存,功能性,不抢品牌)
| 语义 | Token | Hex | 前景 | 含义 |
|---|---|---|---|---|
| trusted / 受控 | `trust` | `#2D6FF0` | white | 已治理/可信/已发布 |
| aligned / 恢复 | `aligned` | `#1FA971` | white | 收敛/已传播/对齐 |
| caution / 等待 | `caution` | `#E8930C` | ink | 协调中/待审/陈旧可用 |
| critical / 紧急 | `critical` | `#DC2626` | white | 紧急/阻塞/高漂移 |

### 2.4 Urgency Heat(Priority Stack / Atlas 用)
| 级别 | Token | Hex | 对应 |
|---|---|---|---|
| urgent | `heat-urgent` | `#DC2626` | = critical |
| high | `heat-high` | `#EA6A0C` | 橙 |
| medium | `heat-medium` | `#E8930C` | = caution |
| low | `heat-low` | `#2D6FF0` | = trust |

> Risk Type(audience_mismatch / drift / source_blindness / ticket_pressure / policy_conflict / owner_gap)用**图标 + mono 标签**区分类别,用 **urgency heat** 表达温度——避免再造 6 个色相。

### 2.5 可达性(WCAG)
- 正文 4.5:1、大字/UI 3:1。`primary-500` 上用白字(≈4.6:1,达标);`caution`/amber 上用 **ink** 而非白。
- 每个背景色都配 `-foreground`(见 §9 令牌)。

---

## 3. 签名装置:硬阴影 + 触感命令(基调的心脏)

### 3.1 阴影令牌(硬阴影,无模糊)
```
--shadow-command:    4px 4px 0 0 var(--primary-600);   /* 主命令/品牌 */
--shadow-command-lg: 6px 6px 0 0 var(--primary-600);   /* hero 指挥面 */
--shadow-ink:        4px 4px 0 0 var(--ink-900);        /* 中性结构卡 */
--shadow-pressed:    2px 2px 0 0 var(--primary-600);    /* 按下态 */
--shadow-critical:   4px 4px 0 0 #991B1B;               /* 危险命令 */
```

### 3.2 描边 / 圆角
- `--border-brutal: 2px solid var(--ink-900)`(品牌件可用 `primary-700`)。
- `--radius: 10px`(参考件原值);小件 8px,大面 12px。

### 3.3 触感交互规范(核心体验)
- **默认**:`box-shadow: var(--shadow-command)`。
- **hover**:主色提亮到 `primary-400`(品牌件);阴影不变。
- **active / 按下**:`transform: translate(2px,2px); box-shadow: var(--shadow-pressed)`,`--dur-press` 内完成 —— 像把实体键按下去。
- **playful reveal**(参考件的图标滑入):仅用于**轻量/可逆**操作(如展开、切换),`--dur-reveal`;**治理命令(发布/限制/升级)不用花哨揭示**,要稳、要直给。
- **focus-visible**:硬偏移焦点环 `0 0 0 3px var(--primary-200)` + 2px 描边,绝不去掉(可达性)。

> 原则:**命令要有实体感,但越高风险越克制**。按钮可以"按下去",但"对 12 万外部受众发布"不该有可爱动画。

---

## 4. 排版
| 角色 | 字体栈 | 字重 | 用途 |
|---|---|---|---|
| display | `"Space Grotesk", "Geist", system-ui` | 600/700 | 标题、Situation Frame、命令面标题 |
| sans | `"Geist", "Inter", system-ui` | 400/500 | 正文、卡片 |
| mono | `"Geist Mono", "JetBrains Mono", ui-monospace` | 500 | ID、enum、命令 token、风险类型标签 |

- 类型阶:`12 / 13 / 14 / 16 / 18 / 22 / 28 / 36`(line-height 1.25–1.45)。
- 数据/ID/命令一律 mono —— 这是治理产品,屏上全是 `cp-source-1` / `restrict_publish` / `external · billing · eu`。

---

## 5. 间距 / 布局 / 密度
- 间距阶(4px 基):`4 / 8 / 12 / 16 / 20 / 24 / 32 / 48`。令牌 `--space-1..8`。
- **密度规则**:这是高密 ops 工具,默认紧凑(卡片内边距 12–16,行高紧),但**命令路径留白更多**(主操作周围 ≥20)。
- **Command Frame**(沿用 wireframe 文档,本基调重皮):
  - Command Horizon(顶,全局健康/周期)
  - Situation Frame(简报带)
  - Priority Stack(入口,风险重排)
  - Atlas Field(主舞台,空间风险图)
  - Recovery Tower(右,恢复证明 —— 规划中/E4)
  - Active Command Shadow + Command Ribbon(未闭合战线)

---

## 6. 动效
```
--ease-command: cubic-bezier(0.2, 0.8, 0.2, 1);  /* snappy */
--dur-press:  120ms;   /* 按下 */
--dur-base:   200ms;   /* 一般过渡 */
--dur-reveal: 300ms;   /* 轻量揭示 */
```
- 仅过渡 `transform / box-shadow / color / background`(便宜属性)。
- **`prefers-reduced-motion`**:禁用 transform 位移与 reveal,仅保留颜色/阴影瞬时切换。

---

## 7. 组件清单(基调下的处理)
| 组件 | 处理 |
|---|---|
| **Command Button(primary)** | 紫底白字 + `--shadow-command` + 触感按下;用于发命令(open review / restrict / publish) |
| **Secondary Button** | 白底 ink 描边 + `--shadow-ink`;次要动作 |
| **Destructive/Governance Button** | critical 红 + `--shadow-critical`;高风险(force / freeze)需二次确认,不加 reveal |
| **Risk Card(Priority Stack)** | 2px 描边卡 + urgency heat 左条 + `--shadow-ink`;首项 `--shadow-command-lg` 强调 |
| **Chip — risk type** | mono 标签 + 图标,中性描边 |
| **Chip — urgency** | heat 实底/描边 |
| **Chip — owner state** | unassigned=caution 警示;assigned=ink 次要;escalated=critical |
| **Situation Frame** | 顶部宽带,display 字体,左侧 critical 强调块 |
| **Command Ribbon** | 底部常驻条,最高风险提醒 + 未闭合计数 |
| **Atlas node** | 圆/方节点,urgency 上色,urgent 带脉冲环(reduced-motion 下静止) |

> 落地建议用 **shadcn/ui** 作底,再以本令牌覆盖(button/card/badge 重写 variant 为 brutalist)。

---

## 8. UX 原则(沿用 interaction-principles,基调下重述)
1. **Coordinate before Edit** —— 先判断优先级/路由,别一上来塞内容编辑。
2. **Every Action Has Scope** —— 每个命令显示触及的 objects / audiences / surfaces(爆炸半径)。
3. **Commands feel tactile, risk stays sober** —— 命令有实体按压感;风险越高,反馈越克制、越要二次确认。
4. **Propagation Confirmation, not toast** —— 发布后给传播路径与卡点,不是一句"成功"。
5. **Conflict Exposure** —— 来源失明/受众冲突要显式可见,不为顺滑而藏。
6. **Drill-down preserves posture** —— 可下钻到证据,但始终让用户知道自己在"指挥"。

---

## 9. 落地令牌(Tailwind v4,可直接用)
> 架构:`:root`/`.dark` 定义变量 → `@theme inline` 映射 → 工具类。**不要**把 `:root` 放进 `@layer base`,**不要**双重 `hsl()` 包裹。

```css
@import "tailwindcss";

:root {
  --radius: 10px;

  --paper: hsl(48 33% 97%);
  --surface: hsl(0 0% 100%);
  --background: var(--paper);
  --foreground: hsl(20 14% 8%);

  --primary: hsl(276 100% 57%);
  --primary-foreground: hsl(0 0% 100%);
  --primary-active: hsl(276 74% 48%);

  --border: hsl(20 14% 8%);
  --muted-foreground: hsl(25 8% 40%);

  --trust: hsl(217 87% 56%);        --trust-foreground: hsl(0 0% 100%);
  --aligned: hsl(152 69% 39%);      --aligned-foreground: hsl(0 0% 100%);
  --caution: hsl(38 90% 48%);       --caution-foreground: hsl(20 14% 8%);
  --critical: hsl(0 72% 51%);       --critical-foreground: hsl(0 0% 100%);

  --heat-urgent: hsl(0 72% 51%);
  --heat-high:   hsl(24 90% 48%);
  --heat-medium: hsl(38 90% 48%);
  --heat-low:    hsl(217 87% 56%);

  --shadow-command:    4px 4px 0 0 var(--primary-active);
  --shadow-command-lg: 6px 6px 0 0 var(--primary-active);
  --shadow-ink:        4px 4px 0 0 var(--foreground);
  --shadow-pressed:    2px 2px 0 0 var(--primary-active);
  --shadow-critical:   4px 4px 0 0 hsl(0 63% 35%);
}

.dark {
  --paper: hsl(276 30% 8%);
  --surface: hsl(276 22% 12%);
  --background: var(--paper);
  --foreground: hsl(40 20% 94%);
  --primary: hsl(276 100% 68%);
  --primary-foreground: hsl(276 70% 10%);
  --primary-active: hsl(276 90% 60%);
  --border: hsl(40 20% 94%);
  --muted-foreground: hsl(35 10% 65%);
  --shadow-ink: 4px 4px 0 0 hsl(276 90% 60%);
}

@theme inline {
  --radius-lg: var(--radius);
  --color-background: var(--background);
  --color-foreground: var(--foreground);
  --color-surface: var(--surface);
  --color-primary: var(--primary);
  --color-primary-foreground: var(--primary-foreground);
  --color-border: var(--border);
  --color-trust: var(--trust);
  --color-aligned: var(--aligned);
  --color-caution: var(--caution);
  --color-critical: var(--critical);
  --font-display: "Space Grotesk", "Geist", system-ui, sans-serif;
  --font-sans: "Geist", "Inter", system-ui, sans-serif;
  --font-mono: "Geist Mono", "JetBrains Mono", ui-monospace, monospace;
}

@layer base {
  body { background-color: var(--background); color: var(--foreground); font-family: var(--font-sans); }
}
```

签名按钮(brutalist)参考实现:
```css
.btn-command {
  border: var(--border-brutal, 2px solid var(--primary-active));
  border-radius: var(--radius);
  background: var(--primary);
  color: var(--primary-foreground);
  font-weight: 600;
  box-shadow: var(--shadow-command);
  transition: transform var(--dur-press,120ms) var(--ease-command, ease),
              box-shadow var(--dur-press,120ms) var(--ease-command, ease),
              background var(--dur-base,200ms);
}
.btn-command:hover  { background: hsl(276 100% 68%); }
.btn-command:active { transform: translate(2px,2px); box-shadow: var(--shadow-pressed); }
.btn-command:focus-visible { outline: none; box-shadow: var(--shadow-command), 0 0 0 3px hsl(276 100% 87%); }
@media (prefers-reduced-motion: reduce) {
  .btn-command { transition: background var(--dur-base,200ms); }
  .btn-command:active { transform: none; }
}
```

---

## 10. 技术栈落地建议
- **React + TS + Vite + Tailwind v4 + shadcn/ui**(与本仓 skills 生态一致),token 用 §9 的四步架构。
- 参考件用的是 styled-components;若选 styled-components,把 §9 的 CSS 变量放到 `:root`,组件读 `var(--…)` 即可,令牌不变。
- 数据来源:已就绪的 `GET /api/command-center`(`cygnus/api`),返回真实 payload。

---

## 11. 待确认 / open
- **Light vs Dark 默认**:本文定 Light Paper 为默认,Dark 为变体。若你更想要"深色指挥台优先",一句话我翻转默认。
- **字体**:Space Grotesk / Geist 是建议,可换(Satoshi / Clash / 系统)。
- **en 镜像**:本文先出中文;需要我同步 `docs/en/frontend-design-system.md` 再说。
- **supersede**:`visual-language.md` 的美学方向已被本文取代,待标注。
