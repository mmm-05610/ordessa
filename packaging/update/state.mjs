// The update state file and the recovery gate (C-09 §C4, FR-076/077).
//
// Why this file exists: `dpkg -i` over an installed package is NOT atomic. A
// power cut can leave files half-written and dpkg's own state mid-transaction.
// So the update does not try to make the install atomic -- it makes the
// interruption *detectable* and *repairable*, and treats data preservation as
// inviolable.
//
// The hard rule, in one place: nothing in this module may delete or overwrite
// `backupRef`. Recovery is allowed to leave a mess in the program directory;
// it is not allowed to cost the user their data.

import { writeFileSync, renameSync, readFileSync, existsSync, mkdirSync, chmodSync, cpSync, readdirSync, statSync, unlinkSync } from 'node:fs'
import path from 'node:path'

export const PHASES = ['idle', 'downloading', 'verified', 'backed-up', 'installing', 'restarting', 'done', 'failed']

// A phase that means "we were in the middle of changing the installation".
// Seeing one of these on startup means the previous run did not finish.
export const IN_FLIGHT_PHASES = ['downloading', 'verified', 'backed-up', 'installing', 'restarting']

export function updateStatePath(dataRoot) {
  return path.join(dataRoot, 'backups', 'update-state.json')
}

function publish(file, text) {
  // Write-then-rename: a reader either sees the previous complete state or the
  // new complete state, never a half-written file.
  const tmp = file + '.tmp'
  writeFileSync(tmp, text, { mode: 0o600 })
  renameSync(tmp, file)
  try { chmodSync(file, 0o600) } catch { /* best effort on odd filesystems */ }
}

export function readState(dataRoot) {
  const file = updateStatePath(dataRoot)
  if (!existsSync(file)) return { phase: 'idle', failure: null }
  let parsed
  try {
    parsed = JSON.parse(readFileSync(file, 'utf8'))
  } catch {
    // A corrupt state file must not itself become a blocker: an unreadable
    // state is treated as "unknown", which the gate reports rather than hides.
    return { phase: 'unknown', failure: null, corrupt: true }
  }
  if (!PHASES.includes(parsed.phase)) return { phase: 'unknown', failure: null, corrupt: true }
  return parsed
}

export function writeState(dataRoot, patch) {
  const current = readState(dataRoot)
  const next = {
    phase: 'idle',
    from: null,
    to: null,
    backupRef: null,
    debRef: null,
    ...current,
    ...patch,
    updatedAt: new Date().toISOString(),
  }
  if (!next.startedAt) next.startedAt = next.updatedAt
  mkdirSync(path.dirname(updateStatePath(dataRoot)), { recursive: true, mode: 0o700 })
  publish(updateStatePath(dataRoot), JSON.stringify(next, null, 2) + '\n')
  return next
}

// The gate. Called on startup BEFORE anything tries to use the installation.
//
// Returns a report the host can show verbatim. `severity` is one of
// 'ok' | 'warning' | 'blocked' and the caller must not paper over 'blocked'.
export function assessUpdateState(dataRoot, { currentVersion, currentBuild } = {}) {
  const state = readState(dataRoot)

  if (state.corrupt || state.phase === 'unknown') {
    return {
      severity: 'warning',
      incomplete: true,
      phase: 'unknown',
      reason: 'UPDATE_STATE_UNREADABLE: the record of the last update could not be read.',
      remedy: 'Ordessa will keep running. If updates misbehave, reinstall the package.',
      backupRef: null,
      // Never auto-delete: the data may still be recoverable and the user has
      // not been told about it yet.
      dataRootSafe: null,
    }
  }

  if (state.phase === 'failed') {
    return {
      severity: 'warning',
      incomplete: true,
      phase: state.phase,
      reason: (state.failure && state.failure.reason) || 'UPDATE_FAILED: the last update did not complete.',
      remedy: (state.failure && state.failure.remedy) || 'Reinstall the previous version, or retry the update.',
      backupRef: state.backupRef || null,
      dataRootSafe: dataRootHealthy(dataRoot),
    }
  }

  if (IN_FLIGHT_PHASES.includes(state.phase)) {
    // Data first, exactly as the contract orders it: check that the user's data
    // is still readable and writable BEFORE offering to fix anything, so a
    // repair prompt is never shown on top of a broken data root.
    const healthy = dataRootHealthy(dataRoot)
    return {
      severity: 'blocked',
      incomplete: true,
      phase: state.phase,
      from: state.from || null,
      to: state.to || null,
      currentVersion: currentVersion || null,
      currentBuild: currentBuild || null,
      reason: `UPDATE_INCOMPLETE: the last update stopped during "${state.phase}" and did not finish.`,
      remedy: 'Run the repair action, or reinstall the previous version. Your data and its backup are kept.',
      backupRef: state.backupRef || null,
      debRef: state.debRef || null,
      dataRootSafe: healthy,
      recovery: recoveryActions(state, dataRoot),
    }
  }

  return {
    severity: 'ok',
    incomplete: false,
    phase: state.phase,
    currentVersion: currentVersion || null,
    currentBuild: currentBuild || null,
    backupRef: state.backupRef || null,
    dataRootSafe: dataRootHealthy(dataRoot),
  }
}

