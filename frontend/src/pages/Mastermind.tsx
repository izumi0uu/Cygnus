import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from 'react'
import { motion } from 'framer-motion'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import {
  DIFFICULTY_PRESETS,
  PEG_COLORS,
  emptyGuess,
  evaluateGuess,
  generateSecret,
  getBest,
  isGuessComplete,
  isWin,
  maybeSetBest,
  type Code,
  type Difficulty,
  type Feedback,
  type Peg,
} from '@/game/mastermind'
import { GuessRow, SecretRow } from '@/components/mastermind/GuessRow'
import { Palette } from '@/components/mastermind/Palette'
import { ResultOverlay } from '@/components/mastermind/ResultOverlay'

interface Attempt {
  guess: Code
  feedback: Feedback
}

type Phase = 'menu' | 'playing' | 'won' | 'lost'

interface GameState {
  phase: Phase
  difficulty: Difficulty
  secret: Code
  attempts: Attempt[]
  /** The live row the operator is composing (null slots = empty). */
  draft: (Peg | null)[]
  config: (typeof DIFFICULTY_PRESETS)[Difficulty]
  /** Guess count at the moment of a win (null until/unless won). Drives best tracking. */
  winningGuesses: number | null
}

function makeInitial(difficulty: Difficulty): GameState {
  const config = DIFFICULTY_PRESETS[difficulty]
  return {
    phase: 'playing',
    difficulty,
    secret: generateSecret(config),
    attempts: [],
    draft: emptyGuess(config.codeLength),
    config,
    winningGuesses: null,
  }
}

type Action =
  | { type: 'start'; difficulty: Difficulty }
  | { type: 'place'; peg: Peg }
  | { type: 'backspace' }
  | { type: 'submit' }

function reducer(state: GameState, action: Action): GameState {
  switch (action.type) {
    case 'start':
      return makeInitial(action.difficulty)

    case 'place': {
      if (state.phase !== 'playing') return state
      // Fill the leftmost empty slot — operator enters channels in order.
      const idx = state.draft.findIndex((p) => p === null)
      if (idx === -1) return state
      const draft = state.draft.slice()
      draft[idx] = action.peg
      return { ...state, draft }
    }

    case 'backspace': {
      if (state.phase !== 'playing') return state
      // Clear the rightmost filled slot.
      let idx = -1
      for (let i = state.draft.length - 1; i >= 0; i--) {
        if (state.draft[i] !== null) { idx = i; break }
      }
      if (idx === -1) return state
      const draft = state.draft.slice()
      draft[idx] = null
      return { ...state, draft }
    }

    case 'submit': {
      if (state.phase !== 'playing') return state
      if (!isGuessComplete(state.draft)) return state
      const guess = state.draft as Code
      const feedback = evaluateGuess(state.secret, guess)
      const attempts = [...state.attempts, { guess, feedback }]
      const won = isWin(feedback, state.config.codeLength)
      const lost = !won && attempts.length >= state.config.maxGuesses
      return {
        ...state,
        attempts,
        draft: won ? state.draft : emptyGuess(state.config.codeLength),
        phase: won ? 'won' : lost ? 'lost' : 'playing',
        winningGuesses: won ? attempts.length : null,
      }
    }

    default:
      return state
  }
}

