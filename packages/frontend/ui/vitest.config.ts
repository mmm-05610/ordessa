import { defineConfig } from 'vitest/config'

// Package-local runner (UIB002–UIB004, C8): every test file here is a jsdom
// React test that opts in with a `// @vitest-environment jsdom` docblock, so
// the include pattern only has to cover *.test.tsx. Tests resolve react and
// react-dom through the root workspace hoist; this package declares no
// runtime dependencies and must never gain one on the registry
// (`@ordessa/ui-components`) — C8 ruling 6 keeps `ui` registry-free.
export default defineConfig({
  test: { include: ['tests/**/*.test.tsx'], maxWorkers: 1 },
})
