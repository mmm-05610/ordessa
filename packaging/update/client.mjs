// The update client: the seven-step flow of C-09 §C2, in order, aborting on
// the first failure and leaving the old version in place.
//
// This is the engine P-C owns and P-A calls. P-A owns the settings-page UI and
// the restart; the two meet at this module's return values. Every step reports
// a typed reason + remedy, and no step may leave the installation in a state
// the next run cannot recognise -- that is what `update-state.json` is for.
//
// Deliberate design points:
//  * Step 1 never downloads. The user is asked first (C-09 §C2 step 1), so an
//    available update does not start moving bytes behind their back.
//  * An unreachable source is an ERROR, not "you are up to date". Treating a
//    network failure as success is the most misleading thing an updater can do
//    (FR-075).
//  * The install step is the only privileged step, and it goes through polkit.
//  * Nothing here deletes a backup. Ever.

import { existsSync, mkdirSync, readFileSync, rmSync, createWriteStream } from 'node:fs'
import { spawn } from 'node:child_process'
import { pipeline } from 'node:stream/promises'
import { Readable } from 'node:stream'
import path from 'node:path'
import { sha256File } from '../lib/hash.mjs'
import { verifyManifest, loadPublicKey } from './manifest.mjs'
import { writeState, createBackup, readState, PHASES } from './state.mjs'

const DEFAULT_TIMEOUT_MS = 15000

// -- step 1: check -----------------------------------------------------------

export async function checkForUpdate({ manifestUrl, publicKeyPem, currentVersion, timeoutMs = DEFAULT_TIMEOUT_MS, fetchImpl = fetch }) {
  let response
  try {
    response = await withTimeout(fetchImpl(manifestUrl), timeoutMs)
  } catch (err) {
    // FR-075. Note what this does NOT say: it never says "already up to date".
    return {
      ok: false,
      status: 'source-unreachable',
      reason: 'UPDATE_SOURCE_UNREACHABLE: could not reach the update source.',
      remedy: 'Check your network connection and try again. Your current version is unchanged.',
      cause: String((err && err.message) || err),
    }
  }
  if (!response.ok) {
    return {
      ok: false,
      status: 'source-unreachable',
      reason: 'UPDATE_SOURCE_HTTP_' + response.status + ': the update source did not return a manifest.',
      remedy: 'The update service may be unavailable. Your current version is unchanged; try again later.',
    }
  }

  let manifest
  try {
    manifest = await response.json()
  } catch {
    return {
      ok: false,
      status: 'source-unreachable',
      reason: 'UPDATE_SOURCE_MALFORMED: the update manifest could not be read.',
      remedy: 'The update service returned something unreadable. Your current version is unchanged.',
    }
  }

  const verdict = verifyManifest(manifest, loadPublicKey(publicKeyPem))
  if (!verdict.ok) {
    // Nothing has been downloaded or installed, so the old version is intact.
    return { ok: false, status: 'signature-invalid', reason: verdict.reason, remedy: verdict.remedy }
  }

  const latest = manifest.latest
  return {
    ok: true,
    status: compareVersions(latest.version, currentVersion) > 0 ? 'update-available' : 'up-to-date',
    manifest,
    version: latest.version,
    build: latest.build,
    notes: latest.notes || '',
    minDataSchema: latest.minDataSchema,
    size: latest.deb.size,
  }
}

// Numeric-segment comparison. A pre-release suffix sorts below its release, so
// "0.2.0-rc1" is not offered to someone already on "0.2.0".
export function compareVersions(a, b) {
  const parse = v => {
    const [core, pre] = String(v).split('-')
    const nums = core.split('.').map(n => parseInt(n, 10) || 0)
    while (nums.length < 3) nums.push(0)
    return { nums, pre: pre || null }
  }
  const pa = parse(a)
  const pb = parse(b)
  for (let i = 0; i < 3; i++) {
    if (pa.nums[i] !== pb.nums[i]) return pa.nums[i] < pb.nums[i] ? -1 : 1
  }
  if (pa.pre === pb.pre) return 0
  if (pa.pre === null) return 1
  if (pb.pre === null) return -1
  return pa.pre < pb.pre ? -1 : 1
}

// -- step 2: download + verify ----------------------------------------------

