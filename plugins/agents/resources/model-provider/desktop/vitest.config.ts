// migrated from plugins/model-provider@9305563719d25e04076b9221a7284660bd8f8642
// (vitest.config.ts; alias depth adjusted for plugins/model-provider/desktop)
import { defineConfig } from 'vitest/config'
import { fileURLToPath } from 'node:url'
export default defineConfig({
  resolve: { alias: {
    '@extensions/ordessa.model-provider/contract.js': fileURLToPath(new URL('./src/contract.ts', import.meta.url)),
    '@extensions/ordessa.contracts/contract.js': fileURLToPath(new URL('../../../../../packages/interfaces/channels/workbench/extension-api/contracts/foundation/src/contract.ts', import.meta.url)),
  } },
  test: { include: ['tests/**/*.test.tsx', 'tests/**/*.test.ts'] },
})
