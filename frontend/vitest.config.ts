import { defineConfig } from 'vitest/config'
import path from 'node:path'

// Vitest runs alongside Vite. Discovery covers both the unit tests next to
// the source (`src/**/*.test.*`) and the P0/navigation contract tests under
// `tests/`; both suites are pure-logic, so no DOM/jsdom environment is needed.
export default defineConfig({
  resolve: {
    alias: { '@': path.resolve(import.meta.dirname, './src') },
  },
  test: {
    environment: 'node',
    include: ['src/**/*.test.{ts,tsx}', 'tests/**/*.test.{ts,tsx}'],
  },
})
