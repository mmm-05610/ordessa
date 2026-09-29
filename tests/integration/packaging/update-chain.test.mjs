// Update chain acceptance: SC-005 / PC-14 (FR-074..077).
//
// A controlled update source is stood up locally, a real signed manifest is
// published against the real built .deb, and the whole client is driven through
// its seven steps. Then the attack cases are run against the same chain.
//
// What makes this meaningful rather than a self-fulfilling mock: the manifest
// is signed with a real Ed25519 key, the deb bytes are the real built package,
// and the negative cases mutate a *validly signed* manifest so that only the
// signature covering the key metadata can reject them.
//
// Run: node tests/integration/packaging/update-chain.test.mjs

import { test, describe, before, after } from 'node:test'
import assert from 'node:assert/strict'
import { createServer } from 'node:http'
import { readFileSync, writeFileSync, existsSync, mkdirSync, rmSync, cpSync } from 'node:fs'
import path from 'node:path'
import { repoRoot, identity } from '../../../packaging/lib/identity.mjs'
import { signManifest, loadPrivateKey, loadPublicKey, verifyManifest, buildManifest } from '../../../packaging/update/manifest.mjs'
import {
  checkForUpdate, downloadAndVerify, backUpAndCheckCompatibility,
  installDeb, selfCheck, markUpdateDone, compareVersions,
} from '../../../packaging/update/client.mjs'
import { assessUpdateState, readState, writeState, createBackup, verifyBackup } from '../../../packaging/update/state.mjs'
import { sha256File } from '../../../packaging/lib/hash.mjs'

const id = identity()
const OUT = path.join(repoRoot, 'packaging/.out')
const DEB = path.join(OUT, id.pkgName + '_' + id.version + '_amd64.deb')
const KEYS = path.join(repoRoot, 'packaging/.keys')
const WORK = path.join(repoRoot, 'packaging/.test-update')

const NEW_VERSION = '9.9.9'
const NEW_BUILD = '20260928-acceptance'

let server = null
let origin = null
let sourceDir = null
let dataRoot = null
let manifest = null
let privateKey = null
let publicKeyPem = null

const ports = { installCalls: 0, cancelled: false, failNext: false }

