/**
 * Mastermind — pure game logic.
 *
 * The "codemaster" is the rules engine in this file: it mints the secret
 * code and, given a guess, returns the alignment feedback. Everything here
 * is framework-agnostic and deterministic given an RNG, so it can be unit
 * tested in isolation and shared between the UI and any future AI solver.
 *
 * Terminology is mapped to the Cygnus console metaphor:
 *   peg     → a frequency channel (one of N colors)
 *   code    → the sealed signal the operator must decode
 *   guess   → a probe transmitted against the signal
 *   exact   → channel locked (right color, right position)
 *   partial → channel drift  (right color, wrong position)
 */

/** A single peg color, indexed into PEG_COLORS. */
export type Peg = number

/** A code or guess — an array of pegs whose length is `codeLength`. */
export type Code = Peg[]

export interface Feedback {
  /** Right color AND right position (classic "black" peg). */
  exact: number
  /** Right color, wrong position (classic "white" peg). */
  partial: number
}

export type Difficulty = 'easy' | 'normal' | 'hard'

export interface MastermindConfig {
  /** Number of pegs per code. */
  codeLength: number
  /** Number of distinct colors available. */
  numColors: number
  /** Maximum guesses before the signal is considered lost. */
  maxGuesses: number
  /** Whether the secret may repeat a color. */
  allowDuplicates: boolean
}

/** Difficulty presets — tuned for a satisfying difficulty curve. */
export const DIFFICULTY_PRESETS: Record<Difficulty, MastermindConfig> = {
  easy: { codeLength: 4, numColors: 6, maxGuesses: 12, allowDuplicates: false },
  normal: { codeLength: 4, numColors: 6, maxGuesses: 10, allowDuplicates: true },
  hard: { codeLength: 5, numColors: 6, maxGuesses: 8, allowDuplicates: true },
}

/**
 * The six channel colors. Fixed hex (not CSS vars) so a peg reads identically
 * on the light and dark blueprint — the signal is the signal regardless of
 * console theme. Each entry carries a stable `key` used for i18n labels and
 * a `hint` digit shown in the palette so the channels are distinguishable
 * without relying on color alone (colorblind-friendly + keyboard hint).
 */
export interface PegColor {
  id: Peg
  hex: string
  key: string
  hint: string
}

export const PEG_COLORS: PegColor[] = [
  { id: 0, hex: '#2563eb', key: 'azure', hint: '1' },
  { id: 1, hex: '#e5484d', key: 'crimson', hint: '2' },
  { id: 2, hex: '#16a34a', key: 'jade', hint: '3' },
  { id: 3, hex: '#f59e0b', key: 'amber', hint: '4' },
  { id: 4, hex: '#9333ea', key: 'violet', hint: '5' },
  { id: 5, hex: '#0891b2', key: 'cyan', hint: '6' },
]

/**
 * Generate a secret code honoring the config. Pass a seeded RNG for
 * deterministic tests; defaults to Math.random for real play.
 */
export function generateSecret(
  config: MastermindConfig,
  rng: () => number = Math.random,
): Code {
  const pool: Peg[] = Array.from({ length: config.numColors }, (_, i) => i)

  if (!config.allowDuplicates) {
    // Fisher–Yates shuffle of the pool, take the first codeLength.
    for (let i = pool.length - 1; i > 0; i--) {
      const j = Math.floor(rng() * (i + 1))
      ;[pool[i], pool[j]] = [pool[j], pool[i]]
    }
    return pool.slice(0, config.codeLength)
  }

  return Array.from({ length: config.codeLength }, () =>
    Math.floor(rng() * config.numColors),
  )
}

/**
 * Evaluate a guess against the secret using the canonical Mastermind algorithm
 * that handles duplicate colors correctly: each peg in the secret can only be
 * "spent" once, exact matches taking priority over partial matches.
 */
export function evaluateGuess(secret: Code, guess: Code): Feedback {
  let exact = 0
  const secretRemaining: Record<number, number> = {}
  const guessRemaining: Record<number, number> = {}

  // First pass: count exact matches and bucket the rest by color.
  for (let i = 0; i < secret.length; i++) {
    if (secret[i] === guess[i]) {
      exact++
    } else {
      secretRemaining[secret[i]] = (secretRemaining[secret[i]] ?? 0) + 1
      guessRemaining[guess[i]] = (guessRemaining[guess[i]] ?? 0) + 1
    }
  }

  // Second pass: a partial is each leftover guess color that the secret still
  // has in stock — min of the two leftovers, summed over colors.
  let partial = 0
  for (const color of Object.keys(guessRemaining)) {
    const c = Number(color)
    partial += Math.min(guessRemaining[c] ?? 0, secretRemaining[c] ?? 0)
  }

  return { exact, partial }
}

/** A guess wins when every channel is locked (all exact). */
export function isWin(feedback: Feedback, codeLength: number): boolean {
  return feedback.exact === codeLength
}

/** An empty guess slot array (all nulls) for a fresh input row. */
export function emptyGuess(codeLength: number): (Peg | null)[] {
  return Array.from({ length: codeLength }, () => null)
}

/** True when every slot of the in-progress guess is filled. */
export function isGuessComplete(guess: (Peg | null)[]): boolean {
  return guess.every((p) => p !== null)
}

/** Best-score storage — fewest guesses to decode, per difficulty. */
const BEST_KEY = 'cygnus-mastermind-best'

export function getBest(difficulty: Difficulty): number | null {
  try {
    const raw = localStorage.getItem(BEST_KEY)
    if (!raw) return null
    const map = JSON.parse(raw) as Partial<Record<Difficulty, number>>
    const v = map[difficulty]
    return typeof v === 'number' && v > 0 ? v : null
  } catch {
    return null
  }
}

export function maybeSetBest(difficulty: Difficulty, guesses: number): boolean {
  try {
    const raw = localStorage.getItem(BEST_KEY)
    const map = raw ? (JSON.parse(raw) as Partial<Record<Difficulty, number>>) : {}
    const prev = map[difficulty]
    if (typeof prev !== 'number' || guesses < prev) {
      map[difficulty] = guesses
      localStorage.setItem(BEST_KEY, JSON.stringify(map))
      return true
    }
    return false
  } catch {
    return false
  }
}
