import { defineConfig } from 'vitest/config'
import { fileURLToPath } from 'node:url'
export default defineConfig({
  resolve: { alias: {
    '@extensions/ordessa.contracts/contract.js': fileURLToPath(new URL('../../../../packages/desktop-platform/contracts/foundation/src/contract.ts', import.meta.url)),
    // consumed checkpoint chat-api READY @ 54ad26c15d (fixed SHA merged into this branch)
    '@extensions/ordessa.chat-api/contract.js': fileURLToPath(new URL('../../../../plugins/chat/api/src/contract.ts', import.meta.url)),
    // T4.1: the production entry binds its component key through the real
    // ui-components platform, so the outlet is resolved against the real
    // package rather than a local stand-in.
    '@ordessa/ui-components/react': fileURLToPath(new URL('../../../../packages/desktop-platform/ui-components/react/index.ts', import.meta.url)),
    '@ordessa/ui-components/api': fileURLToPath(new URL('../../../../packages/desktop-platform/ui-components/api/ui-components.ts', import.meta.url)),
  } },
  test: { include: ['tests/**/*.test.tsx', 'tests/**/*.test.ts'] },
})
