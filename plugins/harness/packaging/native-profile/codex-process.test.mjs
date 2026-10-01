import test from 'node:test'
import assert from 'node:assert/strict'
import { EventEmitter } from 'node:events'
import { spawn } from 'node:child_process'
import {
  replaceNativeProcess, ownedRolloutPath, managedAccountDirectory, nativeCodexTarget,
  resolveNativeCodexBinary, assertNativeCodexSpecifier, assertNativeProcess, processIdentity,
  readProcessSnapshot, ownedProcessSet, assertProcessGone, spawnNativeCodex, stopNativeProcess,
  captureCodexHistory, rebindCodexConnection, invalidateCodexSession, orchestrateCodexReplacement,
  assertResumedThread,
} from './codex-process.mjs'
import { chmodSync, copyFileSync, existsSync, mkdtempSync, mkdirSync, realpathSync,
  writeFileSync, symlinkSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'

// A copied interpreter stands in for the vendor binary: /proc/<pid>/exe really
// resolves to it, so identity checks run against the real kernel, not a stub.
const DASH = existsSync('/usr/bin/dash') ? '/usr/bin/dash' : '/bin/dash'

function nativeFixture(t) {
  const root = realpathSync(mkdtempSync(path.join(tmpdir(), 'ordessa-native-test-')))
  t.after(() => rmSync(root, { recursive: true, force: true }))
  const triple = nativeCodexTarget().triple
  const packageRoot = path.join(root, 'node_modules', '@openai', 'codex-linux-x64')
  const binary = path.join(packageRoot, 'vendor', triple, 'bin', 'codex')
  mkdirSync(path.dirname(binary), { recursive: true })
  writeFileSync(path.join(packageRoot, 'package.json'), '{"name":"@openai/codex"}')
  copyFileSync(DASH, binary); chmodSync(binary, 0o755)
  return { root, triple, binary, realpathSync, resolver: name => path.join(root, 'node_modules', '@openai',
    String(name).replace('@openai/', '').replace('/package.json', ''), 'package.json') }
}

test('history path must match the owned session and scope; only a previously bound path crosses homes', () => {
  const root = mkdtempSync(path.join(tmpdir(), 'ordessa-history-test-'))
  try {
    const home = path.join(root, 'home'); const second = path.join(root, 'second')
    mkdirSync(path.join(home, 'sessions'), {recursive: true}); mkdirSync(second, {mode: 0o700})
    const file = path.join(home, 'sessions', 'rollout.jsonl'); writeFileSync(file, 'fixture')
    const thread = {id: 'session', path: file}
    assert.equal(ownedRolloutPath(thread, 'session', home), file)
    assert.throws(() => ownedRolloutPath(thread, 'other', home), /owned scope/)
    assert.throws(() => ownedRolloutPath(thread, 'session', second), /owned scope/)
    assert.equal(ownedRolloutPath(thread, 'session', second, file), file)
    const link = path.join(home, 'sessions', 'link.jsonl'); symlinkSync(file, link)
    assert.throws(() => ownedRolloutPath({...thread, path: link}, 'session', home), /ownership/)
    assert.equal(managedAccountDirectory(second, home), second)
    assert.throws(() => managedAccountDirectory(home, home), /scope/)
    const alias = path.join(root, 'alias'); symlinkSync(second, alias)
    assert.throws(() => managedAccountDirectory(alias, home), /ownership/)
  } finally { rmSync(root, {recursive: true, force: true}) }
})

function peer({ exits = true } = {}) {
  const child = new EventEmitter()
  child.exitCode = null; child.signalCode = null; child.killed = false
  child.stdin = { end() {} }
  child.signals = []
  child.kill = signal => {
    child.killed = true; child.signals.push(signal)
    if (exits) queueMicrotask(() => {
      child.signalCode = signal; child.emit('exit', null, signal)
    })
    return true
  }
  return child
}

test('replacement starts only after authoritative exit, not killed flag', async () => {
  const old = peer(); let starts = 0
  const result = await replaceNativeProcess(old, async () => {
    starts++; assert.notEqual(old.signalCode, null)
    return { process: peer() }
  }, { graceMs: 1, terminateMs: 1, killMs: 1 })
  assert.equal(starts, 1); assert.deepEqual(old.signals, ['SIGTERM'])
  assert.ok(result.process)
})

test('an unconfirmed exit refuses replacement even when kill returned true', async () => {
  const old = peer({ exits: false }); let starts = 0
  await assert.rejects(replaceNativeProcess(old, async () => { starts++ },
    { graceMs: 1, terminateMs: 1, killMs: 1 }), /exit was not confirmed/)
  assert.equal(starts, 0); assert.equal(old.killed, true)
  assert.deepEqual(old.signals, ['SIGTERM', 'SIGKILL'])
  assert.equal(old.listenerCount('exit'), 0)
})

test('initialization failure disposes the new process without retrying', async () => {
  const old = peer(); old.exitCode = 0
  const next = peer(); let starts = 0
  await assert.rejects(replaceNativeProcess(old, async () => {
    starts++; return { process: next }
  }, { graceMs: 1, terminateMs: 1, killMs: 1,
    initialize: async () => { throw new Error('synthetic startup failure') } }), /synthetic startup failure/)
  assert.equal(starts, 1); assert.equal(next.signalCode, 'SIGTERM')
})

test('actual native-style child exits before replacement and sibling stays live', async () => {
  const old = spawn(process.execPath, ['-e', 'process.stdin.resume(); process.stdin.on("end", () => process.exit(0))'])
  const sibling = spawn(process.execPath, ['-e', 'setInterval(() => {}, 1000)'])
  let next
  try {
    await replaceNativeProcess(old, async () => {
      assert.notEqual(old.exitCode, null)
      next = spawn(process.execPath, ['-e', 'setInterval(() => {}, 1000)'])
      return { process: next }
    })
    assert.equal(sibling.exitCode, null); assert.equal(sibling.killed, false)
  } finally {
    if (next) next.kill('SIGKILL')
    sibling.kill('SIGKILL'); if (old.exitCode === null) old.kill('SIGKILL')
  }
})

// --- T1.1 / T1.2 / A01 / A03 / A21: the managed process is the native binary ---

test('the native target is selected explicitly; other platforms and triples are refused', () => {
  assert.deepEqual(nativeCodexTarget(), { triple: 'x86_64-unknown-linux-musl', platformPackage: '@openai/codex-linux-x64' })
  assert.deepEqual(nativeCodexTarget({ platform: 'linux', arch: 'arm64' }),
    { triple: 'aarch64-unknown-linux-musl', platformPackage: '@openai/codex-linux-arm64' })
  for (const target of [{ platform: 'linux', arch: 'ia32' }, { platform: 'sunos', arch: 'x64' },
    { platform: 'darwin', arch: 'ppc64' }, { platform: 'android', arch: 'riscv64' }])
    assert.throws(() => nativeCodexTarget(target), /not a supported Codex platform/)
  // A supported triple with no platform package installed is still a refusal.
  assert.throws(() => nativeCodexTarget({ platform: 'darwin', arch: 'arm64' }, () => {
    throw new Error('missing')
  }), /platform package is absent/)
})

test('resolution composes the pinned vendor path and never accepts a launcher or a PATH shim', t => {
  const f = nativeFixture(t)
  assert.equal(resolveNativeCodexBinary({ resolvePackage: f.resolver }), f.binary)
  assert.equal(assertNativeCodexSpecifier(f.binary, f.binary), f.binary)
  for (const rejected of ['codex', '/usr/local/bin/codex', f.root + '/bin/codex.js',
    f.binary + '.js', f.root + '/../' + path.relative(f.root, f.binary), ''])
    assert.throws(() => assertNativeCodexSpecifier(rejected, f.binary), /verified native Codex binary/)
  assert.throws(() => resolveNativeCodexBinary({ resolvePackage: () => path.join(f.root, 'absent', 'package.json') }),
    /native Codex binary is absent/)
})

test('a managed process must really be the native executable, never a Node launcher', async t => {
  const f = nativeFixture(t)
  const nativeChild = spawnNativeCodex({ nativeBinary: f.binary, args: ['-c', 'read line'] })
  const launcher = spawn(process.execPath, ['-e', 'process.stdin.resume()'])
  t.after(() => { for (const child of [nativeChild, launcher]) { try { process.kill(child.pid, "SIGKILL") } catch { /* gone */ } } })
  const identity = await nativeChild.ordessaNativeIdentity
  assert.equal(identity.executable, f.binary)
  assert.equal(identity.leader, true)
  assert.equal(identity.pgid, identity.pid)
  assert.equal(identity.startTime, processIdentity(identity.pid).startTime)
  // A live Node launcher is never accepted as the native owner.
  assert.throws(() => assertNativeProcess(launcher.pid, f.binary), /not the verified native Codex binary/)
  assert.throws(() => assertNativeProcess(nativeChild.pid + 999999, f.binary), /not present/)
  // Same pid, different start time is pid reuse, not survival.
  assert.throws(() => assertProcessGone({ ...identity, startTime: '0' }), /still present/)
})

test('a launcher exit is never accepted as native exit; the owned group must be gone first', async () => {
  // A real launcher-shaped parent: SIGKILL on it orphans the native descendant,
  // which stays alive inside the group the launcher led. A replacement must
  // never be created beside it, and must not wait on the launcher exit alone.
  const root = mkdtempSync(path.join(tmpdir(), 'ordessa-orphan-test-'))
  const binary = path.join(root, 'codex')
  copyFileSync(DASH, binary); chmodSync(binary, 0o755)
  const launcher = spawn(process.execPath, ['-e',
    `const { spawn } = require('child_process'); spawn(${JSON.stringify(binary)}, ['-c', 'sleep 30'], { stdio: 'inherit' }); process.stdin.resume()`,
  ], { detached: true, stdio: ['pipe', 'pipe', 'pipe'] })
  const owned = () => ownedProcessSet(readProcessSnapshot(), { pid: launcher.pid, pgid: launcher.pid })
  let descendant
  try {
    descendant = await new Promise((resolve, reject) => {
      const deadline = Date.now() + 5000
      const poll = () => {
        const entry = owned().find(item => item.pid !== launcher.pid)
        if (entry) return resolve(entry)
        if (Date.now() > deadline) return reject(new Error('descendant never appeared'))
        setTimeout(poll, 25)
      }
      poll()
    })
    assert.equal(descendant.executable, binary)
    launcher.kill('SIGKILL')
    await new Promise(resolve => launcher.once('exit', resolve))
    assert.equal(launcher.signalCode, 'SIGKILL')
    // The launcher is gone; the native descendant it started is not.
    assert.ok(readProcessSnapshot().byPid.get(descendant.pid), 'orphan native descendant must still be present')
    let starts = 0
    await replaceNativeProcess(launcher, () => {
      starts++
      assert.deepEqual(owned(), [], 'a replacement must never start beside a surviving native process')
      return { process: peer() }
    }, { graceMs: 50, terminateMs: 200, killMs: 2000 })
    assert.equal(starts, 1)
    assert.deepEqual(owned(), [], 'the whole owned group must be released')
  } finally {
    try { process.kill(-launcher.pid, 'SIGKILL') } catch { /* already released */ }
    for (const pid of [descendant?.pid, launcher.pid]) { try { process.kill(pid, 'SIGKILL') } catch { /* gone */ } }
    rmSync(root, { recursive: true, force: true })
  }
})

test('an unkillable surviving native descendant still refuses the replacement', async () => {
  const old = peer()
  old.exitCode = 0; old.pid = 4242
  old.ordessaNativeIdentity = Promise.resolve({ pid: 4242, pgid: 4242, leader: true,
    executable: '/verified/native/codex', startTime: '1' })
  const snapshot = { supported: true, byPid: new Map([
    [4242, { pid: 4242, pgid: 4242, ppid: 1, state: 'Z', executable: '/verified/native/codex' }],
    [4243, { pid: 4243, pgid: 4242, ppid: 1, state: 'D', executable: '/verified/native/codex' }],
    [process.pid, { pid: process.pid, pgid: process.pid, ppid: 1, state: 'S', executable: '/verified/native/codex' }]]) }
  let starts = 0
  const signals = []
  await assert.rejects(replaceNativeProcess(old, () => { starts++; return { process: peer() } },
    { graceMs: 1, terminateMs: 1, killMs: 1, readSnapshot: () => snapshot,
      signal: (pid, signal) => { signals.push([pid, signal]); return true } }), /exit was not confirmed/)
  assert.equal(starts, 0)
  assert.deepEqual([...new Set(signals.map(entry => entry[1]))], ['SIGTERM', 'SIGKILL'])
  assert.ok(signals.some(([pid]) => pid === 4243), 'the surviving descendant must be signalled, not just the launcher pid')
  assert.equal(signals.some(([pid]) => pid === process.pid), false, 'never signal this instance')
})

test('grace, terminate and kill stay bounded and only the OS exit event confirms', async t => {
  const f = nativeFixture(t)
  const stubborn = spawnNativeCodex({ nativeBinary: f.binary, args: ['-c', "trap '' TERM; while :; do :; done"] })
  const polite = spawnNativeCodex({ nativeBinary: f.binary, args: ['-c', 'read line'] })
  try {
    await stubborn.ordessaNativeIdentity
    await stopNativeProcess(polite, { graceMs: 2000, terminateMs: 2000, killMs: 2000 })
    assert.notEqual(polite.exitCode, null, 'closing our own stdin must end the native process')
    const began = Date.now()
    await stopNativeProcess(stubborn, { graceMs: 200, terminateMs: 200, killMs: 2000 })
    assert.deepEqual(stubborn.ordessaSignals, ['SIGTERM', 'SIGKILL'])
    assert.equal(stubborn.killed, false, 'the owned group is signalled directly, never through .killed')
    assert.equal(stubborn.exitCode, null)
    assert.equal(stubborn.signalCode, 'SIGKILL', 'the OS exit event is the only proof')
    assert.equal(assertProcessGone(stubborn.ordessaNativeIdentity).gone, true)
    assert.ok(Date.now() - began < 6000, 'the escalation ladder must stay bounded')
  } finally {
    for (const child of [stubborn, polite]) { try { process.kill(-child.pid, 'SIGKILL') } catch {} }
  }
})

test('replacement publishes the new native owner only after the old one is confirmed gone', async t => {
  const f = nativeFixture(t)
  const old = spawnNativeCodex({ nativeBinary: f.binary, args: ['-c', 'read line'] })
  const oldIdentity = await old.ordessaNativeIdentity
  let next
  try {
    const result = await replaceNativeProcess(old, async () => {
      assert.equal(assertProcessGone(oldIdentity).gone, true)
      assert.notEqual(old.exitCode, null)
      next = spawnNativeCodex({ nativeBinary: f.binary, args: ['-c', 'read line'] })
      return { process: next, connection: 'replacement-connection' }
    })
    assert.notEqual(result.process.pid, oldIdentity.pid)
    assert.equal(result.connection, 'replacement-connection')
  } finally {
    if (next) try { process.kill(-next.pid, 'SIGKILL') } catch {}
  }
})

// --- T1.3 / A11: initialization failure keeps the primary error and stays fail-closed ---

test('a fresh native client that fails to initialize keeps the primary error and the dead binding invalid', async () => {
  const old = peer(); old.exitCode = 0
  const next = peer()
  const previousClient = { codexClient: { connection: 'dead-connection' } }
  const instance = { sessions: new Map([['s', {}]]), codexAcpClient: previousClient,
    availableCommands: { client: previousClient } }
  await assert.rejects(replaceNativeProcess(old, async () => ({ process: next }), {
    graceMs: 1, terminateMs: 1, killMs: 1,
    initialize: async () => { throw new Error('synthetic startup failure') },
    stopNative: async (child, options) => {
      if (child === next) throw new Error('native cleanup did not confirm exit')
      return stopNativeProcess(child, options)
    },
  }), error => {
    assert.match(error.message, /synthetic startup failure/)
    assert.equal(error.nativeCleanupFailed, true)
    assert.equal(error.nativeCleanupReason, 'native cleanup did not confirm exit')
    return true
  })
  assert.equal(next.signalCode, null, 'a cleanup that did not confirm must not claim exit')
  // The old binding is now invalid; no prompt may pass through it.
  invalidateCodexSession(instance, 's', 'native-replacement-failed')
  assert.equal(instance.sessions.has('s'), false)
  assert.equal(instance.codexAcpClient.ordessaDisconnected, true)
  assert.deepEqual([...instance.ordessaInvalidSessions], ['s'])
})

test('replacement never spawns twice when the previous exit cannot be confirmed', async () => {
  const old = peer({ exits: false })
  let starts = 0
  await assert.rejects(replaceNativeProcess(old, () => { starts++; return { process: peer() } },
    { graceMs: 1, terminateMs: 1, killMs: 1 }), /exit was not confirmed/)
  await assert.rejects(replaceNativeProcess(old, () => { starts++; return { process: peer() } },
    { graceMs: 1, terminateMs: 1, killMs: 1 }), /exit was not confirmed/)
  assert.equal(starts, 0)
})

// --- T1.4 / A10: every fresh object points at the new connection ---

test('the fresh client, commands and resume path all follow the new connection', async () => {
  const connections = []
  class AppServer { constructor(connection) { this.connection = connection } }
  class Client {
    constructor(codexClient, config, modelProvider) {
      this.codexClient = codexClient; this.config = config; this.modelProvider = modelProvider
      connections.push(this)
    }
  }
  const commands = []
  class Commands {
    constructor(connection, client, runWithProcessCheck, onAuthStateRefresh) {
      this.connection = connection; this.client = client
      this.runWithProcessCheck = runWithProcessCheck; this.onAuthStateRefresh = onAuthStateRefresh
      commands.push(this)
    }
  }
  const dead = new AppServer('dead-connection')
  const previousClient = new Client(dead, {}, null)
  const instance = { connection: 'acp-connection', sessions: new Map(),
    codexAcpClient: previousClient, availableCommands: new Commands('acp-connection', previousClient) }
  const live = 'live-connection'
  const runWithProcessCheck = operation => operation()
  const onAuthStateRefresh = () => {}
  const { client, previous } = rebindCodexConnection(instance, { connection: live,
    AppServerClass: AppServer, ClientClass: Client, CommandsClass: Commands,
    config: { reasoning: 'high' }, model: 'gpt-5', rolloutPath: '/private/rollout.jsonl',
    acpConnection: 'acp-connection', runWithProcessCheck, onAuthStateRefresh })
  assert.equal(instance.codexAcpClient, client)
  assert.equal(previous, previousClient)
  assert.notEqual(previous, client)
  assert.equal(client.codexClient.connection, live)
  assert.equal(previous.codexClient, dead)
  assert.equal(client.config.model, 'gpt-5')
  assert.equal(client.config.reasoning, 'high')
  assert.equal(client.ordessaResumeRolloutPath, '/private/rollout.jsonl')
  assert.equal(commands.at(-1).client, client)
  assert.equal(commands.at(-1).connection, 'acp-connection')
  assert.equal(commands.at(-1).runWithProcessCheck, runWithProcessCheck)
  assert.equal(commands.at(-1).onAuthStateRefresh, onAuthStateRefresh)
  assert.equal(previous.ordessaDisconnected, true)
  assert.equal(previous.ordessaResumeRolloutPath, undefined)
  assert.equal(instance.availableCommands.client.codexClient.connection, 'live-connection')
  assert.equal(commands.slice(1).filter(entry => entry.client === previous).length, 0)
})

// --- T1.5 / T1.6 / A06-A09 / A12: rollout ownership and resume truthfulness ---

test('a sibling thread or an unpersisted thread stops the replacement before any effect', async () => {
  const root = mkdtempSync(path.join(tmpdir(), 'ordessa-capture-test-'))
  try {
    const home = path.join(root, 'home')
    mkdirSync(path.join(home, 'sessions'), { recursive: true })
    const rollout = path.join(home, 'sessions', 'rollout.jsonl')
    writeFileSync(rollout, '{"type":"session_meta"}\n')
    const reading = thread => ({ codexClient: { threadRead: async request => {
      if (request.threadId !== 's' || request.includeTurns !== false) throw new Error('wrong thread/read request')
      return { thread }
    } } })
    // A06: a sibling session id is refused, not adopted.
    await assert.rejects(captureCodexHistory({ client: reading({ id: 'sibling', path: rollout }), sessionId: 's', home }),
      /owned scope/)
    // A09: no persisted rollout means no restore; never a fresh session.
    await assert.rejects(captureCodexHistory({ client: reading({ id: 's' }), sessionId: 's', home }), /not persisted/)
    await assert.rejects(captureCodexHistory({ client: reading({ id: 's', path: '' }), sessionId: 's', home }), /not persisted/)
    assert.equal(ownedRolloutPath({ id: 's', path: rollout }, 's', home), rollout)
  } finally { rmSync(root, { recursive: true, force: true }) }
})

test('an empty or damaged rollout is refused; a real persisted rollout binds', async () => {
  const root = mkdtempSync(path.join(tmpdir(), 'ordessa-rollout-test-'))
  try {
    const home = path.join(root, 'home'); const elsewhere = path.join(root, 'other')
    mkdirSync(path.join(home, 'sessions'), { recursive: true })
    mkdirSync(path.join(elsewhere, 'sessions'), { recursive: true })
    const rollout = path.join(elsewhere, 'sessions', 'rollout.jsonl')
    const client = { codexClient: { threadRead: async () => ({ thread: { id: 's', path: rollout } }) } }
    writeFileSync(rollout, '')
    await assert.rejects(captureCodexHistory({ client, sessionId: 's', home, previouslyOwnedPath: rollout }), /usable/)
    writeFileSync(rollout, 'not json at all\n')
    await assert.rejects(captureCodexHistory({ client, sessionId: 's', home, previouslyOwnedPath: rollout }), /usable/)
    writeFileSync(rollout, '{"type":"session_meta"}\n')
    assert.equal(await captureCodexHistory({ client, sessionId: 's', home, previouslyOwnedPath: rollout }), rollout)
    // A07: a directory is never a usable history file.
    const directory = path.join(elsewhere, 'sessions')
    assert.throws(() => ownedRolloutPath({ id: 's', path: directory }, 's', home, directory), /ownership/)
  } finally { rmSync(root, { recursive: true, force: true }) }
})

test('a symlinked parent directory is refused even when the file itself is regular', () => {
  const root = mkdtempSync(path.join(tmpdir(), 'ordessa-parentlink-test-'))
  try {
    const real = path.join(root, 'real'); const home = path.join(root, 'home')
    mkdirSync(path.join(real, 'sessions'), { recursive: true }); mkdirSync(home)
    const file = path.join(real, 'sessions', 'rollout.jsonl'); writeFileSync(file, 'x')
    // The owned home is reached through a symlinked directory.
    const homeAlias = path.join(root, 'home-alias'); symlinkSync(home, homeAlias)
    mkdirSync(path.join(home, 'sessions'), { recursive: true })
    const aliasedFile = path.join(homeAlias, 'sessions', 'rollout.jsonl'); writeFileSync(aliasedFile, 'x')
    assert.throws(() => ownedRolloutPath({ id: 's', path: aliasedFile }, 's', home), /owned scope/)
    // A symlinked parent of the history file itself is refused too.
    const realAlias = path.join(root, 'real-alias'); symlinkSync(real, realAlias)
    const viaAlias = path.join(realAlias, 'sessions', 'rollout.jsonl')
    assert.throws(() => ownedRolloutPath({ id: 's', path: viaAlias }, 's', home, viaAlias), /ownership/)
    const elsewhere = path.join(root, 'elsewhere.jsonl'); writeFileSync(elsewhere, 'x')
    // A08: a cross-HOME binding is honoured only for this one previously bound file.
    assert.throws(() => ownedRolloutPath({ id: 's', path: elsewhere }, 's', home, file), /owned scope/)
    assert.equal(ownedRolloutPath({ id: 's', path: file }, 's', home, file), file)
    const directory = path.join(real, 'sessions')
    assert.throws(() => ownedRolloutPath({ id: 's', path: directory }, 's', home, directory), /ownership/)
  } finally { rmSync(root, { recursive: true, force: true }) }
})

// --- T1.7 / A06 / A11: the replacement order itself, before any native effect ---

test('the replacement refuses history first and only then stops, invalidates and respawns', async () => {
  const order = []
  const instance = { sessions: new Map([['s', {}]]), codexAcpClient: { codexClient: {} } }
  await assert.rejects(orchestrateCodexReplacement({ instance, sessionId: 's', order,
    capture: () => { order.push('capture'); throw new Error('Native history is not persisted') },
    stop: () => { order.push('stop') },
    start: () => { order.push('start'); return { process: peer() } } }), /not persisted/)
  assert.deepEqual(order, ['capture'])
  assert.equal(instance.sessions.has('s'), true, 'a refused history read has no effect at all')
  assert.equal(instance.codexAcpClient.ordessaDisconnected, undefined)
  assert.equal(instance.ordessaInvalidSessions, undefined)
})

test('a failed exit confirmation never starts a second native process and invalidates the old binding', async () => {
  const order = []
  const previousClient = { codexClient: {} }
  const instance = { sessions: new Map([['s', {}]]), codexAcpClient: previousClient }
  await assert.rejects(orchestrateCodexReplacement({ instance, sessionId: 's', order,
    capture: () => { order.push('capture'); return '/private/rollout.jsonl' },
    stop: () => { order.push('stop'); throw new Error('Native process exit was not confirmed') },
    start: () => { order.push('start'); return { process: peer() } } }), /exit was not confirmed/)
  assert.deepEqual(order, ['capture', 'stop'])
  assert.equal(instance.sessions.has('s'), false)
  assert.equal(previousClient.ordessaDisconnected, true)
  assert.deepEqual([...instance.ordessaInvalidSessions], ['s'])
  assert.equal(instance.codexAcpClient, previousClient, 'a failed replacement must not publish a new client')
})

test('initialization failure disposes the new native process exactly once, without retry', async () => {
  const order = []
  const instance = { sessions: new Map([['s', {}]]), codexAcpClient: { codexClient: {} } }
  const next = peer()
  let starts = 0, cleanups = 0
  await assert.rejects(orchestrateCodexReplacement({ instance, sessionId: 's', order,
    capture: () => { order.push('capture'); return '/private/rollout.jsonl' },
    stop: () => { order.push('stop') },
    start: () => { starts++; order.push('start'); return { process: next } },
    initialize: async () => { order.push('initialize'); throw new Error('synthetic startup failure') },
    cleanup: async () => { cleanups++; order.push('cleanup') } }), error => {
    assert.match(error.message, /synthetic startup failure/)
    assert.equal(error.nativeCleanupFailed, undefined)
    return true
  })
  assert.equal(starts, 1); assert.equal(cleanups, 1)
  assert.deepEqual(order, ['capture', 'stop', 'start', 'initialize', 'cleanup'])
  assert.equal(instance.sessions.has('s'), false)
  assert.equal(instance.codexAcpClient.ordessaDisconnected, true)
})

test('a cleanup failure is surfaced separately and never replaces the primary error', async () => {
  const order = []
  const instance = { sessions: new Map([['s', {}]]), codexAcpClient: { codexClient: {} } }
  await assert.rejects(orchestrateCodexReplacement({ instance, sessionId: 's', order,
    capture: () => { order.push('capture'); return '/private/rollout.jsonl' },
    stop: () => { order.push('stop') },
    start: () => { order.push('start'); return { process: peer() } },
    initialize: async () => { order.push('initialize'); throw new Error('synthetic startup failure') },
    cleanup: async () => { order.push('cleanup'); throw new Error('Native process exit was not confirmed') } }),
  error => {
    assert.match(error.message, /synthetic startup failure/)
    assert.equal(error.nativeCleanupFailed, true)
    assert.equal(error.nativeCleanupReason, 'Native process exit was not confirmed')
    return true
  })
  assert.deepEqual(order, ['capture', 'stop', 'start', 'initialize', 'cleanup'])
  assert.equal(instance.sessions.has('s'), false)
})

test('a successful replacement reports the new owner and the retired one as gone', async () => {
  const order = []
  const previousClient = { codexClient: {} }
  const instance = { sessions: new Map([['s', {}]]), codexAcpClient: previousClient }
  const fresh = { process: peer() }
  const result = await orchestrateCodexReplacement({ instance, sessionId: 's', order,
    capture: () => { order.push('capture'); return '/private/rollout.jsonl' },
    stop: () => { order.push('stop') },
    start: () => { order.push('start'); return fresh },
    initialize: async () => { order.push('initialize') } })
  assert.equal(result, fresh)
  assert.deepEqual(order, ['capture', 'stop', 'start', 'initialize'])
  assert.equal(previousClient.ordessaDisconnected, true)
  assert.equal(instance.codexAcpClient.ordessaDisconnected, true)
  assert.equal(instance.ordessaInvalidSessions.has('s'), false)
})

// --- T1.6 / A09: a native ACK is only a resume when it is the bound thread ---

test('a resume ACK is refused unless the native side really resumed the bound thread and rollout', () => {
  const rollout = '/private/rollout.jsonl'
  // The bound thread and its owned rollout: the only acceptable ACK.
  assert.deepEqual(assertResumedThread({ thread: { id: 's', path: rollout } }, 's', rollout),
    { sessionId: 's', rolloutPath: rollout })
  // A cached/other thread is not a resume of this session, whatever the model field says.
  assert.throws(() => assertResumedThread({ thread: { id: 'other', path: rollout }, model: 'm' }, 's', rollout),
    /resumed a different native thread/)
  // A transport that dropped the thread body is an unknown outcome, not a resume.
  assert.throws(() => assertResumedThread({ model: 'm' }, 's', rollout), /did not resume the bound native thread/)
  assert.throws(() => assertResumedThread(null, 's', rollout), /did not resume the bound native thread/)
  // The native side answered for a different history file than the one we own.
  assert.throws(() => assertResumedThread({ thread: { id: 's', path: '/elsewhere.jsonl' } }, 's', rollout),
    /different native rollout/)
  // No private rollout bound: nothing to compare, but the thread must still match.
  assert.deepEqual(assertResumedThread({ thread: { id: 's' } }, 's', undefined), { sessionId: 's', rolloutPath: null })
  assert.throws(() => assertResumedThread({ thread: { id: 's' } }, 's', ''), /did not resume the bound native thread/)
})
