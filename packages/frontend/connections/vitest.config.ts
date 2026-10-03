import { defineConfig } from 'vitest/config'
import { fileURLToPath } from 'node:url'

// Package-local runner. `@ordessa/extension-api` resolves through the root
// workspace symlink (same as apps/desktop tests); the api subpath is aliased
// because the package is not yet linked into node_modules/@ordessa.
export default defineConfig({
  resolve: { alias: {
    '@ordessa/connections/api': fileURLToPath(new URL('./api/connections.ts', import.meta.url)),
  } },
  test: { include: ['tests/**/*.test.ts'], maxWorkers: 1 },
})
