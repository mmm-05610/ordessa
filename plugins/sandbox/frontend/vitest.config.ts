import { defineConfig } from 'vitest/config'
import { fileURLToPath } from 'node:url'
export default defineConfig({
  resolve: { alias: {
    '@extensions/ordessa.contracts/contract.js': fileURLToPath(new URL('../../../../packages/desktop-platform/contracts/foundation/src/contract.ts', import.meta.url)),
    '@ordessa/extension-api': fileURLToPath(new URL('../../../../packages/desktop-platform/extension-api/src/index.ts', import.meta.url)),
    '@ordessa/ui': fileURLToPath(new URL('../../../../packages/desktop-platform/ui/src/index.ts', import.meta.url)),
  } },
  // Node by default; the DOM suites opt in with a `@vitest-environment jsdom`
  // pragma so the file-system guard suites keep real file: module URLs.
  test: { include: ['tests/**/*.test.ts', 'tests/**/*.test.tsx'] },
})
