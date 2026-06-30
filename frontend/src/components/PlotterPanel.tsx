import {
  animate,
  motion,
  useMotionValue,
  useTransform,
  type MotionValue,
  type Transition,
} from 'motion/react'
import {
  forwardRef,
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type ElementType,
  type HTMLAttributes,
  type ReactNode,
} from 'react'
import { DEFAULT_CHART_ENTER_TRANSITION } from '@/components/charts/animation'

/**
 * PlotterPanel — the "pen plotter" reveal from HANDOFF §12 Idea 1.
 *
 * A pen draws around the four edges of a blueprint panel (top L→R, right T→B,
 * bottom R→L, left B→T). While it draws, the contents渗出 (seep in) from all
 * four sides simultaneously, each side at its own speed, so the surface fills
 * in as the pen laps — not after. Title-block monospace text sweeps in once
 * the lap is mostly done.
 *
 * Design intent: this is a console control surface, so the reveal must be
 * handy — fast enough not to block interaction, with content arriving while
 * the pen moves rather than gating on a finished lap.
 *
 * Pacing convention (two tiers — pick by surface, not by mood):
 * - 1.05s: entry / low-frequency surfaces (Login). The slower lap is a
 *   one-time "drawing being plotted" ceremony, acceptable because it is
 *   seen rarely.
 * - 0.4s: operational surfaces (drawers, panels opened repeatedly). Fast
 *   enough that the pen is felt but never waits on; the whole lap fits inside
 *   a normal open gesture. Callers MUST pass lapDuration={0.4} on any surface
 *   a user opens more than once per session.
 *
 * How it's wired:
 * - A single MotionValue `lap` (0→1) drives everything. The four edges are
 *   rendered as one stroked SVG path whose `pathLength === lap`, animated on
 *   an ease that has subtle non-linearity (a brief dwell at each corner) so
 *   the pen tip feels physical rather than mechanically linear.
 * - Content opacity and the four-sided inset() clip are derived from `lap` via
 *   useTransform, each side remapped to its own speed band so left/right/top/
 * -bottom reveal at different rates.
 * - reduced-motion users get the final state immediately, no animation.
 * - Easing reuses the studio chart transition so the pen belongs to the same
 *   drawing set as the charts, not a one-off.
 */

export interface PlotterPanelProps extends Omit<HTMLAttributes<HTMLElement>, 'style'> {
  label?: string
  drawingId?: string
  titleBlock?: { key: string; value: string }[]
  children?: ReactNode
  strokeColor?: string
  /** Total pen-lap duration in seconds (all four edges). */
  lapDuration?: number
  delay?: number
  className?: string
  style?: CSSProperties
  /** Bump to replay the reveal. */
  replayKey?: number | string
  /**
   * Element to render as. Defaults to "div"; pass "aside" (with the caller's
   * role/aria props) so the plotter can BE a dialog panel instead of nesting
   * inside one. The forwarded ref lands on this element.
   */
  as?: ElementType
}

// Edge end-points form one closed clockwise path: top L→R, right T→B,
// bottom R→L, left B→T. pathLength drives how far the pen has traveled.
function buildEdgePath(w: number, h: number): string {
  return `M 0 0.5 L ${w} 0.5 L ${w - 0.5} ${h} L 0.5 ${h} L 0.5 0 Z`
}

