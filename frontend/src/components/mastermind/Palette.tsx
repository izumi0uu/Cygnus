import { motion } from 'framer-motion'
import { PEG_COLORS, type Peg } from '@/game/mastermind'
import { PegDot } from './Peg'

/**
 * The channel palette — the operator's input deck. Each color is a button
 * labeled with a hint digit so it is operable by keyboard (1–6) and legible
 * without color. `disabled` locks input while a guess is being transmitted.
 */
export function Palette({
  numColors,
  onPick,
  disabled,
}: {
  numColors: number
  onPick: (peg: Peg) => void
  disabled?: boolean
}) {
  const colors = PEG_COLORS.slice(0, numColors)
  return (
    <div className="flex flex-wrap items-center justify-center gap-2">
      {colors.map((c) => (
        <motion.button
          key={c.id}
          type="button"
          disabled={disabled}
          onClick={() => onPick(c.id)}
          aria-label={`Channel ${c.hint}`}
          className="group relative flex flex-col items-center gap-1.5 p-1.5 transition-opacity disabled:opacity-40"
          whileHover={disabled ? undefined : { y: -2 }}
          whileTap={disabled ? undefined : { scale: 0.92 }}
        >
          <span
            className="relative flex items-center justify-center rounded-full transition-all group-hover:ring-2 group-hover:ring-[color-mix(in_srgb,var(--primary)_40%,transparent)]"
            style={{ width: 34, height: 34 }}
          >
            <PegDot peg={c.id} size={30} live />
          </span>
          <span className="font-mono text-[9px] text-[var(--faint)]">{c.hint}</span>
        </motion.button>
      ))}
    </div>
  )
}
