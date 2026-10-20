import { defineConfig } from 'vitest/config'
import { contractAliases } from '../../../../tooling/dev/vitest-extensions.mjs'

// Product-level UI suites for the assembled desktop product. They live in `../../tests/product-ui/` rather than
// `tests/` on purpose: `tests/` is driven by `node --test` (the real-build guards), whose file
// patterns also match .tsx, so a vitest-only JSX suite would be handed to the wrong runner.
export default defineConfig({
  resolve: { alias: contractAliases() },
  test: { include: ['../../tests/product-ui/**/*.test.tsx'], maxWorkers: 1 },
})
