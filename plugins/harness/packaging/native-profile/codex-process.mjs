// Per-adapter child ownership only. Neither an ACP unsubscribe nor ChildProcess
// .killed proves native exit; replacement must wait for the OS exit event.
//
// The managed process is the verified native Codex binary itself. The upstream
// Node launcher (`@openai/codex/bin/codex.js`) spawns that binary with
// `stdio: "inherit"` and forwards only SIGINT/SIGTERM/SIGHUP, so a launcher
// exit is never accepted as native exit: a SIGKILLed launcher orphans a live
// native descendant. Resolution, platform selection and the owned process set
// therefore live here, and stay Harness-internal.
import { spawn as nodeSpawn } from 'node:child_process'
import {
  closeSync, fstatSync, lstatSync, openSync, readFileSync, readSync, readdirSync, realpathSync,
} from 'node:fs'
import { createRequire } from 'node:module'
import path from 'node:path'

const exited = child => child.exitCode !== null || child.signalCode !== null
const sleep = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds))
const defaultSignal = (pid, signal) => { process.kill(pid, signal) }

// Mirrors the pinned launcher's platform table so a non-target platform or an
// absent platform package is an explicit refusal, never a silent fallback to a
// global `codex` on PATH or to an unverified launcher.
const CODEX_TARGETS = {
  'x86_64-unknown-linux-musl': '@openai/codex-linux-x64',
  'aarch64-unknown-linux-musl': '@openai/codex-linux-arm64',
  'x86_64-apple-darwin': '@openai/codex-darwin-x64',
  'aarch64-apple-darwin': '@openai/codex-darwin-arm64',
  'x86_64-pc-windows-msvc': '@openai/codex-win32-x64',
  'aarch64-pc-windows-msvc': '@openai/codex-win32-arm64',
}
const CODEX_TRIPLES = {
  'linux:x64': 'x86_64-unknown-linux-musl',
  'android:x64': 'x86_64-unknown-linux-musl',
  'linux:arm64': 'aarch64-unknown-linux-musl',
  'android:arm64': 'aarch64-unknown-linux-musl',
  'darwin:x64': 'x86_64-apple-darwin',
  'darwin:arm64': 'aarch64-apple-darwin',
  'win32:x64': 'x86_64-pc-windows-msvc',
  'win32:arm64': 'aarch64-pc-windows-msvc',
}
const defaultResolvePackage = createRequire(import.meta.url).resolve

export function nativeCodexTarget({ platform = process.platform, arch = process.arch } = {},
  resolvePackage = null) {
  const triple = CODEX_TRIPLES[`${platform}:${arch}`]
  const platformPackage = triple ? CODEX_TARGETS[triple] : null
  if (!triple || !platformPackage)
    throw new Error(`${platform}/${arch} is not a supported Codex platform`)
  // A supported triple with no resolvable platform package is still a refusal.
  if (resolvePackage) {
    try { resolvePackage(platformPackage + '/package.json') }
    catch { throw new Error(`Codex native platform package is absent: ${platformPackage}`) }
  }
  return { triple, platformPackage }
}

export function resolveNativeCodexBinary({ platform, arch, resolvePackage = defaultResolvePackage } = {}) {
  const { triple, platformPackage } = nativeCodexTarget({ platform, arch }, resolvePackage)
  const manifest = resolvePackage(platformPackage + '/package.json')
  const binary = path.join(path.dirname(manifest), 'vendor', triple, 'bin',
    process.platform === 'win32' ? 'codex.exe' : 'codex')
  let stat, real
  try { stat = lstatSync(binary); real = realpathSync(binary) } catch { stat = null }
  if (!stat || !stat.isFile() || stat.isSymbolicLink() || (stat.mode & 0o111) === 0)
    throw new Error('Verified native Codex binary is absent')
  return real
}

/** An externally supplied CODEX_PATH is only honoured when it is that binary. */
export function assertNativeCodexSpecifier(specifier, nativeBinary) {
  if (typeof specifier !== 'string' || !path.isAbsolute(specifier) || path.normalize(specifier) !== specifier
      || /\.(?:js|mjs|cjs)$/u.test(specifier)) throw new Error('Refusing an unverified native Codex binary')
  let real
  try { real = realpathSync(specifier) } catch { throw new Error('Refusing an unverified native Codex binary') }
  if (real !== nativeBinary) throw new Error('Refusing an unverified native Codex binary')
  return real
}

