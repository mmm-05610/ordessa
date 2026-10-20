import { defineConfig } from 'vitest/config'
export default defineConfig({ test: { include: ['src/**/*.test.ts', '../../packages/interfaces/channels/workbench/status-board/src/tests/**/*.test.{ts,tsx}'], environment: 'jsdom' } })
