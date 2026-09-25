import { defineConfig } from 'vitest/config'
import { fileURLToPath } from 'node:url'
export default defineConfig({
  resolve: { alias: {
    '@extensions/ordessa.contracts/contract.js': fileURLToPath(new URL('../../packages/desktop-platform/contracts/foundation/src/contract.ts', import.meta.url)),
    '@extensions/ordessa.agent-contracts/contract.js': fileURLToPath(new URL('../../packages/desktop-platform/contracts/agent-ui/src/contract.ts', import.meta.url)),
  } },
  test: { include: ['tests/**/*.test.tsx', 'tests/**/*.test.ts'] },
})
