import { defineConfig } from 'vitest/config'
import { fileURLToPath } from 'node:url'
import { contractAliases } from '../../../../tooling/vitest-extensions.mjs'
export default defineConfig({
  resolve: { alias: {
    // The `@extensions/<id>/contract.js` mapping has one source of truth; a
    // hand-written copy here is what drifted when the carrier moved.
    ...contractAliases(),
    '@ordessa/extension-api': fileURLToPath(new URL('../../../../packages/desktop-platform/extension-api/src/index.ts', import.meta.url)),
  } },
  test: { include: ['tests/**/*.test.ts'] },
})
