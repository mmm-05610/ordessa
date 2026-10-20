import { test } from 'node:test'
import assert from 'node:assert/strict'
import { mkdtempSync, writeFileSync, rmSync, existsSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { spawnSync } from 'node:child_process'
import { fileURLToPath, pathToFileURL } from 'node:url'

const moduleURL = pathToFileURL(fileURLToPath(new URL('../../apps/desktop/packaging/build-deb.mjs', import.meta.url))).href
function check(cache, env) {
  return spawnSync(process.execPath, ['--input-type=module', '-e', `process.argv = [process.execPath, "controlled", "--cache", ${JSON.stringify(cache)}]; const {buildBridge} = await import(${JSON.stringify(moduleURL)}); buildBridge()`, '--', '--cache', cache], {
    env: { PATH: '/usr/bin:/bin', HOME: cache, TMPDIR: cache, ...env }, encoding: 'utf8',
  })
}

test('corrupt cached ACP cannot pass the actual Desktop artifact gate', () => {
  const cache = mkdtempSync(path.join(tmpdir(), 'ordessa-bridge-corrupt-'))
  try {
    writeFileSync(path.join(cache, 'acp-adapter'), 'corrupt controlled artifact')
    const result = check(cache)
    assert.notEqual(result.status, 0)
    assert.match(result.stderr, /ACP bridge sha256 .* differs from required/)
    assert.equal(existsSync(path.join(cache, 'build-result.json')), false)
  } finally { rmSync(cache, { recursive: true, force: true }) }
})

test('fresh Desktop ACP rebuild rejects missing pinned toolchain context', () => {
  const cache = mkdtempSync(path.join(tmpdir(), 'ordessa-bridge-context-'))
  try {
    const result = check(cache)
    assert.notEqual(result.status, 0)
    assert.match(result.stderr, /GOROOT must point at the pinned Go 1.24.13/)
    assert.equal(existsSync(path.join(cache, 'acp-adapter')), false)
  } finally { rmSync(cache, { recursive: true, force: true }) }
})
