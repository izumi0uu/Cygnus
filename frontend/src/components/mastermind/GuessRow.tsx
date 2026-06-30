import { motion } from 'framer-motion'
import { PegDot, PegSlot } from './Peg'
import type { Code, Feedback, Peg as PegT } from '@/game/mastermind'
import { cn } from '@/lib/utils'

/**
 * The alignment feedback for one guess, rendered as classic Mastermind key
 * pegs. `exact` (channel locked) uses the primary blue and a filled glyph;
 * `partial` (channel drift) uses a hollow outline. We show them sorted
 * exact-first so the operator can scan lock count at a glance.
 */
export function KeyFeedback({
  feedback,
  codeLength,
  revealed,
  size = 12,
}: {
  feedback: Feedback | null
  codeLength: number
  revealed: boolean
  size?: number
}) {
  const slots = Array.from({ length: codeLength }, () => 'empty' as 'exact' | 'partial' | 'empty')
  if (feedback && revealed) {
    for (let i = 0; i < feedback.exact; i++) slots[i] = 'exact'
    for (let i = feedback.exact; i < feedback.exact + feedback.partial; i++) slots[i] = 'partial'
  }

  return (
    <div className="grid grid-cols-2 gap-1" style={{ width: size * 2 + 6 }}>
      {slots.map((s, i) => (
        <motion.span
          key={i}
          className="inline-flex items-center justify-center"
          style={{ width: size, height: size }}
          initial={revealed ? { scale: 0, opacity: 0 } : false}
          animate={revealed ? { scale: 1, opacity: 1 } : { opacity: 0.35 }}
          transition={{ delay: revealed ? 0.25 + i * 0.06 : 0, type: 'spring', stiffness: 500, damping: 18 }}
        >
          {s === 'exact' && (
            <span
              className="block rounded-full"
              style={{
                width: size,
                height: size,
                background: 'var(--primary)',
                boxShadow: '0 0 6px color-mix(in srgb, var(--primary) 50%, transparent)',
              }}
            />
          )}
          {s === 'partial' && (
            <span
              className="block rounded-full"
              style={{
                width: size - 2,
                height: size - 2,
                border: '1.5px solid var(--primary)',
                background: 'color-mix(in srgb, var(--primary) 10%, transparent)',
              }}
            />
          )}
          {s === 'empty' && (
            <span
              className="block rounded-full"
              style={{
                width: size - 4,
                height: size - 4,
                border: '1px dashed color-mix(in srgb, var(--primary) 20%, transparent)',
              }}
            />
          )}
        </motion.span>
      ))}
    </div>
  )
}

/**
 * One attempt row. When `active` it is the live input the operator is filling;
 * otherwise it is a locked record of a past guess + its alignment.
 */
export function GuessRow({
  guess,
  feedback,
  codeLength,
  active,
  revealed,
  index,
  slotSize = 30,
}: {
  guess: (PegT | null)[]
  feedback: Feedback | null
  codeLength: number
  active: boolean
  revealed: boolean
  index: number
  slotSize?: number
}) {
  return (
    <motion.div
      layout
      className={cn(
        'flex items-center gap-3 px-3 py-2.5 transition-colors',
        active && 'bg-[color-mix(in_srgb,var(--primary)_5%,transparent)]',
      )}
      style={{
        borderBottom: '1px solid color-mix(in srgb, var(--primary) 12%, transparent)',
      }}
    >
      <span className="w-6 shrink-0 text-right font-mono text-[10px] text-[var(--faint)]">
        {String(index + 1).padStart(2, '0')}
      </span>

      <div className="flex flex-1 items-center justify-center gap-2.5">
        {guess.map((peg, i) => (
          <div key={i} className="relative inline-flex items-center justify-center">
            <PegSlot filled={peg !== null} active={active} size={slotSize} />
            <motion.div
              className="pointer-events-none absolute inset-0 flex items-center justify-center"
              initial={peg !== null && active ? { y: -16, opacity: 0, scale: 0.6 } : false}
              animate={{ y: 0, opacity: 1, scale: 1 }}
              transition={{ type: 'spring', stiffness: 600, damping: 24 }}
            >
              <PegDot peg={peg} size={slotSize - 6} live={active} />
            </motion.div>
          </div>
        ))}
      </div>

      <div className="w-12 shrink-0">
        <KeyFeedback feedback={feedback} codeLength={codeLength} revealed={revealed} />
      </div>
    </motion.div>
  )
}

/** A peg dropped into the palette — never null. Used for the picker. */
export function PalettePeg({ peg, size = 26 }: { peg: PegT; size?: number }) {
  return <PegDot peg={peg} size={size} live />
}

/** The sealed secret row shown on game over — peels back to reveal the code. */
export function SecretRow({ secret, revealed, codeLength }: { secret: Code; revealed: boolean; codeLength: number }) {
  return (
    <div className="flex items-center justify-center gap-2.5 py-2">
      {Array.from({ length: codeLength }, (_, i) => (
        <div key={i} className="relative inline-flex items-center justify-center">
          <PegSlot filled size={30} />
          <motion.div
            className="pointer-events-none absolute inset-0 flex items-center justify-center"
            initial={false}
            animate={revealed ? { rotateY: 0, opacity: 1 } : { rotateY: 90, opacity: 0 }}
            transition={{ delay: revealed ? i * 0.08 : 0, duration: 0.3 }}
          >
            <PegDot peg={secret[i]} size={24} live />
          </motion.div>
        </div>
      ))}
    </div>
  )
}