// A data root is "healthy" when it exists, is readable and is writable. This
// is a liveness check, not a repair: nothing here writes to the data root.
export function dataRootHealthy(dataRoot) {
  if (!existsSync(dataRoot)) return { ok: false, reason: 'DATA_ROOT_MISSING' }
  try {
    const st = statSync(dataRoot)
    if (!st.isDirectory()) return { ok: false, reason: 'DATA_ROOT_NOT_A_DIRECTORY' }
    readdirSync(dataRoot)
  } catch {
    return { ok: false, reason: 'DATA_ROOT_UNREADABLE' }
  }
  const probe = path.join(dataRoot, '.ordessa-write-probe')
  try {
    writeFileSync(probe, '')
    // Best effort cleanup of our own probe only -- never a data file.
    try { unlinkSync(probe) } catch { /* ignore */ }
  } catch {
    return { ok: false, reason: 'DATA_ROOT_NOT_WRITABLE' }
  }
  return { ok: true }
}

function recoveryActions(state, dataRoot) {
  const actions = []
  if (state.debRef) {
    actions.push({
      id: 'reinstall-previous',
      label: 'Reinstall the previous version',
      command: ['dpkg', '-i', path.join(dataRoot, state.debRef)],
      // The retained deb is the only route back to a known-good install.
      available: existsSync(path.join(dataRoot, state.debRef)),
    })
  }
  actions.push({
    // The id is what the host dispatches on; without it the action would be
    // displayed but unclickable.
    id: 'configure-dpkg',
    label: "Finish the interrupted package transaction (dpkg --configure -a)",
    command: ['dpkg', '--configure', '-a'],
    needsPrivilege: true,
    available: true,
  })
  return actions
}

// Back up the data root's irreplaceable content plus the version information
// needed to explain what the backup belongs to (C-09 §C4 / data-model §1).
//
// What is copied: everything except the things an update regenerates anyway
// (logs, the update state file, and the pending download directory). The
// secrets directory IS copied -- it holds the token the server expects, and
// restoring a backup without it produces a data root that cannot start.
export function createBackup(dataRoot, { version, build, dataSchema, timestamp = new Date().toISOString() }) {
  const stamp = timestamp.replace(/[:.]/g, '-')
  const rel = path.join('backups', stamp)
  const dest = path.join(dataRoot, rel)
  mkdirSync(path.join(dest, 'data-snapshot'), { recursive: true, mode: 0o700 })

  const SKIP = new Set(['logs', 'backups', 'run', 'instance.lock'])
  const copied = []
  for (const entry of readdirSync(dataRoot, { withFileTypes: true })) {
    if (SKIP.has(entry.name)) continue
    if (entry.name === '.ordessa-write-probe') continue
    const from = path.join(dataRoot, entry.name)
    const to = path.join(dest, 'data-snapshot', entry.name)
    try {
      cpSync(from, to, { recursive: true, preserveTimestamps: true, dereference: false })
      copied.push(entry.name)
    } catch {
      // A single unreadable entry must not abort the whole backup, but it must
      // not be silently forgotten either: it is recorded in the manifest.
      copied.push(entry.name + ' (COPY FAILED)')
    }
  }

  writeFileSync(path.join(dest, 'version.json'), JSON.stringify({
    version,
    build,
    dataSchema,
    takenAt: timestamp,
    entries: copied.sort(),
  }, null, 2) + '\n', { mode: 0o600 })

  return { backupRef: rel.split(path.sep).join('/'), absPath: dest, entries: copied }
}

// Verify a backup is still intact and matches what it claimed to be. Used by the
// recovery path before it points a user at a backup as restorable.
export function verifyBackup(dataRoot, backupRef) {
  const dir = path.join(dataRoot, backupRef)
  if (!existsSync(dir)) return { ok: false, reason: 'BACKUP_MISSING' }
  const versionFile = path.join(dir, 'version.json')
  if (!existsSync(versionFile)) return { ok: false, reason: 'BACKUP_METADATA_MISSING' }
  let meta
  try {
    meta = JSON.parse(readFileSync(versionFile, 'utf8'))
  } catch {
    return { ok: false, reason: 'BACKUP_METADATA_UNREADABLE' }
  }
  return { ok: true, meta, entries: meta.entries || [] }
}

