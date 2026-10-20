import { mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import path from 'node:path'
import assert from 'node:assert/strict'
import { launchSmoke } from '../support/launch-smoke.mjs'
const home = await mkdtemp(path.join(tmpdir(), 'ordessa-empty-smoke-'))
try {
  const result = await launchSmoke(home)
  assert.equal(result.ready, true); assert.equal(result.nodeAbsent, true)
  assert.deepEqual(result.pages, []); assert.deepEqual(result.errors, [])
  assert.deepEqual(result.bridgeKeys, ['read'])
  console.log(JSON.stringify(result))
} finally { await rm(home, { recursive: true, force: true }) }