// --- process identity and the owned process set -------------------------------

function readProcEntry(pid) {
  let text
  try { text = readFileSync(`/proc/${pid}/stat`, 'utf8') } catch { return null }
  const cut = text.lastIndexOf(')')
  if (cut < 0) return null
  const fields = text.slice(cut + 2).split(' ')
  const head = Number(text.slice(0, text.indexOf(' ')))
  if (!Number.isSafeInteger(head) || fields.length < 20) return null
  let executable = null
  try { executable = realpathSync(`/proc/${head}/exe`) } catch { /* exited or unreadable */ }
  return { pid: head, state: fields[0], ppid: Number(fields[1]), pgid: Number(fields[2]),
    startTime: fields[19], executable }
}

export function readProcessSnapshot() {
  // Identity comes from the kernel, so procfs is a hard requirement rather than
  // a best-effort guess on an unsupported platform.
  if (process.platform !== 'linux') return { byPid: new Map(), supported: false }
  const byPid = new Map()
  let names
  try { names = readdirSync('/proc') } catch { return { byPid, supported: false } }
  for (const name of names) {
    if (!/^\d+$/u.test(name)) continue
    const entry = readProcEntry(Number(name))
    if (entry) byPid.set(entry.pid, entry)
  }
  return { byPid, supported: true }
}

/**
 * Live processes this instance owns: the managed pid, its own process group and
 * its descendants. A zombie has released its executable and cannot act, so it
 * never counts as a surviving native process. `startTime` is the start time
 * recorded with our identity: a pid now held by a process that started later is
 * a reused pid, not ours, so it is neither a survivor nor a signal target.
 */
export function ownedProcessSet(snapshot, { pid, pgid, startTime = null }) {
  if (!snapshot?.supported) return []
  const members = new Set()
  if (Number.isSafeInteger(pid) && pid > 0) members.add(pid)
  if (Number.isSafeInteger(pgid) && pgid > 0) for (const entry of snapshot.byPid.values())
    if (entry.pgid === pgid && entry.state !== 'Z') members.add(entry.pid)
  // Closure to a fixpoint: procfs enumerates unordered, so a grandchild can be
  // read before its own parent has joined the set and a single pass would drop
  // it — leaving a live native descendant outside every escalation round.
  for (let grew = true; grew;) {
    grew = false
    for (const entry of snapshot.byPid.values()) {
      if (entry.state === 'Z' || members.has(entry.pid) || !members.has(entry.ppid)) continue
      members.add(entry.pid); grew = true
    }
  }
  members.delete(process.pid)
  const reused = startTime && snapshot.byPid.get(pid)?.startTime !== startTime ? pid : null
  return [...members].map(entry => snapshot.byPid.get(entry))
    .filter(entry => entry && entry.state !== 'Z' && entry.pid !== reused)
}

export function assertNativeProcess(pid, nativeBinary, snapshot = readProcessSnapshot()) {
  if (!snapshot.supported) throw new Error('Native process identity requires procfs')
  const entry = snapshot.byPid.get(pid)
  if (!entry) throw new Error('The managed native process is not present')
  if (entry.executable !== nativeBinary)
    throw new Error('The managed process is not the verified native Codex binary')
  return identityOf(entry)
}

const identityOf = entry => ({ pid: entry.pid, pgid: entry.pgid, ppid: entry.ppid, state: entry.state,
  executable: entry.executable, startTime: entry.startTime, leader: entry.pgid === entry.pid })

export function processIdentity(pid, snapshot = readProcessSnapshot()) {
  const entry = snapshot.supported ? snapshot.byPid.get(pid) : null
  return entry ? identityOf(entry) : null
}

