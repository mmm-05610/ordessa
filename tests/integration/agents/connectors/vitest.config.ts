import { defineConfig } from 'vitest/config'
import { contractAliases } from '../../../../tooling/dev/vitest-extensions.mjs'

export default defineConfig({
  resolve: { alias: contractAliases() },
  test: { include: ['acp/*.test.ts', 'ordessa/*.test.ts'], environment: 'node', fileParallelism: false, maxWorkers: 1 },
})
