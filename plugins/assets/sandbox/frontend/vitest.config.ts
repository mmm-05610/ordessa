import { defineConfig } from 'vitest/config'
import { fileURLToPath } from 'node:url'
export default defineConfig({
  resolve: { alias: {
    '@extensions/ordessa.contracts/contract.js': fileURLToPath(new URL('../../../packages/frontend/contracts/foundation/src/contract.ts', import.meta.url)),
    '@ordessa/extension-api': fileURLToPath(new URL('../../../packages/frontend/extension-api/src/index.ts', import.meta.url)),
    '@ordessa/ui': fileURLToPath(new URL('../../../packages/frontend/ui/src/index.ts', import.meta.url)),
  } },
  // Node by default; the DOM suites opt in with a `@vitest-environment jsdom`
  // pragma so the file-system guard suites keep real file: module URLs.
  test: { include: ['tests/**/*.test.ts', 'tests/**/*.test.tsx'] },
})
