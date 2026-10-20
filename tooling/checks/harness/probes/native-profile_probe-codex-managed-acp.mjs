// Candidate ACP boundary; optional empty native creation, never inference.
import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { mkdtempSync, mkdirSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { createInterface } from 'node:readline'

const allowed = new Set(['initialize', 'authentication/status', 'authenticate', 'logout', 'authentication/logout',
  'providers/set', 'providers/disable', '_ordessa/channel/configuration/prepare',
  '_ordessa/channel/configuration/operation', 'session/new', 'session/close'])
class Peer {
  constructor(entry, env) {
    this.child = spawn(process.execPath, [entry], { env, detached: true, stdio: ['pipe', 'pipe', 'ignore'] })
    this.next = 0; this.pending = new Map()
    this.lines = createInterface({ input: this.child.stdout })
    this.lines.on('line', line => {
      if (Buffer.byteLength(line) > 1024 * 1024) { this.fail(); return }
      let message
      try { message = JSON.parse(line) } catch { this.fail(); return }
      if (message.method && Object.hasOwn(message, 'id')) {
        this.child.stdin.write(JSON.stringify({ jsonrpc: '2.0', id: message.id,
          error: { code: -32601, message: 'Client effects forbidden' } }) + '\n')
      } else if (this.pending.has(message.id)) {
        const slot = this.pending.get(message.id); this.pending.delete(message.id)
        clearTimeout(slot.timer); slot.resolve(message)
      }
    })
    this.child.on('error', () => this.fail()); this.child.on('exit', () => this.fail())
  }
  fail() {
    for (const slot of this.pending.values()) { clearTimeout(slot.timer); slot.reject(new Error('ACP unavailable')) }
    this.pending.clear()
  }
  request(method, params) {
    if (!allowed.has(method)) throw new Error('Probe method forbidden')
    return new Promise((resolve, reject) => {
      const id = ++this.next
      const timer = setTimeout(() => { this.pending.delete(id); reject(new Error('ACP timeout')) }, 20000)
      this.pending.set(id, { resolve, reject, timer })
      this.child.stdin.write(JSON.stringify({ jsonrpc: '2.0', id, method, params }) + '\n')
    })
  }
  async close() {
    this.fail(); this.lines.close()
    try { process.kill(-this.child.pid, 'SIGTERM') } catch {}
    if (this.child.exitCode === null && this.child.signalCode === null) await new Promise(resolve => {
      const timer = setTimeout(() => { try { process.kill(-this.child.pid, 'SIGKILL') } catch {} }, 3000)
      this.child.once('exit', () => { clearTimeout(timer); resolve() })
    })
    this.child.stdin.destroy()
  }
}

const [entry, account, mode] = process.argv.slice(2)
if (mode !== undefined && mode !== '--initial-no-model') throw new Error('Unknown probe mode')
if (!entry || !account || !path.isAbsolute(entry) || !path.isAbsolute(account)) throw new Error('Explicit paths required')
const root = mkdtempSync(path.join(tmpdir(), 'ordessa-managed-acp-'))
let official, api
try {
  function environment(name, managed) {
    const instance = path.join(root, name); mkdirSync(instance, { mode: 0o700 })
    const env = { ...process.env, ORDESSA_NATIVE_INSTANCE_DIR: instance }
    for (const key of ['ORDESSA_CODEX_MANAGED_ACCOUNT_DIR', 'CODEX_PATH', 'CODEX_CONFIG', 'DEFAULT_AUTH_REQUEST',
      'MODEL_PROVIDER', 'CODEX_API_KEY', 'OPENAI_API_KEY', 'CODEX_ACCESS_TOKEN', 'CODEX_AUTH_TOKEN']) delete env[key]
    if (managed) env.ORDESSA_CODEX_MANAGED_ACCOUNT_DIR = account
    return env
  }
  official = new Peer(entry, environment('official', true))
  api = new Peer(entry, environment('api', false))
  const initialized = await Promise.all([official, api].map(p => p.request('initialize', {
    protocolVersion: 1, clientCapabilities: {}, clientInfo: { name: 'ordessa-auth-boundary-probe', version: '1' } })))
  assert.ok(initialized.every(r => !r.error))
  const before = await official.request('authentication/status', {})
  assert.equal(before.result?.type, 'chat-gpt')
  const privateStatus = await api.request('authentication/status', {})
  assert.equal(privateStatus.result?.type, 'unauthenticated')
  assert.ok((await official.request('authenticate', { methodId: 'api-key',
    _meta: { 'api-key': { apiKey: 'synthetic-never-applied' } } })).error)
  assert.ok((await official.request('logout', {})).error)
  assert.ok((await official.request('authentication/logout', {})).error)
  assert.ok((await official.request('providers/set', {providerId: 'custom-gateway', apiType: 'openai',
    baseUrl: 'http://127.0.0.1:1'})).error)
  assert.ok((await official.request('providers/disable', {providerId: 'custom-gateway'})).error)
  let initialConfigurationObserved = false
  if (mode === '--initial-no-model') {
    const operationId = 'create:managed-boundary-probe'
    const prepared = await official.request('_ordessa/channel/configuration/prepare', {
      operationId, provider: {providerId: 'openai', authentication: 'managed-account'}, model: 'gpt-5.5'})
    assert.equal(prepared.result?.state, 'prepared', 'Official preparation failed')
    const project = path.join(root, 'project'); mkdirSync(project, {mode: 0o700})
    const created = await official.request('session/new', {cwd: project, mcpServers: []})
    assert.ok(!created.error && created.result?.sessionId, 'Official native creation failed')
    const observed = await official.request('_ordessa/channel/configuration/operation', {operationId})
    assert.equal(observed.result?.state, 'observed', 'Official configuration readback failed')
    const selected = observed.result.after.configOptions.find(option => option.id === 'model')
    assert.equal(selected.currentValue, 'gpt-5.5')
    assert.ok(!(await official.request('session/close', {sessionId: created.result.sessionId})).error)
    initialConfigurationObserved = true
  }
  const after = await official.request('authentication/status', {})
  assert.deepEqual(after.result, before.result)
  process.stdout.write(JSON.stringify({ officialAcpLoggedIn: true, apiAcpHasNoAccount: true,
    sessionAccountMutationRejected: true, accountUnchanged: true, initialConfigurationObserved,
    modelCalls: 0, sessionCreations: initialConfigurationObserved ? 1 : 0 }) + '\n')
} finally {
  await Promise.all([official?.close(), api?.close()])
  rmSync(root, { recursive: true, force: true })
}
