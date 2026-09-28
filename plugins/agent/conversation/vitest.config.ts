import { defineConfig } from 'vitest/config'
import { contractAliases } from '../../../tooling/vitest-extensions.mjs'

// Package-local runner. Bare `@ordessa/*`, `react`, `@assistant-ui/react` and friends
// resolve through the hoisted root workspace node_modules (same as the other
// package-local configs); the contract carrier specifiers come from the single
// shared alias source.
export default defineConfig({
  resolve: { alias: contractAliases() },
  test: { include: ['tests/**/*.test.ts', 'tests/**/*.test.tsx'], maxWorkers: 1 },
})
