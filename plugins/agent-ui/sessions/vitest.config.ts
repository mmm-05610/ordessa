import { defineConfig } from 'vitest/config'
import { contractAliases } from '../../../tooling/vitest-extensions.mjs'
export default defineConfig({
  resolve: { alias: contractAliases() },
  test: { include: ['tests/**/*.test.ts', 'tests/**/*.test.tsx'], maxWorkers: 1 },
})
