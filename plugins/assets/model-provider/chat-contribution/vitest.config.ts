import { defineConfig } from 'vitest/config'
import { fileURLToPath } from 'node:url'
export default defineConfig({
  resolve: { alias: {
    '@extensions/ordessa.contracts/contract.js': fileURLToPath(new URL('../../../../packages/desktop-platform/contracts/foundation/src/contract.ts', import.meta.url)),
    // consumed checkpoint chat-api READY @ 54ad26c15d (fixed SHA merged into this branch)
    '@extensions/ordessa.chat-api/contract.js': fileURLToPath(new URL('../../../../plugins/chat/api/src/contract.ts', import.meta.url)),
  } },
  test: { include: ['tests/**/*.test.tsx', 'tests/**/*.test.ts'] },
})
