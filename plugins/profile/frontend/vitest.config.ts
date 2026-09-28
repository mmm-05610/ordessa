import { defineConfig } from 'vitest/config'
import { fileURLToPath } from 'node:url'

export default defineConfig({
  resolve: {
    alias: {
      '@ordessa/plugin-profile-api': fileURLToPath(new URL('../api/src/index.ts', import.meta.url)),
      '@ordessa/extension-api': fileURLToPath(new URL('../../../../packages/desktop-platform/extension-api/src/index.ts', import.meta.url)),
    },
  },
  test: { include: ['tests/**/*.test.ts', 'tests/**/*.test.tsx'], maxWorkers: 1 },
})
