import test from 'node:test'
import assert from 'node:assert/strict'
import { enhanceSource } from './enhance.mjs'
import { build as codex } from '../builders/build-codex-runtime-artifact.mjs'
import { build as claude } from '../builders/build-claude-runtime-artifact.mjs'

test('enhancement refuses upstream content drift and unknown brands', () => {
  for (const brand of ['codex', 'claude-code', 'unknown'])
    assert.throws(() => enhanceSource('export default {}', brand), /source digest mismatch/)
})
test('builder enhancement flags are explicit and cannot upgrade a legacy Claude alias', () => {
  assert.throws(() => codex({ profileBridge: 'true' }), /profileBridge must be boolean/)
  assert.throws(() => claude({ profileBridge: true, variant: 'legacy-alias' }), /canonical Claude/)
})
