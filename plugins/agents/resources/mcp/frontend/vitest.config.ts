import { defineConfig } from 'vitest/config'
import { fileURLToPath } from 'node:url'
// Package-local runner (mirrors plugins/workbench/chat/frontend). The `@extensions/...`
// specifiers map to the real contract sources — this package consumes the
// chat-api r3 and foundation contracts, never a copied type.
export default defineConfig({
  resolve: { alias: {
    '@extensions/ordessa.chat-api/contract.js': fileURLToPath(new URL('../../chat/api/src/contract.ts', import.meta.url)),
    '@extensions/ordessa.contracts/contract.js': fileURLToPath(new URL('../../../../../packages/interfaces/channels/workbench/extension-api/contracts/foundation/src/contract.ts', import.meta.url)),
    '@ordessa/extension-api': fileURLToPath(new URL('../../../../../packages/interfaces/channels/workbench/extension-api/src/index.ts', import.meta.url)),
    '@ordessa/ui-components/api': fileURLToPath(new URL('../../../../../packages/interfaces/channels/workbench/extension-runtime/ui-components/api/ui-components.ts', import.meta.url)),
  } },
  test: { include: ['tests/**/*.test.ts', 'tests/**/*.test.tsx'], environment: 'jsdom', maxWorkers: 1 },
})
