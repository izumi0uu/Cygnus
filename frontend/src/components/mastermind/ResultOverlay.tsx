import { AnimatePresence, motion } from 'framer-motion'
import { SecretRow } from './GuessRow'
import type { Code } from '@/game/mastermind'

/**
 * The decryption report — slides in over the board when the game resolves.
 * On a win it certifies the lock; on a loss it peels back the sealed signal.
 * The operator can replay (same difficulty) or step down to the menu.
 */
export function ResultOverlay({
  open,
  won,
  secret,
  guesses,
  best,
  isNewBest,
  onReplay,
  onMenu,
}: {
  open: boolean
  won: boolean
  secret: Code
  guesses: number
  best: number | null
  isNewBest: boolean
  onReplay: () => void
  onMenu: () => void
}) {
  return (
    <AnimatePresence>
      {open && (
        <motion.div
          className="absolute inset-0 z-30 flex items-center justify-center p-4"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.2 }}
        >
          <div
            className="absolute inset-0"
            style={{ background: 'color-mix(in srgb, var(--background) 80%, transparent)', backdropFilter: 'blur(2px)' }}
          />
          <motion.div
            className="bp-panel relative w-full max-w-sm p-5"
            initial={{ scale: 0.92, y: 12, opacity: 0 }}
            animate={{ scale: 1, y: 0, opacity: 1 }}
            exit={{ scale: 0.95, opacity: 0 }}
            transition={{ type: 'spring', stiffness: 320, damping: 26 }}
          >
            <div className="mb-1 flex items-center justify-between">
              <span className="bp-label">{won ? 'SIGNAL LOCKED' : 'SIGNAL LOST'}</span>
              <span
                className="font-mono text-[10px] font-bold uppercase"
                style={{ color: won ? 'var(--ok)' : 'var(--urgent)' }}
              >
                {won ? '◉ OK' : '✕ FAIL'}
              </span>
            </div>

            <h2
              className="font-mono text-2xl font-bold leading-tight"
              style={{ color: won ? 'var(--ok)' : 'var(--urgent)' }}
            >
              {won ? 'DECRYPT OK' : 'DECRYPT FAIL'}
            </h2>
            <p className="mt-1 font-mono text-[11px] leading-relaxed text-[var(--muted-foreground)]">
              {won
                ? `Signal decoded in ${guesses} transmission${guesses === 1 ? '' : 's'}.`
                : 'Signal sealed beyond reach. The code was:'}
            </p>

            {!won && (
              <div className="bp-panel mt-3 p-2" style={{ borderColor: 'color-mix(in srgb, var(--urgent) 35%, transparent)' }}>
                <SecretRow secret={secret} revealed codeLength={secret.length} />
              </div>
            )}

            <div className="bp-title-block mt-4">
              <div className="bp-tb-row">
                <div className="bp-tb-cell">
                  <div className="bp-tb-key">ATTEMPTS</div>
                  <div className="bp-tb-val">{guesses}</div>
                </div>
                <div className="bp-tb-cell">
                  <div className="bp-tb-key">BEST</div>
                  <div className="bp-tb-val" style={{ color: isNewBest ? 'var(--ok)' : undefined }}>
                    {best ?? '—'}
                  </div>
                </div>
                {isNewBest && (
                  <div className="bp-tb-cell">
                    <div className="bp-tb-key">FLAG</div>
                    <div className="bp-tb-val text-[12px]" style={{ color: 'var(--ok)' }}>NEW!</div>
                  </div>
                )}
              </div>
            </div>

            <div className="mt-4 flex gap-2">
              <button type="button" className="bp-cmd flex-1 justify-center" onClick={onReplay}>
                REPLAY
              </button>
              <button
                type="button"
                className="flex-1 justify-center border border-[color-mix(in_srgb,var(--primary)_25%,transparent)] py-1 font-mono text-[10px] font-semibold uppercase tracking-wider text-[var(--faint)] transition-colors hover:text-foreground"
                onClick={onMenu}
                style={{ borderRadius: 0 }}
              >
                MENU
              </button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