export async function downloadAndVerify({ manifest, dataRoot, publicKeyPem, fetchImpl = fetch, onProgress }) {
  const fileName = path.basename(new URL(manifest.latest.deb.url).pathname)
  const dest = path.join(dataRoot, 'backups', 'pending', fileName)
  mkdirSync(path.dirname(dest), { recursive: true, mode: 0o700 })

  // Re-checked here, not only at check time: the manifest reaching this
  // function is whatever the caller passed, and this is the step where bytes
  // actually arrive.
  const verdict = verifyManifest(manifest, loadPublicKey(publicKeyPem))
  if (!verdict.ok) return { ok: false, reason: verdict.reason, remedy: verdict.remedy }

  const debRef = path.relative(dataRoot, dest).split(path.sep).join('/')
  writeState(dataRoot, {
    phase: 'downloading',
    to: { version: manifest.latest.version, build: manifest.latest.build },
    debRef,
  })

  let response
  try {
    response = await fetchImpl(manifest.latest.deb.url)
  } catch (err) {
    return {
      ok: false,
      reason: 'UPDATE_DOWNLOAD_FAILED: the update package could not be downloaded.',
      remedy: 'Your current version is unchanged. Check your connection and try again.',
      cause: String((err && err.message) || err),
    }
  }
  if (!response.ok) {
    return {
      ok: false,
      reason: 'UPDATE_DOWNLOAD_HTTP_' + response.status + ': the update package could not be downloaded.',
      remedy: 'Your current version is unchanged. Try again later.',
    }
  }

  await pipeline(Readable.fromWeb(response.body), createWriteStream(dest))
  if (onProgress) onProgress(dest)

  const actual = sha256File(dest)
  if (actual !== manifest.latest.deb.sha256) {
    // The bytes are not what was signed for. The download is discarded and the
    // installed version is never touched.
    rmSync(dest, { force: true })
    return {
      ok: false,
      status: 'hash-mismatch',
      reason: 'UPDATE_HASH_MISMATCH: the downloaded package does not match its signed hash.',
      remedy: 'The download was discarded and nothing was installed. Try again; if it repeats, contact your administrator.',
      expected: manifest.latest.deb.sha256,
      actual,
    }
  }

  writeState(dataRoot, { phase: 'verified' })
  return { ok: true, debPath: dest, debRef }
}

// -- step 3 + 4: backup and compatibility ------------------------------------

export function backUpAndCheckCompatibility({ dataRoot, manifest, currentVersion, currentBuild, currentDataSchema }) {
  const required = manifest.latest.minDataSchema
  if (typeof currentDataSchema === 'number' && required > currentDataSchema) {
    // Abort before installing anything and keep every existing backup. The
    // message is plain language: "data format 3 vs 2" helps nobody on its own.
    return {
      ok: false,
      status: 'incompatible',
      reason: 'UPDATE_DATA_INCOMPATIBLE: this update needs data format ' + required +
        ', but your data is format ' + currentDataSchema + '.',
      remedy: 'Your data and its backups are untouched. Install a version compatible with your data, or ask your administrator for help.',
      required,
      current: currentDataSchema,
    }
  }

  const backup = createBackup(dataRoot, {
    version: currentVersion,
    build: currentBuild,
    dataSchema: currentDataSchema,
  })
  writeState(dataRoot, {
    phase: 'backed-up',
    from: { version: currentVersion, build: currentBuild },
    backupRef: backup.backupRef,
  })
  return { ok: true, backupRef: backup.backupRef, backupPath: backup.absPath, entries: backup.entries }
}

// -- step 5: install (the only privileged step) ------------------------------

// polkit raises the prompt; if the user cancels, this reports `cancelled` and
// the old version is still fully installed.
export async function installDeb({ dataRoot, debPath, runCommand = defaultRun, needsPrivilege = true }) {
  writeState(dataRoot, { phase: 'installing' })
  const args = ['-i', debPath]
  // `defaultRun` is promise-based (dpkg output is streamed), so it is awaited
  // rather than inspected synchronously.
  const result = await runCommand(
    needsPrivilege ? 'pkexec' : 'dpkg',
    needsPrivilege ? ['dpkg'].concat(args) : args,
    { timeoutMs: 10 * 60 * 1000 },
  )

  if (result.cancelled) {
    // C-09 §C3: abort, old version intact, state explicit.
    const failure = {
      reason: 'UPDATE_PERMISSION_DENIED: the update was not authorised.',
      remedy: 'Nothing was changed. To install the update, approve the authentication prompt when it appears.',
    }
    writeState(dataRoot, { phase: 'failed', failure })
    return Object.assign({ ok: false, status: 'cancelled' }, failure)
  }

  if (result.code !== 0) {
    // Deliberately no blind rollback: dpkg may have left the system mid-way,
    // and rolling back on top of a half-applied package makes things worse.
    // The state file now says failed, which is exactly what the startup gate
    // looks for, and the backup is untouched.
    const failure = {
      reason: 'UPDATE_INSTALL_FAILED: the package installer exited with code ' + result.code + '.',
      remedy: 'Run "sudo dpkg --configure -a" to finish the interrupted installation, or reinstall the previous version. Your data and its backup are kept.',
    }
    writeState(dataRoot, { phase: 'failed', failure })
    return Object.assign({ ok: false, status: 'install-failed', exitCode: result.code, stderr: result.stderr }, failure)
  }
  return { ok: true }
}

