import { defineConfig } from 'vitest/config'

// Package-local runner (T032/T033): node lane for the registry core, and a jsdom
// lane for the React tests — each React test file opts in with a
// `// @vitest-environment jsdom` docblock so the core tests keep running in node
// under one config. `@ordessa/extension-api`, react and react-dom resolve
// through the root workspace symlink/hoist.
export default defineConfig({
  test: { include: ['tests/**/*.test.ts', 'tests/**/*.test.tsx'], maxWorkers: 1 },
})
