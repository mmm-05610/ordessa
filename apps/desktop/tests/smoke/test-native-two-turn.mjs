// HD-002: one bounded, non-sensitive FE first send and second turn on a private Server.
import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { lstat, mkdir, readFile, readdir, rename, writeFile } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

process.umask(0o077)
const app = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')
const readyPath = path.resolve(process.argv[2] ?? '')
const pairRoot = path.dirname(readyPath)
const donePath = path.join(pairRoot, 'fc-done.json')
const userData = path.join(pairRoot, 'electron-userdata')
const traceBase = path.join(userData, 'electron-connect.trace')
const netLogPath = path.join(userData, 'electron-netlog.json')
const logPath = path.join(userData, 'electron-smoke.log')
const timeoutMs = 210_000

function secureFile(info) {
  assert.ok(info.isFile() && !info.isSymbolicLink() && info.uid === process.getuid() && (info.mode & 0o777) === 0o600)
}
function secureDir(info) {
  assert.ok(info.isDirectory() && !info.isSymbolicLink() && info.uid === process.getuid() && (info.mode & 0o777) === 0o700)
}
function nativeSummary(result) {
  const pair = result?.nativePair
  assert.equal(result?.ready, true)
  assert.equal(result?.nodeAbsent, true)
  assert.deepEqual(result?.errors, [])
  for (const field of ['oneServer', 'connectionIdMatches', 'connected', 'listed', 'selected',
    'draftVisible', 'projectGateOpen', 'emptyComposerCannotSend', 'directConnectorsAbsent', 'errorsAbsent']) {
    assert.equal(pair?.[field], true, `Native pair UI check failed: ${field}`)
  }
  return Object.fromEntries(Object.entries(pair).filter(([, value]) => typeof value === 'boolean'))
}
async function recordedNetwork() {
  secureFile(await lstat(netLogPath))
  const netlog = JSON.parse(await readFile(netLogPath, 'utf8'))
  let traceFiles = 0
  for (const name of await readdir(userData)) {
    if (!/^electron-connect\.trace\.\d+$/.test(name)) continue
    const file = path.join(userData, name)
    secureFile(await lstat(file))
    traceFiles++
  }
  assert.ok(traceFiles > 0 && Array.isArray(netlog.events), 'Network record incomplete')
  return { traceFiles, netlogEvents: netlog.events.length }
}
async function markStopped(sendCount, result) {
  const staging = `${donePath}.${process.pid}.tmp`
  await writeFile(staging, JSON.stringify({ schema: 'hd002-fe-send/1', done: true, electronStopped: true,
    sendCount, result }), { mode: 0o600, flag: 'wx' })
  await rename(staging, donePath)
}

