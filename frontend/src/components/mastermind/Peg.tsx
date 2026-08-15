import { motion } from 'framer-motion'
import { PEG_COLORS, type Peg } from '@/game/mastermind'
import { cn } from '@/lib/utils'

/** A peg rendered at a given size. The "live" flag lifts it off the sheet. */
export function PegDot({
  peg,
  size = 28,
  live = false,
  className,
}: {
  peg: Peg | null
  size?: number
  live?: boolean
  className?: string
}) {
  if (peg === null || peg === undefined) return null
  const color = PEG_COLORS[peg]
  return (
    <motion.span
      layout
      className={cn('relative block rounded-full', className)}
      style={{
        width: size,
        height: size,
        background: color.hex,
        boxShadow: live
          ? `0 0 0 2px color-mix(in srgb, ${color.hex} 30%, transparent), 0 0 14px color-mix(in srgb, ${color.hex} 55%, transparent)`
          : `inset 0 0 0 1px rgba(0,0,0,0.25), 0 1px 2px rgba(0,0,0,0.15)`,
      }}
      transition={{ type: 'spring', stiffness: 500, damping: 32 }}
    >
      {/* specular highlight so the peg reads as a physical bead, not a flat disc */}
      <span
        className="pointer-events-none absolute rounded-full"
        style={{
          inset: size * 0.12,
          top: size * 0.12,
          height: size * 0.3,
          background: 'linear-gradient(180deg, rgba(255,255,255,0.55), rgba(255,255,255,0))',
          opacity: 0.7,
        }}
      />
    </motion.span>
  )
}

/** The empty slot a peg drops into — a dashed blueprint well. */
export function PegSlot({
  filled,
  size = 28,
  active,
  className,
}: {
  filled: boolean
  size?: number
  active?: boolean
  className?: string
}) {
  return (
    <span
      className={cn('relative inline-flex items-center justify-center rounded-full transition-colors', className)}
      style={{
        width: size,
        height: size,
        border: `1px dashed color-mix(in srgb, var(--primary) ${active ? 60 : 25}%, transparent)`,
        background: active ? 'color-mix(in srgb, var(--primary) 8%, transparent)' : 'transparent',
      }}
      aria-hidden
    >
      {!filled && (
        <span
          className="rounded-full"
          style={{
            width: size * 0.18,
            height: size * 0.18,
            background: 'color-mix(in srgb, var(--primary) 25%, transparent)',
          }}
        />
      )}
    </span>
  )
}
