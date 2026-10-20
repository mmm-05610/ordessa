// C-0061: one credential-free, empty-host startup diagnosis. Raw evidence stays in a 0700 tmp root.
import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { closeSync, openSync } from 'node:fs'
import { lstat, mkdtemp, readFile, readdir, writeFile, chmod, symlink } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

process.umask(0o077)
const script = fileURLToPath(import.meta.url)
const app = path.resolve(path.dirname(script), '../..')
const timeoutMs = 25_000
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms))
const privateFile = stat => stat.isFile() && !stat.isSymbolicLink() && stat.uid === process.getuid() && (stat.mode & 0o777) === 0o600
const privateDir = stat => stat.isDirectory() && !stat.isSymbolicLink() && stat.uid === process.getuid() && (stat.mode & 0o777) === 0o700
const isLoopback = line => {
  const v4 = line.match(/sin_addr=inet_addr\("([^"]+)"\)/)?.[1]
  const v6 = line.match(/inet_pton\(AF_INET6, "([^"]+)"/)?.[1]
  return !!(v4?.startsWith('127.') || v6 === '::1' || v6?.startsWith('::ffff:127.'))
}
const stopGroup = pid => { if (pid) try { process.kill(-pid, 'SIGKILL') } catch {} }
const groupGone = async pid => {
  for (let i = 0; i < 20; i++) {
    try { process.kill(-pid, 0) } catch { return true }
    await sleep(20)
  }
  return false
}

