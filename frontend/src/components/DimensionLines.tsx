import { useEffect, useState } from 'react'

/**
 * DimensionLines — the "caliper cursor" from HANDOFF §12 Idea 2.
 *
 * Hover/focus a row in a numeric list and a set of engineering dimension lines
 * springs up, measuring the gap (Δ) between the hovered item and selected
 * neighbors. It measures *relationships*, not attributes: a tooltip says
 * "LEV 8.3"; a dimension line says "1.4 above the next one" — turning the
 * list's *gradient* into space you can read at a glance.
 *
 * Honesty model (the soul of this component — do not violate):
 * - The measured distance is the REAL value delta, extracted by `getValue`.
 *   Never fabricated. Only mount this where the backing data has a genuine
 *   NUMERIC ESTIMATE axis — not counts, not ordinals, not discrete states
 *   (those would make "distance" a lie).
 * - The measured value is a computed estimate, not a precise quantity, so each
 *   measurement carries a derived tolerance. When the tolerance meets or
 *   exceeds the delta, the pair is "in the noise": the line + arrows go dashed
 *   and dim — visualizing "this gap is not to be trusted". That second layer of
 *   judgment is what lifts this from decoration to a reading tool.
 * - Tolerance is derived from the list's own dispersion (median adjacent gap ×
 *   0.5, floored and capped per host) — no invented confidence number, zero
 *   backend change. Dispersion is measured on value-sorted gaps so it reflects
 *   the set's true density, not an arbitrary render order.
 * - Single axis only. `tolerance.{floor,cap}` are scale-specific to the host
 *   (e.g. leverage_score's 0-100 axis vs after_score's 0-1 axis). A range
 *   fraction cannot reproduce both scales, so the config is explicit per host.
 * - Pure client-side, transient. Not in URL, not persisted. The frontend is a
 *   control surface, not a governance-truth holder (HANDOFF §10).
 *
 * Strategies (how neighbors are chosen):
 * - `sorted-adjacent`: the list is sorted by the measured value (render order
 *   == strength order). Measure to the rows immediately above/below plus the
 *   top-ranked row. Reads "distance to neighbors." Host: Overview SEC-A, whose
 *   ranks are sorted by leverage.
 * - `rank-extrema`: the list renders in a fixed canonical order that is NOT
 *   strength order, so "adjacent" is geometrically meaningless. Instead measure
 *   to the strongest (max value) and weakest (min value) items. Reads "how far
 *   from the top and bottom of the pack." Host: RecoveryDetail alignment
 *   planes, which render in fixed object/audience/publish/coverage order.
 */

export interface LabelContext {
  /** Which extremum the pair measures, for `rank-extrema`. Null for adjacent. */
  extremum: 'strongest' | 'weakest' | null
}

export interface DimensionLinesConfig<T> {
  /** Extract the measured continuous scalar from each item. */
  getValue: (item: T) => number
  /** Target-selection strategy. See the strategy docs above. */
  strategy: 'sorted-adjacent' | 'rank-extrema'
  /** Tolerance floor & cap, scale-specific to the host's value axis. */
  tolerance: { floor: number; cap: number }
  /** Format the value label (e.g. "Δ8.7 ±0.10" vs "Δ0.19 ±0.05"). */
  formatLabel: (delta: number, tol: number, ctx: LabelContext) => string
  /** Lane position + extension reach, in px. Driven by row geometry. */
  geometry: {
    /** Which panel gutter the lane sits in. Right when the row's far edge is
     *  free (flat rows); left when the right edge holds the score text. */
    side: 'right' | 'left'
    /** px from that edge → the first lane's x position. */
    inset: number
    /** Extension-line reach from the lane. On the right side, how far the stub
     *  reaches leftward into the row's right gutter (clear of content). On the
     *  left side, how far it reaches leftward toward the panel edge / card
     *  border — set to `inset` to land on the card's left border (in its empty
     *  padding, clear of the progress bar). */
    extReach: number
    /** px between stacked dimension lines (away from the edge). */
    stride: number
  }
  /**
   * Label orientation. `horizontal` (default) places the label as a horizontal
   * chip at the dimension line's midpoint — needs free space beside the lane
   * (flat rows with an empty gutter, like SEC-A). `rotated` turns the label
   * along the dimension line (read bottom-to-top) — for card rows whose body
   * is filled edge-to-edge (like the planes' progress bars), so no horizontal
   * chip has room and the label must ride the line itself.
   */
  labelOrientation?: 'horizontal' | 'rotated'
}