/** The retired native owner must be gone, and its pid must not have been reused. */
export function assertProcessGone(identity, snapshot = readProcessSnapshot()) {
  if (!snapshot.supported) throw new Error('Native process identity requires procfs')
  // Reuse is decided before survival: a live pid with a later start time is a
  // different process, and reporting it as a survivor of ours hides the reuse.
  const reused = identity.startTime ? snapshot.byPid.get(identity.pid) : null
  if (reused && reused.startTime !== identity.startTime)
    throw new Error('The previous native process pid was reused')
  if (ownedProcessSet(snapshot, { pid: identity.pid, pgid: identity.pgid,
    startTime: identity.startTime }).length)
    throw new Error('The previous native process is still present')
  return { gone: true, pid: identity.pid }
}

export function spawnNativeCodex({ nativeBinary, args = [], env, spawn = nodeSpawn,
  readSnapshot = readProcessSnapshot, identityTimeoutMs = 5000 } = {}) {
  if (typeof nativeBinary !== 'string' || !path.isAbsolute(nativeBinary))
    throw new Error('Refusing to launch an unverified native Codex binary')
  // Own the whole group: descendants that leave our pid chain still get signalled.
  const child = spawn(nativeBinary, args, { env, detached: true, stdio: ['pipe', 'pipe', 'pipe'] })
  child.ordessaSignals = []
  child.ordessaNativeBinary = nativeBinary
  const deadline = Date.now() + identityTimeoutMs
  child.ordessaNativeIdentity = new Promise((resolve, reject) => {
    const poll = () => {
      if (exited(child)) return reject(new Error('The native process exited before its identity was confirmed'))
      const snapshot = readSnapshot()
      if (!snapshot.supported) return reject(new Error('Native process identity requires procfs'))
      const entry = snapshot.byPid.get(child.pid)
      if (entry && entry.executable === nativeBinary && entry.pgid === entry.pid)
        return resolve(identityOf(entry))
      if (Date.now() > deadline) return reject(new Error('The native process identity was not confirmed'))
      setTimeout(poll, 20)
    }
    poll()
  })
  // An unconfirmed child must never be left running beside its replacement.
  child.ordessaNativeIdentity.catch(() => { try { process.kill(-child.pid, 'SIGKILL') } catch { /* gone */ } })
  return child
}

export async function stopNativeProcess(child, { graceMs = 2000, terminateMs = 2000, killMs = 2000,
  readSnapshot = readProcessSnapshot, signal = defaultSignal } = {}) {
  if (!child) throw new Error('No managed native process')
  let identity = null
  try { identity = await (child.ordessaNativeIdentity ?? null) } catch { identity = null }
  if (!identity && Number.isSafeInteger(child.pid) && child.pid > 0)
    identity = { pid: child.pid, pgid: child.pid, leader: false }
  const owned = () => identity ? ownedProcessSet(readSnapshot(), { pid: identity.pid,
    pgid: identity.pgid, startTime: identity.startTime }) : []
  const confirmed = () => (identity ? exited(child) && owned().length === 0 : exited(child))
  if (confirmed()) return
  let onExit, timer, didExit = false
  const completion = new Promise(resolve => { onExit = () => { didExit = true; resolve(true) }; child.once('exit', onExit) })
  const wait = async milliseconds => {
    if (confirmed()) return true
    if (didExit || exited(child)) return confirmed()
    const timeout = new Promise(resolve => { timer = setTimeout(() => resolve(false), milliseconds) })
    try { await Promise.race([completion, timeout]) } finally { clearTimeout(timer) }
    return confirmed()
  }
  const escalate = async (name, milliseconds) => {
    if (identity) { for (const target of new Set(owned().map(entry => entry.pid)))
      { try { signal(target, name) } catch { /* already gone */ } } }
    else { try { child.kill(name) } catch { /* already gone */ } }
    if (Array.isArray(child.ordessaSignals)) child.ordessaSignals.push(name)
    return wait(milliseconds)
  }
  try {
    // Install the exit listener first, including for fast/synchronous exits.
    try { child.stdin.end() } catch { /* bounded signal fallback */ }
    if (await wait(graceMs)) return
    if (await escalate('SIGTERM', terminateMs)) return
    if (await escalate('SIGKILL', killMs)) return
    throw new Error('Native process exit was not confirmed')
  } finally {
    clearTimeout(timer); child.removeListener('exit', onExit)
  }
}

