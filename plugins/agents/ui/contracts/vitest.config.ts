import { defineConfig } from 'vitest/config'
import { fileURLToPath } from 'node:url'

export default defineConfig({
  resolve: { alias: {
    '@extensions/ordessa.contracts/contract.js': fileURLToPath(new URL('../../../../packages/interfaces/channels/workbench/extension-api/contracts/foundation/src/contract.ts', import.meta.url)),
  } },
  test: { include: ['tests/**/*.test.ts', 'tests/**/*.test.tsx'] },
})
