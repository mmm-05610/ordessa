import { defineConfig } from 'vitest/config'
import { contractAliases } from '../../tooling/vitest-extensions.mjs'
export default defineConfig({
  resolve: { alias: contractAliases() },
  test: { include: ['tests/**/*.test.tsx', 'tests/**/*.test.ts'] },
})
