// T019 (FR-010) — the desktop shell keeps only host tests. Business unit tests moved to their
// owning packages (see specs/010-platform-core/reports/C-baseline/t019-migration-plan.md); this
// freezes the resulting host-test set so a business suite cannot be dropped back into
// apps/desktop/renderer and simply join the app's run by matching its `renderer/**/*.test.*` glob.
// A new host test must be added here deliberately, with a reason.
import assert from 'node:assert/strict'
import { readdir } from 'node:fs/promises'
import path from 'node:path'
import test from 'node:test'

const repoRoot = path.resolve(import.meta.dirname, '..', '..', '..')
const HOST_SUITES = ['foundation.test.tsx', 'host.test.tsx', 'loader.test.ts']

test('apps/desktop/renderer holds exactly the frozen host test suites', async () => {
  const files = (await readdir(path.join(repoRoot, 'apps/desktop/renderer')))
    .filter(name => /\.test\.[cm]?[jt]sx?$/.test(name)).sort()
  assert.deepEqual(files, [...HOST_SUITES].sort(),
    'FR-010: only startup/window/IPC/host suites may live in the app shell — a business suite belongs in its plugin or in products/desktop')
})
