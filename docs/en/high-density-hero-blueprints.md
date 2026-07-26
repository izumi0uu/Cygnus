# Support Brain for SaaS — High-Density Hero Blueprints

## 1. What this document solves
The previous pass already delivered:
- three strongly different low-fi core directions,
- a recommendation about what to blend.

This document moves one step further and answers:
**if the product starts becoming real now, what should the homepage hero and coordination hero actually look like?**

This is no longer a three-way comparison. It operationalizes the recommended blend:
- **Command Center = Briefing Stack + Risk Atlas**
- **Coordination Board = Command Corridor + Risk Atlas**

---

## 2. Why these two blends

### Why A + C for Command Center
The homepage must do two things at once:
1. a support lead must understand the most important move in about 10 seconds,
2. the product still must not look like a normal operations homepage.

So the homepage hero uses:
- **A** for briefing hierarchy and readability,
- **C** for atlas identity and mission-control differentiation.

### Why B + C for Coordination Board
The coordination screen is not mainly a list or assignment tool. It is where the user:
- enters a clear command path,
- judges relations, ownership, action, and consequence inside a risk battlefield.

So the coordination hero uses:
- **B** for command continuity,
- **C** for battlefield reasoning and spatial risk structure.

---

## 3. Hero 01 — Command Center / Briefing Atlas

## 3.1 Structural thesis
The homepage should not feel like:
- a data overview,
- a KPI landing page,
- a card wall.

The homepage hero should feel like:
**“a morning command briefing pressed onto a live risk map.”**

That means:
- the briefing decides what the user sees first,
- the atlas explains why the issue is not isolated.

## 3.2 Must coexist in the hero
- Command Horizon
- Situation Frame
- Priority Stack
- Atlas Field
- Active Command Shadow
- Recovery Tower
- Command Ribbon

## 3.3 Primary battlefield rules

### Primary battlefield
`Atlas Field`

### Primary reading order
1. Situation Frame
2. first item in Priority Stack
3. most dangerous terrain inside the atlas
4. Recovery Tower
5. Active Command Shadow

### Structural emphasis
- `Priority Stack` is not the battlefield itself; it is the battlefield entry point.
- `Atlas Field` is the spatial center of the homepage hero.
- `Recovery Tower` must not collapse into a tiny KPI tile.
- `Active Command Shadow` must make unresolved fronts feel present.

## 3.4 Hero block definitions

### A. Situation Frame
One sentence should state:
- today’s top tension,
- why it outranks the other fronts.

### B. Priority Stack
Keep 3 layers, but make the first visibly larger than the other two.
That first item should correspond directly to the strongest risk band inside the atlas.

### C. Atlas Field
The atlas is not a decorative background. It must support readings such as:
- queue pressure → topic conflict → audience split → surface spread,
- which front is widening,
- which front already has an active command,
- which front is only beginning to form.

### D. Recovery Tower
A right-side vertical tower.
Its role is not just to show results, but to show:
- which recent cycles were closed, partial, or blocked,
- whether the tower is actually changing the system.

### E. Active Command Shadow
This tells the user:
- which problems remain open,
- where the next command is likely to return.

## 3.5 State deformations

### When `Leadership Intervention Overdue`
- the first Priority Stack item grows,
- the main atlas front becomes more concentrated,
- Recovery Tower recedes so the urgent front takes over.

### When `Calm / Stable`
- the atlas becomes lighter,
- Recovery Tower becomes more prominent,
- Active Command Shadow compresses into a thinner strip.

### When `Multi-surface Spread`
- surface territory inside the atlas must be explicitly lit,
- the correspondence between Priority Stack and atlas becomes stronger.

---

## 4. Hero 02 — Coordination Board / Battle Corridor

## 4.1 Structural thesis
The coordination screen should not feel like:
- a queue dispatch page,
- a responsibility assignment panel,
- a more complicated review queue.

It should feel like:
**“a command corridor passing through a risk battlefield.”**

That means:
- the user does not enter a task list first; they enter a battle zone,
- once inside that zone, the action path stays continuous.

## 4.2 Must coexist in the hero
- Command Horizon
- Horizontal Command Spine
- Situation Frame
- Battlefield Graph
- Corridor Path
- Owner / Load Dock
- Intervention Dock
- Consequence Dock
- Command Ribbon

## 4.3 Primary battlefield rules

### Primary battlefield
`Battlefield Graph`

### Primary action continuity layer
`Corridor Path`

### Primary reading order
1. Situation Frame
2. conflict center inside the battlefield
3. Owner / Load
4. Intervention
5. Consequence

### Structural emphasis
- the battlefield is the spatial proof of why this deserves intervention,
- the corridor is the explicit structure for what to do next,
- the right dock is not supporting annotation; it is the authority wall.

## 4.4 Hero block definitions

### A. Horizontal Command Spine
This blend works better with a horizontal top strip than a left rail.
The user is already inside a move sequence, so a top progression reinforces momentum.

### B. Battlefield Graph
The battlefield should show at least four node classes:
- object,
- audience,
- source,
- affected surface / owner pressure.

The nodes should not simply show static relation; they should reveal:
- which boundary is tearing,
- which source is lowering confidence,
- which surface will be hit by the wrong spread.

### C. Corridor Path
Placed below or through the battlefield, clearly staging:
- Route
- Restrict
- Review
- Publish Gate
- Propagate

It should feel like a tactical command belt.

### D. Authority Dock
The right dock should split into three layers:
1. Owner / Load
2. Intervention Ladder
3. Consequence Lens

This lets the user complete, in one visual pass:
“who moves → how they move → what the consequence is.”

## 4.5 State deformations

### When `Ambiguous Ownership`
- Owner / Load Dock expands,
- owner-pressure nodes become more prominent in the battlefield.

### When `No Safe Route Yet`
- dangerous corridor actions dim,
- Consequence Lens rises into a stronger layer.

### When `Conflict Across Audiences`
- audience nodes visibly separate,
- interventions should bias toward split / hold rather than publish.

---

## 5. Shared density principles across both heroes

### Principle 1: high information density, but even higher command clarity
There can be a lot of information, but the user must rapidly understand:
- what the most dangerous front is,
- whether action is justified,
- what the next move is.

### Principle 2: map / battlefield is not decoration; it is a judgment instrument
If the terrain does not help the user choose an action, it should not own the screen.

### Principle 3: recovery must remain continuously perceptible
Even on the homepage hero, the user should feel the residue of prior command cycles.

### Principle 4: all support surfaces remain in service of the tower
copilot, surfaces, sources, and owners are support evidence for the support lead, not co-equal protagonists.

---

## 6. Why this matters for implementation
Once these two dense hero patterns are fixed, it becomes much easier to lock:
- the component tree,
- semantic token axes,
- the layout system,
- loading / stale / blocked behavior.

Because the hardest part is not making Cygnus look nice.
It is making the homepage and coordination screen feel unlike other products from first glance.
