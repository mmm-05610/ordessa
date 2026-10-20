import { defineConfig } from 'vitest/config'
import { contractAliases } from '../../../../tooling/dev/vitest-extensions.mjs'
export default defineConfig({
  resolve: { alias: contractAliases() },
  test: { include: ['tests/**/*.test.ts'], maxWorkers: 1 },
})