export interface DimensionLinesProps<T> {
  /** The list being measured (already in render order). */
  items: T[]
  /** Index of the hovered/focused row in `items`, or null when idle. */
  hoverIndex: number | null
  /**
   * Ref to the positioned ancestor the overlay is measured against. Rows are
   * located by getBoundingClientRect relative to this container — real-time,
   * not cached, so row-height/wrap changes are followed.
   */
  containerRef: React.RefObject<HTMLElement | null>
  /** Per-host configuration. See DimensionLinesConfig. */
  config: DimensionLinesConfig<T>
  /** Selector for row elements inside the container. Defaults to
   *  [data-rank-index]. Each matched element must carry data-rank-index = its
   *  index in `items` (DimensionLines locates rows by index via this attr). */
  rowSelector?: string
}

interface MeasuredPair {
  targetIndex: number
  /** Real value delta = abs(hover - target). */
  delta: number
  /** Derived tolerance (same for every pair in a list). */
  tol: number
  /** tol >= delta → gap is within noise; render dashed/dim. */
  noisy: boolean
  /** Hover-row vertical center, relative to container. */
  hoverY: number
  /** Target-row vertical center, relative to container. */
  targetY: number
  /** Horizontal lane for this dimension line; pairs are staggered so they
   *  don't overlap when several are shown at once. */
  laneX: number
  /** Which extremum this pair measures (for label context). */
  extremum: 'strongest' | 'weakest' | null
}

const ARROW = 5 // marker size

