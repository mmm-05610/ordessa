import { defineConfig } from 'vitest/config'
import { fileURLToPath } from 'node:url'
export default defineConfig({
  resolve: { alias: {
    '@ordessa/ui-components/react': fileURLToPath(new URL('../../../../packages/interfaces/channels/workbench/extension-runtime/ui-components/react/index.ts', import.meta.url)),
    '@extensions/ordessa.chat-api/contract.js': fileURLToPath(new URL('../api/src/contract.ts', import.meta.url)),
    '@extensions/ordessa.contracts/contract.js': fileURLToPath(new URL('../../../../packages/interfaces/channels/workbench/extension-api/contracts/foundation/src/contract.ts', import.meta.url)),
    '@extensions/ordessa.agent-contracts/contract.js': fileURLToPath(new URL('../../agent-ui/contracts/src/contract.ts', import.meta.url)),
    '@ordessa/extension-api': fileURLToPath(new URL('../../../../packages/interfaces/channels/workbench/extension-api/src/index.ts', import.meta.url)),
    '@ordessa/ui-components/api': fileURLToPath(new URL('../../../../packages/interfaces/channels/workbench/extension-runtime/ui-components/api/ui-components.ts', import.meta.url)),
  } },
  test: { include: ['tests/**/*.test.tsx', 'tests/**/*.test.ts'], environment: 'jsdom' },
})
