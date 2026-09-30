import { defineConfig } from 'vitest/config'
import { fileURLToPath } from 'node:url'

export default defineConfig({
  resolve: {
    alias: {
      // chat-api is consumed through its carrier specifier; the alias mirrors
      // plugins/chat/api/vitest.config.ts (shared registration in C0's
      // tooling/vitest-extensions.mjs is an integration request).
      '@extensions/ordessa.chat-api/contract.js': fileURLToPath(new URL('../../../chat/api/src/contract.ts', import.meta.url)),
      '@extensions/ordessa.profile-api/contract.js': fileURLToPath(new URL('../../api/src/index.ts', import.meta.url)),
      '@extensions/ordessa.contracts/contract.js': fileURLToPath(new URL('../../../../packages/desktop-platform/contracts/foundation/src/contract.ts', import.meta.url)),
      '@ordessa/ui-components/api': fileURLToPath(new URL('../../../../packages/desktop-platform/ui-components/api/ui-components.ts', import.meta.url)),
      '@ordessa/plugin-profile-api': fileURLToPath(new URL('../../api/src/index.ts', import.meta.url)),
      '@ordessa/extension-api': fileURLToPath(new URL('../../../../packages/desktop-platform/extension-api/src/index.ts', import.meta.url)),
    },
  },
  test: { include: ['tests/**/*.test.ts', 'tests/**/*.test.tsx'], maxWorkers: 1 },
})
