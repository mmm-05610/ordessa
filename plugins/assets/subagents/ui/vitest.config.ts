import { defineConfig } from 'vitest/config'
import { fileURLToPath } from 'node:url'
export default defineConfig({
  resolve: { alias: {
    '@extensions/ordessa.chat-api/contract.js': fileURLToPath(new URL('../../../chat/api/src/contract.ts', import.meta.url)),
    '@ordessa/extension-api': fileURLToPath(new URL('../../../../packages/desktop-platform/extension-api/src/index.ts', import.meta.url)),
  } },
  test: { include: ['tests/**/*.test.ts'] },
})
