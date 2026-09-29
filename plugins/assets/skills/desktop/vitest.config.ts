import { defineConfig } from 'vitest/config'
import { fileURLToPath } from 'node:url'
export default defineConfig({
  resolve: { alias: {
    // Same seam the product build uses: the foundation contract is the shared
    // Token surface (Workbench), never a host-internal import.
    '@extensions/ordessa.contracts/contract.js': fileURLToPath(new URL('../../../../packages/desktop-platform/contracts/foundation/src/contract.ts', import.meta.url)),
    // The chat-api shared module (checkpoint 3d8c3fa410): Skills consumes the
    // published contract surface only, the same alias shape the chat packages
    // use among themselves — no deep import of a host-internal path.
    '@extensions/ordessa.chat-api/contract.js': fileURLToPath(new URL('../../../chat/api/src/contract.ts', import.meta.url)),
  } },
  test: { include: ['tests/**/*.test.tsx', 'tests/**/*.test.ts'], environment: 'jsdom' },
})