let readyAccepted = false
let child
let output = ''
let pass = false
try {
  assert.equal(process.argv[2], readyPath, 'Expected an absolute normalized ready.json path')
  assert.equal(path.basename(readyPath), 'ready.json')
  assert.equal(path.dirname(pairRoot), '/tmp')
  assert.match(path.basename(pairRoot), /^hd002-fe-send-[A-Za-z0-9_-]+$/)
  secureDir(await lstat(pairRoot))
  secureFile(await lstat(readyPath))
  const ready = JSON.parse(await readFile(readyPath, 'utf8'))
  assert.equal(ready.schema, 'hd002-fe-send/1')
  const origin = typeof ready.origin === 'string' ? ready.origin.match(/^http:\/\/127\.0\.0\.1:([1-9][0-9]{0,4})$/) : null
  assert.ok(origin && Number(origin[1]) <= 65535, 'Expected this batch exact loopback HTTP origin')
  assert.equal(ready.tokenFile, path.join(pairRoot, 'data/secrets/http-token'))
  assert.ok(typeof ready.serverId === 'string' && ready.serverId.length > 0)
  assert.deepEqual(ready.nativeExecution && { mode: ready.nativeExecution.mode, harness: ready.nativeExecution.harness },
    { mode: 'native', harness: 'pi' })
  assert.ok(typeof ready.nativeExecution.profileId === 'string' && ready.nativeExecution.profileId.length > 0)
  assert.equal(ready.bcProfileUniqueReady, true)
  assert.equal(ready.sendAllowed, true)
  assert.equal(ready.maxSendCount, 2)
  assert.equal(ready.project?.normalizedPath, path.join(pairRoot, 'project'))
  assert.ok(typeof ready.project.workspaceId === 'string' && ready.project.workspaceId.length > 0)
  const electronVersion = '40.10.2' // Reviewed Chromium 144.0.7559.236 dictionary request source.
  const electronPackage = JSON.parse(await readFile(path.resolve(app, '../../node_modules/electron/package.json'), 'utf8'))
  const lock = JSON.parse(await readFile(path.resolve(app, '../../package-lock.json'), 'utf8'))
  assert.equal(electronPackage.version, electronVersion, 'Expected the reviewed Electron build')
  assert.equal(lock.packages?.['node_modules/electron']?.version, electronVersion)
  secureFile(await lstat(ready.tokenFile)) // metadata only; native main opens and reads it.
  await mkdir(userData, { mode: 0o700 })
  secureDir(await lstat(userData))
  await writeFile(netLogPath, '', { mode: 0o600, flag: 'wx' })
  secureFile(await lstat(netLogPath))
  readyAccepted = true

  const allowed = ['PATH', 'DISPLAY', 'WAYLAND_DISPLAY', 'XAUTHORITY', 'XDG_RUNTIME_DIR', 'DBUS_SESSION_BUS_ADDRESS',
    'LANG', 'LC_ALL', 'LC_CTYPE', 'TZ', 'LD_LIBRARY_PATH', 'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY',
    'http_proxy', 'https_proxy', 'all_proxy', 'NO_PROXY', 'no_proxy']
  const env = Object.fromEntries(allowed.filter(key => process.env[key] !== undefined).map(key => [key, process.env[key]]))
  for (const key of ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy', 'all_proxy']) {
    if (env[key] !== undefined) assert.ok(!/^[^:]+:\/\/[^/]*@/.test(env[key]), 'PROXY_CREDENTIALS_PRESENT')
  }
  Object.assign(env, {
    HOME: userData, XDG_CONFIG_HOME: userData, XDG_CACHE_HOME: userData,
    MODULAR_USER_DATA: userData, ORDESSA_EXTENSION_HOME: userData, ORDESSA_EMPTY_HOST: '0',
    MODULAR_SMOKE: '1', ORDESSA_SMOKE_DRIVER_ID: 'smoke', MODULAR_NATIVE_PAIR_SMOKE: '1', MODULAR_FE_TWO_TURN_SMOKE: '1', ELECTRON_DISABLE_SECURITY_WARNINGS: 'true',
    ORDESSA_SERVER_ORIGIN: ready.origin, ORDESSA_SERVER_TOKEN_FILE: ready.tokenFile,
    ORDESSA_PAIR_SERVER_ID: ready.serverId, ORDESSA_PAIR_PROJECT_PATH: ready.project.normalizedPath,
  })
  child = spawn('strace', ['--kill-on-exit', '-ff', '-ttt', '-e',
    'trace=clone,clone3,fork,vfork,execve,socket,connect,getsockname,close,sendto,sendmsg,sendmmsg',
    '-e', 'raw=sendto,sendmsg,sendmmsg', '-o', traceBase,
    path.resolve(app, '../../node_modules/electron/dist/electron'),
    '--no-sandbox', '--disable-gpu', '--ozone-platform=x11', `--log-net-log=${netLogPath}`, '.'],
  { cwd: app, env, detached: true, stdio: ['ignore', 'pipe', 'pipe'] })
  for (const stream of [child.stdout, child.stderr]) stream.on('data', chunk => {
    output = (output + chunk.toString()).slice(-1_000_000)
  })
  let timedOut = false
  const timer = setTimeout(() => { timedOut = true; try { process.kill(-child.pid, 'SIGKILL') } catch {} }, timeoutMs)
  let code
  try {
    code = await new Promise((resolve, reject) => { child.once('error', reject); child.once('close', resolve) })
  } finally { clearTimeout(timer); try { process.kill(-child.pid, 'SIGKILL') } catch {} }
  await writeFile(logPath, output, { mode: 0o600, flag: 'wx' })
  assert.equal(timedOut, false, 'Electron two-turn gate timed out')
  assert.equal(code, 0, 'Electron two-turn gate exited unsuccessfully')
  const line = output.split('\n').find(item => item.startsWith('MODULAR_LOADER_READY '))
  assert.ok(line, 'Electron two-turn result missing')
  const result = JSON.parse(line.slice('MODULAR_LOADER_READY '.length))
  const checks = nativeSummary(result)
  for (const field of ['firstStarted', 'firstOpened', 'firstReply', 'secondStarted', 'secondReply',
    'stillSession', 'errorsAbsent']) assert.equal(result.twoTurn?.[field], true, `FE two-turn check failed: ${field}`)
  assert.equal(result.twoTurn?.attemptedSends, 2)
  const networkRecord = await recordedNetwork().catch(() => ({ complete: false }))
  pass = true
  console.log(JSON.stringify({ gate: 'HD002_FE_TWO_TURN', pass, checks, twoTurn: result.twoTurn, networkRecord }))
} catch (error) {
  console.error(JSON.stringify({ gate: 'HD002_FE_TWO_TURN', pass: false, reason: error instanceof Error ? error.message : 'unknown error' }))
  process.exitCode = 1
} finally {
  if (child?.pid) { try { process.kill(-child.pid, 'SIGKILL') } catch {} }
  if (readyAccepted) {
    const sendCount = Number(output.includes('HD002_FE_ATTEMPT_1')) + Number(output.includes('HD002_FE_ATTEMPT_2'))
    try { await markStopped(sendCount, pass ? 'PASS' : 'FAIL') }
    catch { console.error(JSON.stringify({ gate: 'HD002_FE_TWO_TURN', doneMarker: false })); process.exitCode = 1 }
  }
}
