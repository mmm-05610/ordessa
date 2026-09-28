import { defineConfig } from 'vitest/config'
import { contractAliases } from '../../../tooling/vitest-extensions.mjs'

// Package-local runner (T019). The `@extensions/<id>/contract.js` mappings come from the shared
// helper, never a hand-copied alias list; `@ordessa/*` packages and react/jsdom resolve through
// the hoisted root node_modules, same as packages/desktop-platform/connections.
export default defineConfig({
  resolve: { alias: contractAliases() },
  test: { include: ['tests/**/*.test.ts', 'tests/**/*.test.tsx'], maxWorkers: 1 },
})
