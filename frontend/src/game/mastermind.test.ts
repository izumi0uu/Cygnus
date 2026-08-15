import { describe, expect, it } from 'vitest'
import {
  DIFFICULTY_PRESETS,
  evaluateGuess,
  emptyGuess,
  generateSecret,
  isGuessComplete,
  isWin,
  type Code,
} from './mastermind'

/** Deterministic RNG for reproducible tests (LCG, returns [0, 1)). */
function seededRng(seed: number): () => number {
  let state = seed >>> 0
  return () => {
    state = (state * 1664525 + 1013904223) >>> 0
    return state / 0x100000000
  }
}

describe('generateSecret', () => {
  it('is deterministic for a fixed seed', () => {
    const first = generateSecret(DIFFICULTY_PRESETS.normal, seededRng(42))
    const second = generateSecret(DIFFICULTY_PRESETS.normal, seededRng(42))
    expect(first).toEqual(second)
    expect(first).toHaveLength(DIFFICULTY_PRESETS.normal.codeLength)
  })

  it('never repeats a color when duplicates are disallowed', () => {
    const secret = generateSecret(DIFFICULTY_PRESETS.easy, seededRng(7))
    expect(new Set(secret).size).toBe(secret.length)
  })
})

describe('evaluateGuess', () => {
  it('reports all exact on a perfect guess', () => {
    const secret: Code = [0, 1, 2, 3]
    expect(evaluateGuess(secret, secret)).toEqual({ exact: 4, partial: 0 })
  })

  it('counts a color only once across secret and guess (duplicate handling)', () => {
    // Classic ambiguity: secret has one 1, guess has two 1s — only one
    // partial is awarded, never two.
    expect(evaluateGuess([1, 0, 0, 0], [1, 1, 1, 1])).toEqual({
      exact: 1,
      partial: 0,
    })
  })

  it('awards partials for right colors in the wrong positions', () => {
    expect(evaluateGuess([0, 1, 2, 3], [3, 2, 1, 0])).toEqual({
      exact: 0,
      partial: 4,
    })
  })
})

describe('isWin / emptyGuess / isGuessComplete', () => {
  it('wins only when every channel is exact', () => {
    expect(isWin({ exact: 4, partial: 0 }, 4)).toBe(true)
    expect(isWin({ exact: 3, partial: 1 }, 4)).toBe(false)
  })

  it('builds an empty guess row of the configured length', () => {
    expect(emptyGuess(4)).toEqual([null, null, null, null])
  })

  it('detects a fully filled guess row', () => {
    expect(isGuessComplete([0, 1, 2, 3])).toBe(true)
    expect(isGuessComplete([0, null, 2, 3])).toBe(false)
  })
})
