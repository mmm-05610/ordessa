import { defineConfig } from 'vitest/config'

// Package-local runner; the root `npm test` aggregates this suite through
// tooling/test-all.mjs (T021), which discovers every workspace package that declares
// its own `test` script.
export default defineConfig({ test: { include: ['src/**/*.test.ts'], maxWorkers: 1 } })