async function scanTrace(root) {
  const rows = []
  for (const name of await readdir(root)) {
    if (!/^trace\.[0-9]+$/.test(name)) continue
    const filename = path.join(root, name)
    assert.ok(privateFile(await lstat(filename)), 'TRACE_FILE_INVALID')
    for (const line of (await readFile(filename, 'utf8')).split('\n')) {
      if (!line.includes('connect(') || !/AF_INET6?/.test(line)) continue
      rows.push({ local: isLoopback(line), success: /= 0(?:\s|$)/.test(line), pending: /EINPROGRESS/.test(line) })
    }
  }
  return rows
}
async function watch(child, root, limit) {
  let reason = '', scanError = false
  const timer = setTimeout(() => { reason ||= 'TIMEOUT'; stopGroup(child.pid) }, limit)
  const interval = setInterval(() => {
    void scanTrace(root).then(rows => {
      if (!reason && rows.some(row => !row.local)) { reason = 'EGRESS_ATTEMPT_STOPPED'; stopGroup(child.pid) }
    }).catch(() => { scanError = true; reason ||= 'TRACE_INVALID'; stopGroup(child.pid) })
  }, 10)
  const code = await new Promise((resolve, reject) => { child.once('error', reject); child.once('close', resolve) })
  clearInterval(interval); clearTimeout(timer); stopGroup(child.pid)
  const stopped = await groupGone(child.pid)
  let rows = []
  try { rows = await scanTrace(root) } catch { scanError = true; reason ||= 'TRACE_INVALID' }
  if (!reason && rows.some(row => !row.local)) reason = 'EGRESS_ATTEMPT_STOPPED'
  return { reason: reason || (code === 0 ? 'NORMAL_EXIT' : 'EARLY_EXIT'), code,
    scanError, groupStopped: stopped, inet: rows.length, loopback: rows.filter(row => row.local).length,
    nonLoopback: rows.filter(row => !row.local).length,
    nonLoopbackSucceeded: rows.filter(row => !row.local && row.success).length,
    nonLoopbackPending: rows.filter(row => !row.local && row.pending).length }
}
async function inspectRoles(root) {
  const roles = new Set()
  for (const name of await readdir(root)) {
    if (!/^trace\.[0-9]+$/.test(name)) continue
    const data = await readFile(path.join(root, name), 'utf8')
    for (const line of data.split('\n')) {
      if (!line.startsWith('execve(')) continue
      roles.add(line.includes('--type=utility') ? 'utility' : line.includes('--type=renderer') ? 'renderer'
        : line.includes('--type=gpu-process') ? 'gpu' : 'main-or-other')
    }
  }
  return [...roles].sort()
}
async function inspectNetLog(root) {
  const file = path.join(root, 'netlog.json')
  try {
    assert.ok(privateFile(await lstat(file)), 'NETLOG_FILE_INVALID')
    const data = JSON.parse(await readFile(file, 'utf8'))
    const events = Array.isArray(data.events) ? data.events : []
    return { parseable: true, eventCount: events.length, sourceKinds: new Set(events.map(event => event.source?.type).filter(value => value !== undefined)).size }
  } catch { return { parseable: false, eventCount: 0, sourceKinds: 0 } }
}
function safeEnv(root) {
  const allowed = ['PATH', 'DISPLAY', 'WAYLAND_DISPLAY', 'XAUTHORITY', 'XDG_RUNTIME_DIR', 'DBUS_SESSION_BUS_ADDRESS',
    'LANG', 'LC_ALL', 'LC_CTYPE', 'TZ', 'LD_LIBRARY_PATH', 'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY',
    'http_proxy', 'https_proxy', 'all_proxy', 'NO_PROXY', 'no_proxy']
  const env = Object.fromEntries(allowed.filter(key => process.env[key] !== undefined).map(key => [key, process.env[key]]))
  for (const key of ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy', 'all_proxy']) {
    if (env[key] !== undefined) assert.ok(!/^[^:]+:\/\/[^/]*@/.test(env[key]), 'PROXY_CREDENTIALS_PRESENT')
  }
  Object.assign(env, { HOME: root, XDG_CONFIG_HOME: root, XDG_CACHE_HOME: root,
    MODULAR_USER_DATA: root, ORDESSA_EXTENSION_HOME: root, ORDESSA_EMPTY_HOST: '1', MODULAR_SMOKE: '1', ORDESSA_SMOKE_DRIVER_ID: 'smoke',
    ELECTRON_DISABLE_SECURITY_WARNINGS: 'true' })
  assert.ok(!Object.keys(env).some(key => key.includes('TOKEN') || key.includes('KEY') || key.includes('SECRET')))
  return env
}
async function selfTest() {
  const root = await mkdtemp('/tmp/hd002-c0061-synthetic-')
  assert.ok(privateDir(await lstat(root)))
  for (const name of ['netlog.json', 'stderr.log', 'trace']) {
    const fd = openSync(path.join(root, name), 'wx', 0o600); closeSync(fd)
    assert.ok(privateFile(await lstat(path.join(root, name))))
  }
  await symlink(path.join(root, 'trace'), path.join(root, 'trace.999'))
  assert.equal(privateFile(await lstat(path.join(root, 'trace.999'))), false)
  // The watcher must not run against this deliberately bad fixture file.
  const symlinkRejected = await watch(spawn(process.execPath, [script, '--fixture-timeout', root], { detached: true, stdio: 'ignore' }), root, 2000)
  assert.equal(symlinkRejected.reason, 'TRACE_INVALID')
  const egressRoot = await mkdtemp('/tmp/hd002-c0061-synthetic-')
  const egress = await watch(spawn(process.execPath, [script, '--fixture-egress', egressRoot], { detached: true, stdio: 'ignore' }), egressRoot, 2000)
  assert.equal(egress.reason, 'EGRESS_ATTEMPT_STOPPED')
  assert.equal(egress.nonLoopback, 1)
  assert.equal(egress.nonLoopbackSucceeded, 0)
  assert.equal(egress.groupStopped, true)
  const timeoutRoot = await mkdtemp('/tmp/hd002-c0061-synthetic-')
  const timeout = await watch(spawn(process.execPath, [script, '--fixture-timeout', timeoutRoot], { detached: true, stdio: 'ignore' }), timeoutRoot, 150)
  assert.equal(timeout.reason, 'TIMEOUT')
  assert.equal(timeout.groupStopped, true)
  const badRoot = await mkdtemp('/tmp/hd002-c0061-synthetic-')
  const bad = await watch(spawn(process.execPath, [script, '--fixture-badmode', badRoot], { detached: true, stdio: 'ignore' }), badRoot, 2000)
  assert.equal(bad.reason, 'TRACE_INVALID')
  assert.equal(bad.groupStopped, true)
  console.log(JSON.stringify({ selfTest: true, egressStopped: true, timeoutStopped: true, invalidTraceStopped: true }))
}
async function fixture(mode, root) {
  if (mode === 'timeout') { await sleep(3000); return }
  const file = path.join(root, `trace.${process.pid}`)
  await writeFile(file, 'connect(3, {sa_family=AF_INET, sin_port=htons(9), sin_addr=inet_addr("127.0.0.1")}, 16) = -1 ECONNREFUSED\n', { mode: 0o600, flag: 'wx' })
  if (mode === 'badmode') await chmod(file, 0o644)
  else await writeFile(file, 'connect(4, {sa_family=AF_INET, sin_port=htons(9), sin_addr=inet_addr("192.0.2.1")}, 16) = -1 EINPROGRESS\n', { flag: 'a' })
  await sleep(3000)
}
async function live() {
  assert.equal(process.argv.length, 2, 'NO_ARGUMENTS_ALLOWED')
  const root = await mkdtemp('/tmp/hd002-c0061-empty-')
  assert.ok(privateDir(await lstat(root)), 'ROOT_INVALID')
  const netlog = path.join(root, 'netlog.json'), stderr = path.join(root, 'stderr.log'), trace = path.join(root, 'trace')
  for (const file of [netlog, stderr, trace]) { const fd = openSync(file, 'wx', 0o600); closeSync(fd); assert.ok(privateFile(await lstat(file))) }
  const stderrFd = openSync(stderr, 'a', 0o600)
  const env = safeEnv(root)
  const child = spawn('strace', ['--kill-on-exit', '-ff', '-e', 'trace=execve,connect', '-o', trace,
    path.resolve(app, '../../node_modules/electron/dist/electron'), '--no-sandbox', '--disable-gpu', '--ozone-platform=x11',
    `--log-net-log=${netlog}`, '.'], { cwd: app, env, detached: true, stdio: ['ignore', stderrFd, stderrFd] })
  closeSync(stderrFd)
  const result = await watch(child, root, timeoutMs)
  const roles = await inspectRoles(root)
  const netLog = await inspectNetLog(root)
  assert.ok(privateFile(await lstat(stderr)), 'STDERR_FILE_INVALID')
  const files = (await readdir(root)).filter(name => /^trace\.[0-9]+$/.test(name))
  console.log(JSON.stringify({ diagnostic: 'C-0061', root, ...result, traceFiles: files.length, roles, netLog,
    proxyPresent: ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy', 'all_proxy'].some(key => process.env[key] !== undefined),
    serverCredentialsPresent: false }))
  if (result.scanError || !result.groupStopped || result.reason === 'TRACE_INVALID') process.exitCode = 2
}

if (process.argv[2] === '--self-test') await selfTest()
else if (process.argv[2]?.startsWith('--fixture-')) await fixture(process.argv[2].slice('--fixture-'.length), process.argv[3])
else await live()