export const PlotterPanel = forwardRef<HTMLElement, PlotterPanelProps>(function PlotterPanel(
  {
    label,
    drawingId,
    titleBlock,
    children,
    strokeColor = 'var(--primary)',
    lapDuration = 1.05,
    delay = 0,
    className = '',
    style,
    replayKey = 0,
    as,
    ...rest
  },
  forwardedRef,
) {
  const panelRef = useRef<HTMLElement>(null)
  const [size, setSize] = useState({ w: 0, h: 0 })

  // Merge the internal measurement ref with the caller's forwarded ref
  // (e.g. a drawer's focus-trap ref) so both land on the same element.
  const setRef = (el: HTMLElement | null) => {
    panelRef.current = el
    if (typeof forwardedRef === 'function') forwardedRef(el)
    else if (forwardedRef) (forwardedRef as React.MutableRefObject<HTMLElement | null>).current = el
  }

  useEffect(() => {
    const el = panelRef.current
    if (!el) return
    const update = () => setSize({ w: el.clientWidth, h: el.clientHeight })
    update()
    const ro = new ResizeObserver(update)
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const prefersReduced = usePrefersReducedMotion()

  // The single source of progress for the whole reveal.
  const lap = useMotionValue(0)

  useEffect(() => {
    if (prefersReduced) {
      lap.set(1)
      return
    }
    lap.set(0)
    const controls = animate(lap, 1, {
      ...PEN_TRANSITION,
      duration: lapDuration,
      delay,
    })
    return () => controls.stop()
    // replayKey re-triggers the lap; lapDuration/delay changes restart it too.
    // biome-ignore lint/correctness/useExhaustiveDependencies: intentional restart
  }, [lap, lapDuration, delay, prefersReduced, replayKey])

  const { w, h } = size
  const hasSize = w > 0 && h > 0

  // Content seep transforms — hooks must live in the component body (not a
  // helper), called unconditionally every render.
  const contentOpacity = useTransform(lap, seepOpacity)
  const contentClip = useTransform(lap, diagonalClip)

  const Tag = (as ?? 'div') as ElementType

  return (
    <Tag ref={setRef} className={`bp-panel ${className}`} style={style} {...rest}>
      {hasSize && !prefersReduced && (
        <svg
          className="pointer-events-none absolute inset-0 z-10"
          width={w}
          height={h}
          style={{ overflow: 'visible' }}
          aria-hidden
        >
          <motion.path
            d={buildEdgePath(w, h)}
            fill="none"
            stroke={strokeColor}
            strokeWidth={1.5}
            strokeLinejoin="miter"
            strokeLinecap="square"
            style={{ pathLength: lap }}
          />
        </svg>
      )}

      {/* content seeps in while the pen draws. The clip reveals on two axes at
          different rates: horizontally fast (left→right), vertically slower
          (top→bottom). The two rates meet as a diagonal wipe that moves down-
          right — the rate difference is what makes the arrival feel
          asymmetric rather than a uniform box-open. clip-path (not scale)
          keeps text and children undistorted.

          The wrapper is itself flex/flex-col + h-full so that when the caller
          is a flex-col container (e.g. a drawer aside) it fills the height and
          the caller's children stack from the top — no extra intermediate
          layer that would collapse the layout to the bottom. */}
      <motion.div
        style={{ opacity: contentOpacity, clipPath: contentClip }}
        className="relative flex h-full flex-col"
      >
        {(label || drawingId) && (
          <div className="mb-3 flex items-baseline justify-between">
            {label ? <span className="bp-label">{label}</span> : <span />}
            {drawingId ? (
              <span className="bp-label" style={{ opacity: 0.6 }}>
                {drawingId}
              </span>
            ) : null}
          </div>
        )}

        {titleBlock && titleBlock.length > 0 && (
          <SweptTitleBlock rows={titleBlock} lap={lap} />
        )}

        <div className="relative">{children}</div>
      </motion.div>
    </Tag>
  )
})

/**
 * Pen ease: mostly linear but with a slight dwell at each quadrant (a tiny
 * cubic ease), so the pen tip pauses at corners like a real pen lifting.
 */
const PEN_TRANSITION: Transition = {
  ...DEFAULT_CHART_ENTER_TRANSITION,
  ease: [0.6, 0.05, 0.4, 0.95],
}

/** Content begins seeping the instant the pen starts; full by ~70% lap. */
function seepOpacity(l: number): number {
  if (l >= 0.7) return 1
  return Math.max(0, Math.min(1, l / 0.7))
}

/**
 * Two-axis diagonal clip: the left inset (X axis) closes fast, the top inset
 * (Y axis) closes slow. Early in the lap the content appears as a wide-thin
 * strip that grows downward — the rate gap between X and Y is the visible
 * asymmetry. clip-path (not scale) keeps text and children undistorted.
 *
 * `inset(top right bottom left)`: left and top edges close (→0) to reveal;
 * right/bottom stay at 0 so nothing leaks past the wipe front.
 */
function diagonalClip(l: number): string {
  const left = band(l, 0.0, 0.45) // X axis: fast, clears by 45% lap
  const top = band(l, 0.05, 0.85) // Y axis: slow, clears by 85% lap
  return `inset(${(top * 100).toFixed(2)}% 0% 0% ${(left * 100).toFixed(2)}%)`
}

/** Map progress into [start, end] → remaining inset fraction (1 → 0). */
function band(l: number, start: number, end: number): number {
  if (l <= start) return 1
  if (l >= end) return 0
  return 1 - (l - start) / (end - start)
}

function SweptTitleBlock({
  rows,
  lap,
}: {
  rows: { key: string; value: string }[]
  lap: MotionValue<number>
}) {
  // Sweep kicks in late, after most of the lap, so values write as the pen
  // finishes — reads as the pen labeling what it just drew.
  const clip = useTransform(lap, (l) => {
    if (l <= 0.6) return 'inset(0 100% 0 0)'
    if (l >= 0.95) return 'inset(0 0% 0 0)'
    return `inset(0 ${((1 - (l - 0.6) / 0.35) * 100).toFixed(2)}% 0 0)`
  })
  return (
    <div className="bp-title-block mb-3">
      {rows.map((row) => (
        <div key={row.key} className="bp-tb-row">
          <span className="bp-tb-key">{row.key}</span>
          <motion.span className="bp-tb-val" style={{ clipPath: clip }}>
            {row.value}
          </motion.span>
        </div>
      ))}
    </div>
  )
}

function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = useState(false)
  useEffect(() => {
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)')
    setReduced(mq.matches)
    const handler = (e: MediaQueryListEvent) => setReduced(e.matches)
    mq.addEventListener('change', handler)
    return () => mq.removeEventListener('change', handler)
  }, [])
  return reduced
}
