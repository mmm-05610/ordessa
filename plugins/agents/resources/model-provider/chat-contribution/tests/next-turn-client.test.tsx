import assert from 'node:assert/strict'
import { access, readFile } from 'node:fs/promises'
import { it } from 'vitest'

it('retired next-turn transport is unreachable from the built Model Provider Chat entry', async () => {
  await assert.rejects(access(new URL('../src/next-turn-client.ts', import.meta.url)))
  const entry = await readFile(new URL('../src/entry.tsx', import.meta.url), 'utf8')
  const selector = await readFile(new URL('../src/canonical-selector.tsx', import.meta.url), 'utf8')
  for (const oldMethod of ['chooseForSession', 'queryChoice', 'beginTurnApplication', 'reconcileChoice',
    'agent.config.', 'profiles.v2.', 'profile-overlay', 'handover-failed']) {
    assert.ok(!entry.includes(oldMethod), `entry must not invoke ${oldMethod}`)
    assert.ok(!selector.includes(oldMethod), `selector must not invoke ${oldMethod}`)
  }
})
