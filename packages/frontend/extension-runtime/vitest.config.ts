import { defineConfig } from 'vitest/config'
import { fileURLToPath } from 'node:url'

// Merged runtime runner (T008-01): one config covering loader + host suites.
// Contract carrier aliases resolve to the platform's public carrier exactly
// as a third-party extension must (PA-24 / FR-09).
export default defineConfig({
  resolve: { alias: {
    '@extensions/ordessa.contracts/contract.js': fileURLToPath(new URL('../contracts/foundation/src/contract.ts', import.meta.url)),
  } },
  test: {
    include: ['tests/**/*.test.ts', 'host/tests/**/*.test.ts', 'host/tests/**/*.test.tsx', 'loader/tests/**/*.test.ts'],
    maxWorkers: 1,
  },
})
