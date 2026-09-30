import test from 'node:test'
import assert from 'node:assert/strict'
import { mkdtempSync, mkdirSync, existsSync, symlinkSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { spawnSync } from 'node:child_process'

test('startup refuses missing, shared, relative and symlinked instance directories before imports', () => {
  const root = mkdtempSync(path.join(tmpdir(), 'ordessa-pi-isolation-gate-'))
  const missing = path.join(root, 'absent')
  const shared = path.join(root, 'shared'); mkdirSync(shared, { mode: 0o755 })
  const privateDirectory = path.join(root, 'private'); mkdirSync(privateDirectory, { mode: 0o700 })
  const link = path.join(root, 'link'); symlinkSync(privateDirectory, link)
  for (const value of [undefined, 'relative', missing, shared, link, path.join(root, 'private') + '/']) {
    const env = { PATH: process.env.PATH }
    if (value !== undefined) env.ORDESSA_PI_INSTANCE_DIR = value
    const result = spawnSync(process.execPath, [path.join(import.meta.dirname, 'entry.mjs')], { env, encoding: 'utf8' })
    assert.equal(result.status, 1)
    assert.equal(result.stdout, '')
    assert.match(result.stderr, /Pi profile bridge startup refused/)
    assert.doesNotMatch(result.stderr, /Cannot find module/)
  }
  assert.equal(existsSync(missing), false, 'refused startup must not allocate config directories')
})
