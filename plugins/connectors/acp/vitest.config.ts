import { defineConfig } from 'vitest/config'
import { contractAliases } from '../../../tooling/vitest-extensions.mjs'

// Package-local runner for the ACP connector plugin. Aliases come from the single
// source of truth (`tooling/vitest-extensions.mjs`); `@ordessa/*` packages resolve
// through the hoisted root workspace node_modules, same as the other lanes.
export default defineConfig({
  resolve: { alias: contractAliases() },
  test: { include: ['tests/**/*.test.ts'], maxWorkers: 1 },
})