export default function Mastermind() {
  const { t } = useTranslation()
  const [menuDifficulty, setMenuDifficulty] = useState<Difficulty | null>(null)
  const [state, dispatch] = useReducer(reducer, null, () =>
    makeInitial('normal'),
  )

  // Best score for the current difficulty. Read from storage as the initial
  // value (pure read, safe under StrictMode), then kept in sync by the effect
  // below — which is the ONLY place we write storage, so no render-time side
  // effects. isNewBest flips true for the single winning render that beats the
  // prior best, then resets on difficulty change / new round.
  const [best, setBest] = useState<number | null>(() => getBest(state.difficulty))
  const [isNewBest, setIsNewBest] = useState(false)

  useEffect(() => {
    // Difficulty changed or a new round started (phase left 'won') — re-read
    // the stored best and clear the new-best flag.
    if (state.phase !== 'won') {
      setIsNewBest(false)
      setBest(getBest(state.difficulty))
      return
    }
    // Winning render: compute the new-best flag from the PRE-write stored
    // value, then persist. maybeSetBest is idempotent (writes only on
    // improvement), so a StrictMode double-invoke is safe.
    const guesses = state.winningGuesses
    if (guesses == null) return
    const priorBest = getBest(state.difficulty)
    const beat = priorBest === null || guesses < priorBest
    maybeSetBest(state.difficulty, guesses)
    setBest(getBest(state.difficulty))
    setIsNewBest(beat)
  }, [state.phase, state.difficulty, state.winningGuesses])

  const inMenu = menuDifficulty !== null ? false : true
  const liveRowRef = useRef<HTMLDivElement>(null)

  // --- Keyboard controls (only active during play, not in menu/overlay) ---
  useEffect(() => {
    if (state.phase !== 'playing') return
    const isTyping = () => {
      const el = document.activeElement as HTMLElement | null
      return !!el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.isContentEditable)
    }
    const onKey = (e: KeyboardEvent) => {
      if (isTyping()) return
      // Number keys 1..N place a channel.
      const n = Number(e.key)
      if (Number.isInteger(n) && n >= 1 && n <= state.config.numColors) {
        e.preventDefault()
        dispatch({ type: 'place', peg: n - 1 })
        return
      }
      if (e.key === 'Backspace') { e.preventDefault(); dispatch({ type: 'backspace' }); return }
      if (e.key === 'Enter') {
        e.preventDefault()
        if (isGuessComplete(state.draft)) dispatch({ type: 'submit' })
        return
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [state.phase, state.config.numColors, state.draft])

  const start = useCallback((d: Difficulty) => {
    setMenuDifficulty(d)
    dispatch({ type: 'start', difficulty: d })
  }, [])

  const replay = useCallback(() => {
    dispatch({ type: 'start', difficulty: state.difficulty })
  }, [state.difficulty])

  const toMenu = useCallback(() => {
    setMenuDifficulty(null)
  }, [])

  const cfg = state.config
  const colors = PEG_COLORS.slice(0, cfg.numColors)
  const draftComplete = isGuessComplete(state.draft)
  const remaining = cfg.maxGuesses - state.attempts.length

  // Slots still empty in the draft (for the empty-row placeholders below the attempts).
  const emptyRows = useMemo(() => {
    const liveRows = state.attempts.length + (state.phase === 'playing' ? 1 : 0)
    return Math.max(0, cfg.maxGuesses - liveRows)
  }, [state.attempts.length, state.phase, cfg.maxGuesses])

  if (inMenu) {
    return <Menu onPick={start} t={t} />
  }

  const showOverlay = state.phase === 'won' || state.phase === 'lost'

  return (
    <div className="bp-grid min-h-screen w-full px-4 py-6 sm:px-6">
      <div className="mx-auto w-full max-w-2xl">
        {/* Header */}
        <div className="mb-4 flex items-baseline justify-between">
          <div>
            <span className="bp-label">DWG-DEMO · SIGNAL DECRYPTOR</span>
            <h1 className="mt-1 font-mono text-xl font-bold tracking-tight text-foreground">
              MASTERMIND
            </h1>
          </div>
          <Link
            to="/"
            className="font-mono text-[10px] uppercase tracking-wider text-[var(--faint)] transition-colors hover:text-foreground"
          >
            ← EXIT
          </Link>
        </div>

        {/* Title block — config readout */}
        <div className="bp-title-block mb-4">
          <div className="bp-tb-row">
            <div className="bp-tb-cell">
              <div className="bp-tb-key">{t('mm.difficulty')}</div>
              <div className="bp-tb-val text-[14px] uppercase">{state.difficulty}</div>
            </div>
            <div className="bp-tb-cell">
              <div className="bp-tb-key">{t('mm.length')}</div>
              <div className="bp-tb-val">{cfg.codeLength}</div>
            </div>
            <div className="bp-tb-cell">
              <div className="bp-tb-key">{t('mm.channels')}</div>
              <div className="bp-tb-val">{cfg.numColors}</div>
            </div>
            <div className="bp-tb-cell">
              <div className="bp-tb-key">{t('mm.remaining')}</div>
              <div className="bp-tb-val" style={{ color: remaining <= 2 ? 'var(--urgent)' : undefined }}>
                {remaining}
              </div>
            </div>
            <div className="bp-tb-cell">
              <div className="bp-tb-key">{t('mm.best')}</div>
              <div className="bp-tb-val text-[14px]">{best ?? '—'}</div>
            </div>
          </div>
        </div>

        {/* Board */}
        <div className="bp-panel relative overflow-hidden p-0">
          <div className="bp-label m-3 mb-0 flex items-center justify-between">
            <span>{t('mm.board')}</span>
            <span className="font-mono text-[9px] text-[var(--faint)]">
              {t('mm.attemptCount', { n: state.attempts.length, max: cfg.maxGuesses })}
            </span>
          </div>

          {/* Column headers */}
          <div className="mx-3 mt-2 flex items-center gap-3 border-b border-[color-mix(in_srgb,var(--primary)_15%,transparent)] pb-1.5">
            <span className="w-6 text-right font-mono text-[9px] text-[var(--faint)]">#</span>
            <span className="flex-1 text-center font-mono text-[9px] uppercase tracking-wider text-[var(--faint)]">
              {t('mm.probe')}
            </span>
            <span className="w-12 text-center font-mono text-[9px] uppercase tracking-wider text-[var(--faint)]">
              {t('mm.alignment')}
            </span>
          </div>

          {/* Attempt history */}
          <div className="thin-scroll max-h-[46vh] overflow-y-auto">
            {state.attempts.map((att, i) => (
              <GuessRow
                key={i}
                index={i}
                guess={att.guess}
                feedback={att.feedback}
                codeLength={cfg.codeLength}
                active={false}
                revealed
              />
            ))}

            {/* Live draft row */}
            {state.phase === 'playing' && (
              <div ref={liveRowRef}>
                <GuessRow
                  index={state.attempts.length}
                  guess={state.draft}
                  feedback={null}
                  codeLength={cfg.codeLength}
                  active
                  revealed={false}
                />
              </div>
            )}

            {/* Empty placeholder rows so the board reads as a fixed grid */}
            {emptyRows > 0 && state.phase === 'playing' &&
              Array.from({ length: emptyRows }).map((_, i) => (
                <GuessRow
                  key={`empty-${i}`}
                  index={state.attempts.length + 1 + i}
                  guess={emptyGuess(cfg.codeLength)}
                  feedback={null}
                  codeLength={cfg.codeLength}
                  active={false}
                  revealed={false}
                />
              ))}

            {/* On loss, show the revealed secret at the bottom */}
            {state.phase === 'lost' && (
              <div className="border-t-2 border-dashed border-[color-mix(in_srgb,var(--urgent)_40%,transparent)] px-3 py-2">
                <div className="mb-1 text-center font-mono text-[9px] uppercase tracking-wider text-[var(--urgent)]">
                  {t('mm.sealedSignal')}
                </div>
                <SecretRow secret={state.secret} revealed codeLength={cfg.codeLength} />
              </div>
            )}
          </div>
        </div>

        {/* Controls */}
        {state.phase === 'playing' && (
          <motion.div
            className="mt-4 bp-panel p-3"
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
          >
            <div className="mb-2 flex items-center justify-between">
              <span className="bp-label">{t('mm.channelPalette')}</span>
              <span className="font-mono text-[9px] text-[var(--faint)]">
                {t('mm.keyboardHint')}
              </span>
            </div>

            <Palette numColors={cfg.numColors} onPick={(p) => dispatch({ type: 'place', peg: p })} />

            <div className="mt-3 flex items-center gap-2">
              <button
                type="button"
                className="bp-cmd"
                onClick={() => dispatch({ type: 'backspace' })}
                disabled={state.draft.every((p) => p === null)}
              >
                ← {t('mm.clear')}
              </button>
              <button
                type="button"
                className="flex-1 justify-center border border-[color-mix(in_srgb,var(--primary)_45%,transparent)] py-1.5 font-mono text-[11px] font-bold uppercase tracking-wider text-[var(--primary)] transition-all hover:bg-[color-mix(in_srgb,var(--primary)_10%,transparent)]"
                style={{ borderRadius: 0 }}
                onClick={() => dispatch({ type: 'submit' })}
                disabled={!draftComplete}
              >
                {draftComplete ? `▶ ${t('mm.transmit')} (↵)` : t('mm.fillToTransmit')}
              </button>
            </div>
          </motion.div>
        )}

        {/* Legend */}
        <div className="mt-4 flex flex-wrap items-center justify-center gap-x-5 gap-y-2 px-2">
          <span className="flex items-center gap-1.5 font-mono text-[10px] text-[var(--muted-foreground)]">
            <span className="block h-2.5 w-2.5 rounded-full" style={{ background: 'var(--primary)' }} />
            {t('mm.locked')} · {t('mm.exact')}
          </span>
          <span className="flex items-center gap-1.5 font-mono text-[10px] text-[var(--muted-foreground)]">
            <span
              className="block h-2.5 w-2.5 rounded-full"
              style={{ border: '1.5px solid var(--primary)' }}
            />
            {t('mm.drift')} · {t('mm.partial')}
          </span>
          <span className="font-mono text-[10px] text-[var(--faint)]">
            {t('mm.legendNote', { colors: colors.length })}
          </span>
        </div>
      </div>

      <ResultOverlay
        open={showOverlay}
        won={state.phase === 'won'}
        secret={state.secret}
        guesses={state.attempts.length}
        best={best}
        isNewBest={isNewBest}
        onReplay={replay}
        onMenu={toMenu}
      />
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/*  Menu — difficulty selection                                               */
/* -------------------------------------------------------------------------- */

function Menu({
  onPick,
  t,
}: {
  onPick: (d: Difficulty) => void
  t: (k: string, o?: Record<string, unknown>) => string
}) {
  const cards: { d: Difficulty; code: string; desc: string }[] = [
    { d: 'easy', code: 'DWG-E', desc: t('mm.easyDesc') },
    { d: 'normal', code: 'DWG-N', desc: t('mm.normalDesc') },
    { d: 'hard', code: 'DWG-H', desc: t('mm.hardDesc') },
  ]

  return (
    <div className="bp-grid min-h-screen w-full px-4 py-10 sm:px-6">
      <div className="mx-auto w-full max-w-2xl">
        <div className="mb-6 flex items-baseline justify-between">
          <div>
            <span className="bp-label">DWG-DEMO · SIGNAL DECRYPTOR</span>
            <h1 className="mt-1 font-mono text-2xl font-bold tracking-tight text-foreground">
              MASTERMIND
            </h1>
            <p className="mt-1 max-w-md font-mono text-[11px] leading-relaxed text-[var(--muted-foreground)]">
              {t('mm.intro')}
            </p>
          </div>
          <Link
            to="/"
            className="font-mono text-[10px] uppercase tracking-wider text-[var(--faint)] transition-colors hover:text-foreground"
          >
            ← EXIT
          </Link>
        </div>

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          {cards.map((c) => {
            const cfg = DIFFICULTY_PRESETS[c.d]
            const cardBest = getBest(c.d)
            return (
              <motion.button
                key={c.d}
                type="button"
                onClick={() => onPick(c.d)}
                className="bp-panel group p-4 text-left transition-colors hover:bg-[color-mix(in_srgb,var(--primary)_4%,transparent)]"
                whileHover={{ y: -3 }}
                whileTap={{ scale: 0.98 }}
              >
                <div className="flex items-center justify-between">
                  <span className="bp-label">{c.code}</span>
                  <span className="font-mono text-[9px] uppercase text-[var(--faint)]">{c.d}</span>
                </div>
                <h3 className="mt-2 font-mono text-lg font-bold uppercase tracking-wide text-foreground">
                  {c.d}
                </h3>
                <p className="mt-1 font-mono text-[10px] leading-relaxed text-[var(--muted-foreground)]">
                  {c.desc}
                </p>
                <div className="mt-3 flex items-center justify-between border-t border-[color-mix(in_srgb,var(--primary)_15%,transparent)] pt-2 font-mono text-[9px] text-[var(--faint)]">
                  <span>{cfg.codeLength}×{cfg.numColors} {cfg.allowDuplicates ? '· DUP' : '· UNIQ'}</span>
                  <span>{t('mm.tries')}: {cfg.maxGuesses}</span>
                </div>
                {cardBest !== null && (
                  <div className="mt-1 font-mono text-[9px]" style={{ color: 'var(--ok)' }}>
                    {t('mm.best')}: {cardBest}
                  </div>
                )}
              </motion.button>
            )
          })}
        </div>

        {/* Rules */}
        <div className="bp-panel mt-4 p-4">
          <div className="bp-label mb-2">{t('mm.rules')}</div>
          <ul className="space-y-1.5 font-mono text-[11px] leading-relaxed text-[var(--muted-foreground)]">
            <li>· {t('mm.rule1')}</li>
            <li>· {t('mm.rule2')}</li>
            <li>· {t('mm.rule3')}</li>
            <li>· {t('mm.rule4')}</li>
          </ul>
        </div>

        <p className="mt-4 text-center font-mono text-[10px] text-[var(--faint)]">
          {t('mm.routeNote')} · <Link to="/demo/plotter" className="underline hover:text-foreground">plotter</Link>
        </p>
      </div>
    </div>
  )
}
