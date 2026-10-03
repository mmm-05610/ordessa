// migrated from plugins/model-provider@9305563719d25e04076b9221a7284660bd8f8642
// (vitest.config.ts; alias depth adjusted for plugins/model-provider/desktop)
import { defineConfig } from 'vitest/config'
import { fileURLToPath } from 'node:url'
export default defineConfig({
  resolve: { alias: {
    '@extensions/ordessa.profile-api/contract.js': fileURLToPath(new URL('../../profile/api/src/index.ts', import.meta.url)),
    '@extensions/ordessa.contracts/contract.js': fileURLToPath(new URL('../../../packages/desktop-platform/contracts/foundation/src/contract.ts', import.meta.url)),
  } },
  test: { include: ['tests/**/*.test.tsx', 'tests/**/*.test.ts'] },
})
