import { defineConfig } from 'vitest/config'
import { contractAliases } from '../../tooling/vitest-extensions.mjs'
export default defineConfig({
  resolve: { alias: contractAliases() },
  // 宿主 UI 与主进程的门都在这里：renderer 下的既有测试 + 013 新增的 tests/。
  test: { include: ['renderer/**/*.test.tsx', 'renderer/**/*.test.ts', 'tests/**/*.test.tsx', 'tests/**/*.test.ts'] },
})