export function DimensionLines<T>({ items, hoverIndex, containerRef, config, rowSelector }: DimensionLinesProps<T>) {
  const [pairs, setPairs] = useState<MeasuredPair[]>([])
  // Container size, tracked continuously so the SVG and lane positions follow
  // responsive width changes. Kept separate from the hover effect because the
  // ResizeObserver must live for the component's lifetime, not just while a
  // row is hovered.
  const [size, setSize] = useState({ w: 0, h: 0 })

  // Resolve rows by querying the container. Both hosts are short lists and we
  // re-query on every hover, so we don't cache row element refs.
  const resolveRows = (): (HTMLElement | null)[] => {
    const container = containerRef.current
    if (!container) return []
    return Array.from(container.querySelectorAll<HTMLElement>(rowSelector ?? '[data-rank-index]'))
  }

  // Track container size for the component's lifetime. ResizeObserver fires an
  // initial callback once the container is laid out, which populates `size`
  // even when the panel mounts inside a grid that grants it width late. Using
  // useEffect (not useLayoutEffect) avoids the StrictMode mount/cleanup/remount
  // race that left `size` stuck at 0.
  useEffect(() => {
    const container = containerRef.current
    if (!container) return
    const update = () => setSize({ w: container.clientWidth, h: container.clientHeight })
    update()
    const ro = new ResizeObserver(update)
    ro.observe(container)
    return () => ro.disconnect()
  }, [containerRef])

  useEffect(() => {
    // Need at least 2 items to measure a gap. With 1 item there is nothing to
    // compare; with 2, the single pair is a legitimate measurement.
    if (hoverIndex == null || items.length < 2) {
      setPairs([])
      return
    }
    const container = containerRef.current
    if (!container) {
      setPairs([])
      return
    }
    const rows = resolveRows()
    const hoverEl = rows[hoverIndex]
    if (!hoverEl) {
      setPairs([])
      return
    }

    const tol = deriveTolerance(items, config)
    const cRect = container.getBoundingClientRect()
    const centerOf = (el: HTMLElement) => el.getBoundingClientRect().top - cRect.top + el.offsetHeight / 2

    const targets = selectTargets(items, hoverIndex, config)
    if (targets.length === 0) {
      setPairs([])
      return
    }

    const hoverY = centerOf(hoverEl)
    const measured: MeasuredPair[] = []
    targets.forEach(({ targetIndex, extremum }, lane) => {
      const targetEl = rows[targetIndex]
      if (!targetEl) return
      const delta = Math.abs(config.getValue(items[hoverIndex]) - config.getValue(items[targetIndex]))
      measured.push({
        targetIndex,
        delta,
        tol,
        noisy: tol >= delta,
        hoverY,
        targetY: centerOf(targetEl),
        extremum,
        laneX: laneXFor(lane, config.geometry, container.clientWidth),
      })
    })
    setPairs(measured)
    // Re-measure on hover change, items identity change (navigation/reload),
    // and container width change (responsive resize) so lane positions follow.
    // biome-ignore lint/correctness/useExhaustiveDependencies: re-measure on hover/items/width
  }, [hoverIndex, items, containerRef, size.w, config])

  if (pairs.length === 0) return null

  const { side } = config.geometry

  return (
    <svg
      className="pointer-events-none absolute inset-0 z-20"
      width={size.w || '100%'}
      height={size.h || '100%'}
      style={{ overflow: 'visible' }}
      aria-hidden
    >
      <defs>
        <marker
          id="dim-arrow"
          viewBox="0 0 10 10"
          refX="9"
          refY="5"
          markerWidth={ARROW}
          markerHeight={ARROW}
          orient="auto-start-reverse"
        >
          <path d="M 0 0 L 10 5 L 0 10 z" fill="var(--primary)" />
        </marker>
        <marker
          id="dim-arrow-dim"
          viewBox="0 0 10 10"
          refX="9"
          refY="5"
          markerWidth={ARROW}
          markerHeight={ARROW}
          orient="auto-start-reverse"
        >
          <path d="M 0 0 L 10 5 L 0 10 z" fill="var(--primary)" opacity="0.4" />
        </marker>
      </defs>

      {pairs.map((p) => {
        const top = Math.min(p.hoverY, p.targetY)
        const bottom = Math.max(p.hoverY, p.targetY)
        // Label at the dimension line's vertical midpoint. For a non-adjacent
        // pair (e.g. hover-middle to an extremum) this lands on an intervening
        // row; we accept that with a semi-transparent background (text stays
        // legible, intervening row reads through) — the same occlusion
        // tradeoff any chart label makes.
        const midY = (top + bottom) / 2
        const stroke = 'var(--primary)'
        // Group opacity drives both the 120ms fade and the noise dimming; the
        // dashed array is the other noise signal. No per-line opacity needed.
        const opacity = p.noisy ? 0.4 : 0.85
        const dashArray = p.noisy ? '4 3' : undefined
        const marker = p.noisy ? 'url(#dim-arrow-dim)' : 'url(#dim-arrow)'
        const label = config.formatLabel(p.delta, p.tol, { extremum: p.extremum })

        // Extension lines reach leftward from the lane. On the right side they
        // reach into the row's right gutter (clear of content); on the left
        // side they reach toward the panel edge / card border (in the card's
        // empty left padding, ahead of the progress bar). Stacked lanes sit
        // further in, so a left-side extReach larger than the deepest lane's x
        // clamps every stub to the edge (x≥0), keeping all of them clear of the
        // bar regardless of which lane they're on.
        const extInner = Math.max(0, p.laneX - config.geometry.extReach)

        // The label sits inside the panel, away from the edge. On the right
        // side it's to the LEFT of the lane; on the left side, to the RIGHT.
        const labelW = label.length * 6.2 + 8
        const labelX = side === 'right' ? p.laneX - 6 - labelW : p.laneX + 6

        return (
          <g key={p.targetIndex} style={{ opacity, transition: 'opacity 120ms linear' }}>
            {/* Extension lines: short dashed stubs reaching from the lane into
                each row's gutter. Faint — the engineering convention for
                projection lines. They stay in the gutter, clear of row content. */}
            <line
              x1={extInner}
              y1={p.hoverY}
              x2={p.laneX}
              y2={p.hoverY}
              stroke={stroke}
              strokeWidth={1}
              strokeDasharray="2 3"
              opacity={0.45}
            />
            <line
              x1={extInner}
              y1={p.targetY}
              x2={p.laneX}
              y2={p.targetY}
              stroke={stroke}
              strokeWidth={1}
              strokeDasharray="2 3"
              opacity={0.45}
            />

            {/* Dimension line: vertical, between the two rows, arrowed both ends. */}
            <line
              x1={p.laneX}
              y1={top + ARROW}
              x2={p.laneX}
              y2={bottom - ARROW}
              stroke={stroke}
              strokeWidth={1}
              strokeDasharray={dashArray}
              markerStart={marker}
              markerEnd={marker}
            />

            {/* Value label. Two orientations:
                - horizontal (default): a chip at the dimension line's midpoint,
                  beside the lane. Needs free space beside the lane (flat rows
                  with an empty gutter). Semi-transparent background so an
                  intervening row, when the pair is non-adjacent, still reads
                  through.
                - rotated: the label rides the dimension line itself, read
                  bottom-to-top, with a slim background. For card rows whose
                  body is filled edge-to-edge (e.g. progress bars), where no
                  horizontal chip has room. The label is pushed to the edge side
                  of the lane (left of the lane on the left side, right on the
                  right) so it sits in the gutter, clear of the card body. */}
            {config.labelOrientation === 'rotated' ? (
              <g transform={`translate(${p.laneX} ${midY}) rotate(-90)`}>
                <rect x={-labelW / 2} y={side === 'right' ? 2 : -14} width={labelW} height={12} fill="var(--background)" opacity={0.82} />
                <text
                  x={-labelW / 2 + 4}
                  y={side === 'right' ? 11 : -5}
                  fontFamily="var(--font-mono)"
                  fontSize={10}
                  fill={p.noisy ? 'var(--faint)' : 'var(--primary)'}
                >
                  {label}
                </text>
              </g>
            ) : (
              <g transform={`translate(${labelX} ${midY})`}>
                <rect x={0} y={-7} width={labelW} height={14} fill="var(--background)" opacity={0.82} />
                <text
                  x={4}
                  y={3}
                  fontFamily="var(--font-mono)"
                  fontSize={10}
                  fill={p.noisy ? 'var(--faint)' : 'var(--primary)'}
                >
                  {label}
                </text>
              </g>
            )}
          </g>
        )
      })}
    </svg>
  )
}