// -- step 7: self-check ------------------------------------------------------

// Success is declared only after the new install proves itself. A version that
// starts but is not the one we installed is still a failed update.
export async function selfCheck({ expectedVersion, expectedBuild, readInstalled, probeLive, timeoutMs = 20000 }) {
  const installed = readInstalled()
  if (!installed || installed.version !== expectedVersion || installed.build !== expectedBuild) {
    return {
      ok: false,
      reason: 'UPDATE_SELFCHECK_VERSION_MISMATCH: the installed version is not the version that was just installed.',
      remedy: 'Reinstall the previous version using the kept package. Your data and its backup are untouched.',
      installed,
      expected: { version: expectedVersion, build: expectedBuild },
    }
  }
  let live
  try {
    live = await withTimeout(Promise.resolve(probeLive()), timeoutMs)
  } catch (err) {
    return {
      ok: false,
      reason: 'UPDATE_SELFCHECK_NOT_READY: the new version did not become ready in time.',
      remedy: 'Reinstall the previous version using the kept package. Your data and its backup are untouched.',
      cause: String((err && err.message) || err),
    }
  }
  if (!live) {
    return {
      ok: false,
      reason: 'UPDATE_SELFCHECK_NOT_READY: the new version did not report itself ready.',
      remedy: 'Reinstall the previous version using the kept package. Your data and its backup are untouched.',
    }
  }
  return { ok: true, installed, live }
}

// Called only after selfCheck passes. The deb reference is cleared here and
// only here: while an update is unresolved the retained deb is the route back.
export function markUpdateDone(dataRoot) {
  const state = readState(dataRoot)
  return writeState(dataRoot, { phase: 'done', debRef: null, failure: null, backupRef: state.backupRef })
}

export function markUpdateFailed(dataRoot, failure) {
  return writeState(dataRoot, { phase: 'failed', failure })
}

// -- helpers -----------------------------------------------------------------

// The data root's schema version is reported by the host; when it is absent we
// return null and the compatibility check is skipped rather than guessed.
export function currentDataSchema(dataRoot) {
  const file = path.join(dataRoot, 'data-root-state.json')
  if (!existsSync(file)) return null
  try {
    const parsed = JSON.parse(readFileSync(file, 'utf8'))
    return typeof parsed.dataSchema === 'number' ? parsed.dataSchema : null
  } catch {
    return null
  }
}

function withTimeout(promise, ms) {
  return Promise.race([
    promise,
    new Promise((_, reject) => setTimeout(() => reject(new Error('timeout after ' + ms + 'ms')), ms)),
  ])
}

export function defaultRun(file, args, { timeoutMs } = {}) {
  return new Promise(resolve => {
    const child = spawn(file, args, { stdio: ['ignore', 'pipe', 'pipe'] })
    let stdout = ''
    let stderr = ''
    child.stdout.on('data', c => { stdout += c })
    child.stderr.on('data', c => { stderr += c })
    const timer = setTimeout(() => { child.kill('SIGKILL') }, timeoutMs || 600000)
    child.on('close', code => {
      clearTimeout(timer)
      // polkit reports a dismissed/cancelled prompt through stderr, not a
      // distinctive exit code -- exit 126 is also used for other auth failures.
      const cancelled = /authentication.*(cancell?ed|failed)|dismissed|cancell?ed by user|not authorized/i.test(stderr)
      resolve({ code, stdout, stderr, cancelled })
    })
    child.on('error', err => {
      clearTimeout(timer)
      resolve({ code: -1, stdout, stderr: String(err.message), cancelled: false })
    })
  })
}

export { PHASES, writeState, readState, createBackup }
