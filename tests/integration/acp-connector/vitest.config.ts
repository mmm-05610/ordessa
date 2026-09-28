import { defineConfig } from 'vitest/config'
import { fileURLToPath } from 'node:url'
import { contractAliases } from '../../../tooling/vitest-extensions.mjs'

// Uses the same contract alias map the product configs use (tooling/vitest-extensions.mjs), so
// the tests exercise the very same contract modules the product imports; nothing here is a
// test-only re-implementation of a contract.
export default defineConfig({
  resolve: { alias: contractAliases() },
  test: {
    root: fileURLToPath(new URL('.', import.meta.url)),
    include: ['fixtures/**/*.test.ts', 'protocol/**/*.test.ts', 'ui/**/*.test.tsx'],
    environment: 'node',
    // jsdom files run through vite's client pipeline, where a computed `import(fileUrl)` is
    // rewritten to a dev-server URL and handed to the native Node loader. These scoped hooks map
    // ONLY that request back to the real TypeScript sources — the seam still imports the actual
    // production module, nothing is stubbed (see acp-ts-hooks.mjs).
    execArgv: ['--import', fileURLToPath(new URL('./register-acp-ts-hooks.mjs', import.meta.url))],
    // One agent per file, serially, like the rest of the repo (AGENTS.md: tests run serially).
    fileParallelism: false,
    maxWorkers: 1,
    server: {
      // The target module lives above this root and must still be transformed by vite (contract
      // aliases, TS), not by the native Node loader (node-environment files).
      deps: { inline: [/plugins\/connectors\/acp/] },
    },
  },
})