function startServer(dir) {
  return new Promise(resolve => {
    const srv = createServer((req, res) => {
      const name = req.url.replace(/^\//, '').split('?')[0]
      const file = path.join(dir, name)
      // Path traversal guard: the source directory is the only thing served.
      if (!file.startsWith(path.resolve(dir)) || !existsSync(file)) {
        res.writeHead(404).end('not found')
        return
      }
      res.writeHead(200, { 'content-type': 'application/octet-stream' })
      res.end(readFileSync(file))
    })
    srv.listen(0, '127.0.0.1', () => resolve(srv))
  })
}

function serve(manifestObj, debBytes) {
  // Each publish gets its own directory so a tampered manifest can be served
  // without disturbing the good one.
  const dir = path.join(WORK, 'source-' + Math.random().toString(36).slice(2))
  mkdirSync(dir, { recursive: true })
  writeFileSync(path.join(dir, 'update-manifest.json'), JSON.stringify(manifestObj, null, 2))
  const debName = path.basename(manifestObj.latest.deb.url)
  writeFileSync(path.join(dir, debName), debBytes)
  return dir
}

const clientFetch = base => (url) => {
  const abs = String(url).startsWith('http') ? String(url) : base + '/' + String(url)
  return fetch(abs)
}

function seedDataRoot(root) {
  mkdirSync(path.join(root, 'secrets'), { recursive: true, mode: 0o700 })
  writeFileSync(path.join(root, 'secrets/http-token'), 'canary-token-bytes', { mode: 0o600 })
  mkdirSync(path.join(root, 'history'), { recursive: true })
  writeFileSync(path.join(root, 'history/conversations.jsonl'), '{"turn":"user: hello"}\n')
  writeFileSync(path.join(root, 'data-root-state.json'), JSON.stringify({ dataSchema: 1 }))
}

before(async () => {
  if (!existsSync(DEB)) throw new Error('deb not built: ' + DEB + '\nRun `npm run build:deb` first.')
  if (!existsSync(path.join(KEYS, 'update-private.pem'))) {
    throw new Error('no signing key. Run: node packaging/update/keygen.mjs packaging/.keys')
  }
  rmSync(WORK, { recursive: true, force: true })
  mkdirSync(WORK, { recursive: true })

  privateKey = loadPrivateKey(readFileSync(path.join(KEYS, 'update-private.pem'), 'utf8'))
  publicKeyPem = readFileSync(path.join(KEYS, 'update-pubkey'), 'utf8')

  const debBytes = readFileSync(DEB)
  manifest = buildManifest({
    version: NEW_VERSION,
    build: NEW_BUILD,
    debUrl: 'PLACEHOLDER/ordessa_acceptance.deb',
    debSize: debBytes.length,
    debSha256: sha256File(DEB),
    notes: 'acceptance',
    minDataSchema: 1,
  })
  // The URL must be inside the signed payload, so the server has to exist
  // before the manifest can be signed. Bind first, then sign, then serve.
  sourceDir = path.join(WORK, 'source-good')
  mkdirSync(sourceDir, { recursive: true })
  server = await startServer(sourceDir)
  origin = 'http://127.0.0.1:' + server.address().port

  manifest.latest.deb.url = origin + '/ordessa_acceptance.deb'
  manifest.latest.deb.signature = signManifest(manifest, privateKey)
  writeFileSync(path.join(sourceDir, 'update-manifest.json'), JSON.stringify(manifest, null, 2))
  writeFileSync(path.join(sourceDir, 'ordessa_acceptance.deb'), debBytes)

  dataRoot = path.join(WORK, 'data-root')
  mkdirSync(dataRoot, { recursive: true, mode: 0o700 })
  seedDataRoot(dataRoot)
})

after(() => {
  if (server) server.close()
  rmSync(WORK, { recursive: true, force: true })
})

// A stand-in for `pkexec dpkg -i`. It records what it was asked to do and can
// be told to behave like a cancelled prompt or a failed install.
const fakeRunner = (file, args) => {
  ports.installCalls++
  if (ports.cancelled) return Promise.resolve({ code: 126, stdout: '', stderr: 'Error executing command as another user: Authentication cancelled', cancelled: true })
  if (ports.failNext) return Promise.resolve({ code: 1, stdout: '', stderr: 'dpkg: error processing archive', cancelled: false })
  assert.equal(file, 'pkexec', 'install must go through polkit, not a direct privileged call')
  assert.deepEqual(args.slice(0, 2), ['dpkg', '-i'])
  return Promise.resolve({ code: 0, stdout: 'Setting up ordessa', stderr: '', cancelled: false })
}

describe('PC-14 happy path: check → download → verify → backup → install → self-check', () => {
  test('step 1 reports an available update from a valid signed manifest', async () => {
    const res = await checkForUpdate({
      manifestUrl: origin + '/update-manifest.json',
      publicKeyPem,
      currentVersion: id.version,
      fetchImpl: clientFetch(origin),
    })
    assert.equal(res.ok, true, res.reason)
    assert.equal(res.status, 'update-available')
    assert.equal(res.version, NEW_VERSION)
    assert.equal(res.build, NEW_BUILD)
  })

  test('the full chain completes and the data survives', async () => {
    const check = await checkForUpdate({
      manifestUrl: origin + '/update-manifest.json',
      publicKeyPem,
      currentVersion: id.version,
      fetchImpl: clientFetch(origin),
    })
    assert.equal(check.ok, true)

    const download = await downloadAndVerify({
      manifest: check.manifest,
      dataRoot,
      publicKeyPem,
      fetchImpl: clientFetch(origin),
    })
    assert.equal(download.ok, true, download.reason)
    assert.equal(readState(dataRoot).phase, 'verified')

    const backup = backUpAndCheckCompatibility({
      dataRoot,
      manifest: check.manifest,
      currentVersion: id.version,
      currentBuild: id.build,
      currentDataSchema: 1,
    })
    assert.equal(backup.ok, true, backup.reason)
    assert.equal(readState(dataRoot).phase, 'backed-up')

    // The backup must actually contain the user's history, not just a marker.
    const snap = path.join(dataRoot, backup.backupRef, 'data-snapshot/history/conversations.jsonl')
    assert.ok(existsSync(snap), 'backup does not contain the conversation history')
    assert.equal(readFileSync(snap, 'utf8'), '{"turn":"user: hello"}\n')

    const install = await installDeb({ dataRoot, debPath: download.debPath, runCommand: fakeRunner })
    assert.equal(install.ok, true, install.reason)
    assert.equal(readState(dataRoot).phase, 'installing')

    const check2 = await selfCheck({
      expectedVersion: NEW_VERSION,
      expectedBuild: NEW_BUILD,
      readInstalled: () => ({ version: NEW_VERSION, build: NEW_BUILD }),
      probeLive: () => true,
    })
    assert.equal(check2.ok, true, check2.reason)

    markUpdateDone(dataRoot)
    const state = readState(dataRoot)
    assert.equal(state.phase, 'done')
    assert.equal(state.debRef, null, 'the retained deb reference is only cleared after a successful self-check')

    // History still there after the "upgrade".
    assert.equal(readFileSync(path.join(dataRoot, 'history/conversations.jsonl'), 'utf8'), '{"turn":"user: hello"}\n')
    // Backup retained (data is never auto-deleted).
    assert.equal(verifyBackup(dataRoot, backup.backupRef).ok, true)
  })
})

describe('PC-10 negative cases: every one must be refused', () => {
  const tamper = mutate => {
    const copy = JSON.parse(JSON.stringify(manifest))
    mutate(copy)
    return copy
  }

  test('repointing the download URL while keeping the deb hash is rejected', async () => {
    // The classic downgrade/redirect attack: the deb hash still verifies, so
    // only a signature that covers `deb.url` can catch this.
    const bad = tamper(m => { m.latest.deb.url = 'https://attacker.invalid/evil.deb' })
    assert.equal(verifyManifest(bad, loadPublicKey(publicKeyPem)).ok, false)

    const dir = serve(bad, Buffer.from('not the real deb'))
    const srv = await startServer(dir)
    const base = 'http://127.0.0.1:' + srv.address().port
    const res = await checkForUpdate({
      manifestUrl: base + '/update-manifest.json',
      publicKeyPem,
      currentVersion: id.version,
      fetchImpl: clientFetch(base),
    })
    srv.close()
    assert.equal(res.ok, false)
    assert.equal(res.status, 'signature-invalid')
    assert.match(res.reason, /UPDATE_SIGNATURE/)
  })

  test('raising minDataSchema while keeping the deb hash is rejected', async () => {
    const bad = tamper(m => { m.latest.minDataSchema = 99 })
    assert.equal(verifyManifest(bad, loadPublicKey(publicKeyPem)).ok, false)
  })

  test('every single signed field is covered (exhaustive)', () => {
    const mutations = {
      schemaVersion: m => { m.schemaVersion = 2 },
      channel: m => { m.channel = 'beta' },
      version: m => { m.latest.version = '0.0.1' },
      build: m => { m.latest.build = 'forged' },
      'deb.url': m => { m.latest.deb.url = 'https://attacker.invalid/evil.deb' },
      'deb.size': m => { m.latest.deb.size = 1 },
      'deb.sha256': m => { m.latest.deb.sha256 = 'f'.repeat(64) },
      minDataSchema: m => { m.latest.minDataSchema = 99 },
    }
    for (const [field, mutate] of Object.entries(mutations)) {
      const bad = tamper(mutate)
      assert.equal(verifyManifest(bad, loadPublicKey(publicKeyPem)).ok, false,
        'tampering with ' + field + ' must invalidate the signature')
    }
    // And the untouched one still passes, so the test is not vacuous.
    assert.equal(verifyManifest(tamper(() => {}), loadPublicKey(publicKeyPem)).ok, true)
  })

  test('tampered deb bytes are rejected on hash, and the download is discarded', async () => {
    const dir = serve(manifest, Buffer.from('corrupted deb bytes'))
    const srv = await startServer(dir)
    const base = 'http://127.0.0.1:' + srv.address().port
    // Re-sign so the signature is valid: the ONLY thing that can catch this is
    // the sha256 comparison.
    const copy = JSON.parse(JSON.stringify(manifest))
    copy.latest.deb.url = base + '/' + path.basename(manifest.latest.deb.url)
    copy.latest.deb.signature = signManifest(copy, privateKey)
    writeFileSync(path.join(dir, 'update-manifest.json'), JSON.stringify(copy, null, 2))

    const root = path.join(WORK, 'tamper-root')
    mkdirSync(root, { recursive: true, mode: 0o700 })
    seedDataRoot(root)

    const res = await downloadAndVerify({
      manifest: copy,
      dataRoot: root,
      publicKeyPem,
      fetchImpl: clientFetch(base),
    })
    srv.close()
    assert.equal(res.ok, false)
    assert.equal(res.status, 'hash-mismatch')
    assert.equal(existsSync(path.join(root, 'backups/pending/ordessa_acceptance.deb')), false,
      'the rejected download must be deleted, not left lying around')
  })

  test('an unreachable source is an error, never "up to date" (FR-075)', async () => {
    const res = await checkForUpdate({
      // Port 1 is reserved and refuses connections.
      manifestUrl: 'http://127.0.0.1:1/update-manifest.json',
      publicKeyPem,
      currentVersion: id.version,
      timeoutMs: 2000,
    })
    assert.equal(res.ok, false)
    assert.equal(res.status, 'source-unreachable')
    assert.notEqual(res.status, 'up-to-date')
    assert.match(res.reason, /could not reach the update source/)
  })

  test('a 404 from the source is an error, not "up to date"', async () => {
    const res = await checkForUpdate({
      manifestUrl: origin + '/does-not-exist.json',
      publicKeyPem,
      currentVersion: id.version,
    })
    assert.equal(res.ok, false)
    assert.equal(res.status, 'source-unreachable')
    assert.match(res.reason, /UPDATE_SOURCE_HTTP_404/)
  })

  test('a too-new minDataSchema aborts and keeps the backup (FR-077)', () => {
    const root = path.join(WORK, 'incompat-root')
    rmSync(root, { recursive: true, force: true })
    mkdirSync(root, { recursive: true, mode: 0o700 })
    seedDataRoot(root)
    const bad = JSON.parse(JSON.stringify(manifest))
    bad.latest.minDataSchema = 99
    bad.latest.deb.signature = signManifest(bad, privateKey)

    const res = backUpAndCheckCompatibility({
      dataRoot: root,
      manifest: bad,
      currentVersion: id.version,
      currentBuild: id.build,
      currentDataSchema: 1,
    })
    assert.equal(res.ok, false)
    assert.equal(res.status, 'incompatible')
    // The user's data is untouched and no destructive backup was taken.
    assert.equal(readFileSync(path.join(root, 'history/conversations.jsonl'), 'utf8'), '{"turn":"user: hello"}\n')
    assert.equal(readState(root).phase, 'idle')
  })

  test('cancelling the polkit prompt aborts with the old version intact', async () => {
    const root = path.join(WORK, 'cancel-root')
    rmSync(root, { recursive: true, force: true })
    mkdirSync(root, { recursive: true, mode: 0o700 })
    seedDataRoot(root)
    ports.cancelled = true
    try {
      const res = await installDeb({ dataRoot: root, debPath: DEB, runCommand: fakeRunner })
      assert.equal(res.ok, false)
      assert.equal(res.status, 'cancelled')
      assert.equal(readState(root).phase, 'failed')
    } finally {
      ports.cancelled = false
    }
  })

  test('a failed install is recorded, and the backup is still there', async () => {
    const root = path.join(WORK, 'failinstall-root')
    rmSync(root, { recursive: true, force: true })
    mkdirSync(root, { recursive: true, mode: 0o700 })
    seedDataRoot(root)
    const backup = createBackup(root, { version: '0.0.9', build: 'old', dataSchema: 1 })
    ports.failNext = true
    try {
      const res = await installDeb({ dataRoot: root, debPath: DEB, runCommand: fakeRunner })
      assert.equal(res.ok, false)
      assert.equal(res.status, 'install-failed')
      assert.equal(readState(root).phase, 'failed')
    } finally {
      ports.failNext = false
    }
    // FR-076/077: a failed install must not cost the user their data.
    assert.equal(verifyBackup(root, backup.backupRef).ok, true)
  })
})

describe('PC-11 interruption is detectable, repairable, and loses no data', () => {
  for (const phase of ['downloading', 'verified', 'backed-up', 'installing', 'restarting']) {
    test('an update interrupted during "' + phase + '" is detected on next start', () => {
      const root = path.join(WORK, 'interrupt-' + phase)
      rmSync(root, { recursive: true, force: true })
      mkdirSync(root, { recursive: true, mode: 0o700 })
      seedDataRoot(root)
      const backup = createBackup(root, { version: '0.0.9', build: 'old', dataSchema: 1 })
      writeState(root, {
        phase,
        from: { version: '0.0.9', build: 'old' },
        to: { version: NEW_VERSION, build: NEW_BUILD },
        backupRef: backup.backupRef,
        debRef: 'backups/pending/ordessa_old.deb',
      })

      const report = assessUpdateState(root, { currentVersion: '0.1.0', currentBuild: 'x' })
      assert.equal(report.incomplete, true, 'phase ' + phase + ' must be reported as an incomplete update')
      assert.equal(report.severity, 'blocked')
      assert.match(report.reason, /UPDATE_INCOMPLETE/)
      assert.equal(report.backupRef, backup.backupRef, 'the backup path must be surfaced to the user')
      // Data first, per C-09 §C4.
      assert.equal(report.dataRootSafe.ok, true)
      // A concrete repair action, not just a message.
      assert.ok(report.recovery.some(a => a.id === 'configure-dpkg'))
    })
  }

  test('a completed update is not reported as incomplete', () => {
    const root = path.join(WORK, 'done-root')
    rmSync(root, { recursive: true, force: true })
    mkdirSync(root, { recursive: true, mode: 0o700 })
    seedDataRoot(root)
    markUpdateDone(root)
    const report = assessUpdateState(root, { currentVersion: id.version, currentBuild: id.build })
    assert.equal(report.incomplete, false)
    assert.equal(report.severity, 'ok')
  })

  test('a corrupt state file is surfaced, not silently treated as healthy', () => {
    const root = path.join(WORK, 'corrupt-root')
    rmSync(root, { recursive: true, force: true })
    mkdirSync(path.join(root, 'backups'), { recursive: true, mode: 0o700 })
    writeFileSync(path.join(root, 'backups/update-state.json'), '{ this is not json')
    const report = assessUpdateState(root, {})
    assert.equal(report.severity, 'warning')
    assert.match(report.reason, /UPDATE_STATE_UNREADABLE/)
  })

  test('recovery never deletes the backup it points at', () => {
    const root = path.join(WORK, 'retain-root')
    rmSync(root, { recursive: true, force: true })
    mkdirSync(root, { recursive: true, mode: 0o700 })
    seedDataRoot(root)
    const backup = createBackup(root, { version: '0.0.9', build: 'old', dataSchema: 1 })
    writeState(root, { phase: 'installing', backupRef: backup.backupRef, debRef: 'backups/pending/x.deb' })
    // Run the gate repeatedly, as a restarting app would.
    for (let i = 0; i < 3; i++) assessUpdateState(root, { currentVersion: '0.1.0' })
    assert.equal(verifyBackup(root, backup.backupRef).ok, true, 'the backup must survive recovery inspection')
    assert.equal(readFileSync(path.join(root, backup.backupRef, 'data-snapshot/secrets/http-token'), 'utf8'), 'canary-token-bytes')
  })
})

describe('version comparison', () => {
  test('orders versions numerically, with pre-releases below releases', () => {
    assert.equal(compareVersions('0.2.0', '0.1.9') > 0, true)
    assert.equal(compareVersions('0.1.0', '0.1.0'), 0)
    assert.equal(compareVersions('0.1.0-rc1', '0.1.0') < 0, true)
    assert.equal(compareVersions('1.0.0', '0.99.99') > 0, true)
  })
})