export async function replaceNativeProcess(previous, start, options = {}) {
  const stop = options.stopNative ?? stopNativeProcess
  await stop(previous, options)
  let next
  try {
    next = await start()
    if (options.initialize) await options.initialize(next)
    return next
  } catch (failure) {
    // A start() that threw produced no owner, so there is nothing to clean up and
    // the primary failure stands alone rather than beside a bogus cleanup error.
    if (next?.process) {
      try { await stop(next.process, options) }
      catch (cleanupError) {
        failure.nativeCleanupFailed = true
        failure.nativeCleanupReason = String(cleanupError?.message ?? cleanupError)
      }
    }
    throw failure
  }
}

// --- account, history and binding ownership -----------------------------------

export function managedAccountDirectory(directory, instance) {
  if (typeof directory !== 'string' || !path.isAbsolute(directory)
      || path.normalize(directory) !== directory || directory.endsWith(path.sep)
      || typeof instance !== 'string' || !path.isAbsolute(instance)
      || directory === instance || directory.startsWith(instance + path.sep)
      || instance.startsWith(directory + path.sep))
    throw new Error('Invalid managed account scope')
  const stat = lstatSync(directory)
  if (!stat.isDirectory() || stat.isSymbolicLink() || realpathSync(directory) !== directory
      || stat.uid !== process.getuid() || (stat.mode & 0o077) !== 0)
    throw new Error('Invalid managed account ownership')
  return directory
}

function assertRealOwnedFile(filename, message) {
  // realpath resolves the whole chain, so a symlinked parent directory is caught
  // here even when the leaf itself is a regular file.
  const stat = lstatSync(filename)
  if (!stat.isFile() || stat.isSymbolicLink() || realpathSync(filename) !== filename
      || stat.uid !== process.getuid())
    throw new Error(message)
  return filename
}

export function ownedRolloutPath(thread, sessionId, home, previouslyOwnedPath) {
  const filename = thread?.path
  if (thread?.id !== sessionId || typeof filename !== 'string' || !path.isAbsolute(filename)
      || path.normalize(filename) !== filename || !path.isAbsolute(home)
      || (!filename.startsWith(path.join(home, 'sessions') + path.sep)
        && filename !== previouslyOwnedPath))
    throw new Error('Native history is not persisted in the owned scope')
  return assertRealOwnedFile(filename, 'Native history ownership is invalid')
}

/** An empty or damaged rollout cannot stand in for a resumed native thread. */
function assertUsableRollout(filename) {
  const unusable = () => { throw new Error('Native history rollout is not usable') }
  let handle
  try { handle = openSync(filename, 'r') } catch { unusable() }
  try {
    const size = fstatSync(handle).size
    if (size <= 0) unusable()
    const buffer = Buffer.alloc(Math.min(size, 65536))
    const read = readSync(handle, buffer, 0, buffer.length, 0)
    if (read <= 0) unusable()
    const lines = buffer.toString('utf8', 0, read).split('\n')
    // Only a truncated tail is tolerated, never a damaged record.
    if (read < buffer.length) lines.pop()
    for (const line of lines) {
      if (!line.trim()) continue
      try { JSON.parse(line) } catch { unusable() }
    }
  } catch (error) {
    if (String(error?.message) === 'Native history rollout is not usable') throw error
    unusable()
  } finally { closeSync(handle) }
  return filename
}

/** Read this owner's live thread before any native effect; refuse on mismatch. */
export async function captureCodexHistory({ client, sessionId, home, previouslyOwnedPath }) {
  if (typeof sessionId !== 'string' || !sessionId || sessionId.length > 4096)
    throw new Error('Expected a bounded native session id')
  const history = await client.codexClient.threadRead({ threadId: sessionId, includeTurns: false })
  const thread = history?.thread
  if (thread?.id !== sessionId)
    throw new Error('Native history is not the bound session in the owned scope')
  if (typeof thread.path !== 'string' || !thread.path)
    throw new Error('Native history is not persisted for this session')
  return assertUsableRollout(ownedRolloutPath(thread, sessionId, home, previouslyOwnedPath))
}

/**
 * A native `thread/resume` ACK is only a resume when it names the bound thread
 * and, when a private rollout was bound, that same rollout. Upstream echoes the
 * requested session id back, so an ACK alone proves nothing on its own.
 */