/**
 * Lane x for the n-th stacked pair. Pairs stack *away* from the panel edge so
 * multiple lines don't overlap: right-side lanes march leftward from the right
 * edge, left-side lanes march rightward from the left edge.
 */
function laneXFor(lane: number, geo: DimensionLinesConfig<unknown>['geometry'], width: number): number {
  if (geo.side === 'right') {
    return width - geo.inset - lane * geo.stride
  }
  return geo.inset + lane * geo.stride
}

interface Target {
  targetIndex: number
  extremum: 'strongest' | 'weakest' | null
}

/**
 * Pick which items to measure the hovered item against.
 *
 * `sorted-adjacent`: the rows immediately above and below in render order
 * (which == strength order for this strategy) plus the top-ranked row when the
 * hovered row is not itself the top. Deduped, bounds-checked, max 3.
 *
 * `rank-extrema`: the strongest (max value) and weakest (min value) items by
 * value, tie-broken by first-in-render-order for determinism. If the hovered
 * item is an extremum, measure only to the opposite end; if it's the middle,
 * measure to both. If all values tie (max === min) there is no rank to surface,
 * so return nothing. Max 2.
 */
function selectTargets<T>(items: T[], hoverIndex: number, config: DimensionLinesConfig<T>): Target[] {
  if (config.strategy === 'sorted-adjacent') {
    const want = [hoverIndex - 1, hoverIndex + 1, 0]
    const seen = new Set<number>()
    const out: Target[] = []
    for (const i of want) {
      if (i < 0 || i >= items.length || i === hoverIndex || seen.has(i)) continue
      seen.add(i)
      out.push({ targetIndex: i, extremum: null })
    }
    return out
  }

  // rank-extrema: strongest = max value, weakest = min value.
  // Ties keep the FIRST occurrence (deterministic, render-order stable).
  if (items.length < 2) return []
  let maxI = 0
  let minI = 0
  for (let i = 1; i < items.length; i++) {
    if (config.getValue(items[i]) > config.getValue(items[maxI])) maxI = i
    if (config.getValue(items[i]) < config.getValue(items[minI])) minI = i
  }
  // Universal tie: no rank to surface.
  if (config.getValue(items[maxI]) === config.getValue(items[minI])) return []

  const out: Target[] = []
  if (hoverIndex === maxI) {
    out.push({ targetIndex: minI, extremum: 'weakest' })
  } else if (hoverIndex === minI) {
    out.push({ targetIndex: maxI, extremum: 'strongest' })
  } else {
    out.push({ targetIndex: maxI, extremum: 'strongest' })
    out.push({ targetIndex: minI, extremum: 'weakest' })
  }
  return out
}

/**
 * Derived tolerance for the list. The median adjacent gap × 0.5, over
 * value-sorted gaps (order-independent — the set's true density, not an
 * arbitrary render order), floored and capped per host. When the list is tight
 * (small adjacent gaps) the tolerance shrinks toward the floor; when it's
 * loose, it caps so a single huge gap can't inflate every pair's tolerance.
 * With <2 items this is never called (caller gates on length).
 */
function deriveTolerance<T>(items: T[], config: DimensionLinesConfig<T>): number {
  const sorted = [...items].sort((a, b) => config.getValue(b) - config.getValue(a))
  const gaps: number[] = []
  for (let i = 1; i < sorted.length; i++) {
    gaps.push(Math.abs(config.getValue(sorted[i - 1]) - config.getValue(sorted[i])))
  }
  if (gaps.length === 0) return config.tolerance.floor
  gaps.sort((a, b) => a - b)
  const mid = Math.floor(gaps.length / 2)
  const median = gaps.length % 2 === 0 ? (gaps[mid - 1] + gaps[mid]) / 2 : gaps[mid]
  return Math.min(config.tolerance.cap, Math.max(config.tolerance.floor, median * 0.5))
}
