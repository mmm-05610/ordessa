import { defineConfig } from 'vitest/config'
import { fileURLToPath } from 'node:url'

// Package-local runner. The platform services published to plugins are imported
// through the public contract carrier exactly as a third-party extension must,
// so the suite also proves the carrier is self-sufficient (PA-24).
// 别名直接指向平台内的公开载体：平台包不得引用 desktop-platform 之外的路径（FR-009）。
export default defineConfig({
  resolve: { alias: {
    '@extensions/ordessa.contracts/contract.js': fileURLToPath(new URL('../contracts/foundation/src/contract.ts', import.meta.url)),
  } },
  test: { include: ['tests/**/*.test.ts', 'tests/**/*.test.tsx'], maxWorkers: 1 },
})