export function assertResumedThread(response, sessionId, expectedRolloutPath) {
  const thread = response?.thread
  if (!thread || typeof thread !== 'object' || typeof sessionId !== 'string' || !sessionId)
    throw new Error('Native resume did not resume the bound native thread')
  if (thread.id !== sessionId) throw new Error('Native resume resumed a different native thread')
  if (expectedRolloutPath !== undefined && expectedRolloutPath !== null
      && (typeof expectedRolloutPath !== 'string' || !expectedRolloutPath))
    throw new Error('Native resume did not resume the bound native thread')
  const expected = expectedRolloutPath ? expectedRolloutPath : null
  if (expected) {
    if (typeof thread.path !== 'string' || !thread.path)
      throw new Error('Native resume did not resume the bound native thread')
    if (path.resolve(thread.path) !== path.resolve(expected))
      throw new Error('Native resume returned a different native rollout')
  }
  return { sessionId, rolloutPath: typeof thread.path === 'string' && thread.path ? path.resolve(thread.path) : null }
}

/**
 * Publish one replacement owner in a fixed order: read history, stop the old
 * native process, invalidate the dead binding, spawn, initialize. The primary
 * error is preserved; a cleanup failure is reported beside it.
 */
export async function orchestrateCodexReplacement({ instance, sessionId, capture, stop, start,
  initialize = null, cleanup = null }) {
  await capture()
  try { await stop() }
  catch (error) {
    invalidateCodexSession(instance, sessionId, 'native-exit-unconfirmed')
    throw error
  }
  invalidateCodexSession(instance, sessionId, 'native-replaced')
  let next
  try {
    next = await start()
    if (initialize) await initialize(next)
  } catch (failure) {
    // A start() that threw produced no owner, so there is nothing to clean up and
    // the primary failure stands alone rather than beside a bogus cleanup error.
    if (next) {
      try { await (cleanup ? cleanup(next) : stopNativeProcess(next.process)) }
      catch (cleanupError) {
        failure.nativeCleanupFailed = true
        failure.nativeCleanupReason = String(cleanupError?.message ?? cleanupError)
      }
    }
    invalidateCodexSession(instance, sessionId, 'native-replacement-failed')
    throw failure
  }
  instance.ordessaInvalidSessions.delete(sessionId)
  return next
}

/** A dead native owner must not keep a routable client, session or resume path. */
export function invalidateCodexSession(instance, sessionId, reason) {
  if (!instance || typeof sessionId !== 'string' || !sessionId || sessionId.length > 4096)
    throw new Error('Expected a bounded native session id')
  const invalid = instance.ordessaInvalidSessions ??= new Set()
  invalid.add(sessionId)
  if (typeof reason === 'string' && reason) (instance.ordessaInvalidReasons ??= new Map()).set(sessionId, reason)
  if (instance.sessions instanceof Map) instance.sessions.delete(sessionId)
  else if (instance.sessions && typeof instance.sessions === 'object') delete instance.sessions[sessionId]
  const client = instance.codexAcpClient
  if (client && typeof client === 'object') {
    client.ordessaDisconnected = true
    delete client.ordessaResumeRolloutPath
    delete client.ordessaOwnedRolloutPath
  }
  return { sessionId, reason: typeof reason === 'string' ? reason : null }
}

/** Every fresh object follows the new connection; the retired one is marked. */
export function rebindCodexConnection(instance, { connection, AppServerClass, ClientClass, CommandsClass,
  config, model, rolloutPath, acpConnection, runWithProcessCheck, onAuthStateRefresh }) {
  if (!instance || !connection || !AppServerClass || !ClientClass || !CommandsClass)
    throw new Error('A complete native rebinding is required')
  const previous = instance.codexAcpClient ?? null
  if (previous && typeof previous === 'object') {
    previous.ordessaDisconnected = true
    delete previous.ordessaResumeRolloutPath
  }
  const client = new ClientClass(new AppServerClass(connection), { ...config, model }, null)
  client.ordessaResumeRolloutPath = rolloutPath
  client.ordessaOwnedRolloutPath = rolloutPath
  instance.codexAcpClient = client
  instance.availableCommands = new CommandsClass(acpConnection ?? instance.connection, client,
    runWithProcessCheck, onAuthStateRefresh)
  return { client, previous }
}
