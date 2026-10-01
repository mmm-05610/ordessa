// Installed native Codex + installed enhanced ACP API route. No prompt/turn.
// Official native config scope is deliberately separate from the API instance.
import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { lstatSync, realpathSync, mkdtempSync, mkdirSync, rmSync, readdirSync, readFileSync } from 'node:fs'
import { createServer } from 'node:http'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { createInterface } from 'node:readline'

const allowed = new Set(['initialize', 'account/read', 'config/read', 'thread/start', 'thread/read',
  'thread/unsubscribe', 'authentication/status', 'providers/set', 'session/new', 'session/close',
  'session/set_config_option', '_ordessa/session/configuration', '_ordessa/channel/configuration/prepare'])

class Peer {
  constructor(command, args, env) {
    this.child = spawn(command, args, { env, stdio: ['pipe', 'pipe', 'ignore'], detached: true })
    this.pending = new Map(); this.next = 0
    this.lines = createInterface({ input: this.child.stdout })
    this.lines.on('line', line => {
      if (Buffer.byteLength(line) > 1024 * 1024) { this.fail(); return }
      let message
      try { message = JSON.parse(line) } catch { this.fail(); return }
      if (message.method && Object.hasOwn(message, 'id')) {
        this.child.stdin.write(JSON.stringify({ jsonrpc: '2.0', id: message.id,
          error: { code: -32601, message: 'No client operations in no-model probe' } }) + '\n')
      } else if (this.pending.has(message.id)) {
        const slot = this.pending.get(message.id); this.pending.delete(message.id)
        clearTimeout(slot.timer)
        message.error ? slot.reject(new Error('native-request-rejected')) : slot.resolve(message.result)
      }
    })
    this.child.on('error', () => this.fail())
    this.child.on('exit', () => this.fail())
  }
  fail() {
    for (const slot of this.pending.values()) { clearTimeout(slot.timer); slot.reject(new Error('native-peer-unavailable')) }
    this.pending.clear()
  }
  notify(method) { this.child.stdin.write(JSON.stringify({ method, params: {} }) + '\n') }
  request(method, params) {
    if (!allowed.has(method)) throw new Error('effect-method-forbidden')
    return new Promise((resolve, reject) => {
      const id = ++this.next
      const timer = setTimeout(() => { this.pending.delete(id); reject(new Error('native-request-timeout')) }, 20000)
      this.pending.set(id, { resolve, reject, timer })
      this.child.stdin.write(JSON.stringify({ jsonrpc: '2.0', id, method, params }) + '\n')
    })
  }
  async close() {
    this.fail(); this.lines.close()
    // Only the group created by this probe. Never a user service.
    try { process.kill(-this.child.pid, 'SIGTERM') } catch {}
    if (this.child.exitCode === null && this.child.signalCode === null) await new Promise(resolve => {
      const timer = setTimeout(() => { try { process.kill(-this.child.pid, 'SIGKILL') } catch {} }, 3000)
      this.child.once('exit', () => { clearTimeout(timer); resolve() })
    })
    this.child.stdin.destroy()
  }
}

function privateDirectory(directory) {
  if (!directory || !path.isAbsolute(directory) || realpathSync(directory) !== directory) throw new Error('unsafe-scope')
  const info = lstatSync(directory)
  if (!info.isDirectory() || info.isSymbolicLink() || info.uid !== process.getuid() || info.mode & 0o077)
    throw new Error('unsafe-scope')
  return directory
}

function environment(instance, nativeHome) {
  const result = { ...process.env, HOME: instance, CODEX_HOME: nativeHome,
    XDG_CONFIG_HOME: instance, ORDESSA_NATIVE_INSTANCE_DIR: instance, NO_COLOR: '1' }
  for (const key of ['CODEX_API_KEY', 'OPENAI_API_KEY', 'CODEX_ACCESS_TOKEN', 'CODEX_AUTH_TOKEN',
    'DEFAULT_AUTH_REQUEST', 'CODEX_CONFIG', 'MODEL_PROVIDER', 'CODEX_PATH']) delete result[key]
  return result
}

function containsFixtureSecret(directory, secret) {
  for (const item of readdirSync(directory, { withFileTypes: true })) {
    const target = path.join(directory, item.name)
    if (item.isDirectory() && containsFixtureSecret(target, secret)) return true
    if (item.isFile() && readFileSync(target).includes(secret)) return true
  }
  return false
}

const assets = process.argv[2]
const account = privateDirectory(process.argv[3])
if (!assets || !path.isAbsolute(assets) || realpathSync(assets) !== assets) throw new Error('unsafe-assets')
const native = path.join(assets, 'codex-runtime/node_modules/@openai/codex-linux-x64/vendor/x86_64-unknown-linux-musl/bin/codex')
const entry = path.join(assets, 'codex-runtime/node_modules/@agentclientprotocol/codex-acp/dist/ordessa-profile.mjs')
const temporary = mkdtempSync(path.join(tmpdir(), 'ordessa-codex-mixed-'))
const officialHome = path.join(temporary, 'official-instance')
const apiHome = path.join(temporary, 'api-instance')
const project = path.join(temporary, 'project')
for (const directory of [officialHome, apiHome, project]) mkdirSync(directory, { mode: 0o700 })
let official, api, threadId, sessionId, phase = 'startup'
let httpRequests = 0, inferenceRequests = 0
const provider = createServer((request, response) => {
  httpRequests++
  if (/\/(responses|chat\/completions)(?:\?|$)/u.test(request.url)) inferenceRequests++
  response.writeHead(403, { 'content-type': 'application/json' })
  response.end('{"error":"no-model-probe"}')
})
let report
try {
  await new Promise(resolve => provider.listen(0, '127.0.0.1', resolve))
  const endpoint = 'http://127.0.0.1:' + provider.address().port
  official = new Peer(native, ['-c', 'cli_auth_credentials_store="keyring"',
    '-c', 'model_reasoning_effort="low"', 'app-server'], environment(officialHome, account))
  const apiEnvironment = environment(apiHome, apiHome)
  apiEnvironment.CODEX_CONFIG = JSON.stringify({ model_reasoning_effort: 'high' })
  api = new Peer(process.execPath, [entry], apiEnvironment)
  phase = 'initialize'
  await Promise.all([
    official.request('initialize', { clientInfo: { name: 'ordessa-mixed-auth-probe', version: '1' },
      capabilities: { experimentalApi: false } }),
    api.request('initialize', { protocolVersion: 1, clientCapabilities: {},
      clientInfo: { name: 'ordessa-mixed-auth-probe', version: '1' } }),
  ])
  official.notify('initialized')
  phase = 'authentication-before'
  const before = await official.request('account/read', { refreshToken: false })
  assert.equal(before.account?.type, 'chatgpt')
  assert.equal((await api.request('authentication/status', {})).type, 'unauthenticated')
  phase = 'official-native-thread'
  const officialThread = await official.request('thread/start', { cwd: project, model: 'gpt-5.5',
    modelProvider: 'openai', config: { model_reasoning_effort: 'low' }, ephemeral: true,
    approvalPolicy: 'never', sandbox: 'read-only' })
  threadId = officialThread.thread.id
  assert.equal(officialThread.modelProvider, 'openai')
  assert.equal(officialThread.reasoningEffort, 'low')
  phase = 'api-native-thread'
  const fixtureSecret = 'ordessa-mixed-synthetic-not-a-real-key'
  const configured = await api.request('_ordessa/channel/configuration/prepare', {
    operationId: 'create:mixed-auth-probe', model: 'gpt-5.5', provider: {
      providerId: 'custom-gateway', apiType: 'openai', baseUrl: endpoint,
      headers: { authorization: 'Bearer ' + fixtureSecret } } })
  assert.equal(configured.state, 'prepared')
  sessionId = (await api.request('session/new', { cwd: project, mcpServers: [] })).sessionId
  assert.equal(typeof sessionId, 'string')
  const readApi = () => api.request('_ordessa/session/configuration', { sessionId })
  const apiBefore = await readApi()
  const select = (state, id) => state.configOptions.find(item => item.id === id)
  const flatten = options => options.flatMap(item => [item, ...flatten(item.options ?? [])])
  const chosen = flatten(select(apiBefore, 'model').options).find(item => item.value === 'gpt-5.5')
  assert.equal(chosen?._meta?.ordessaModel?.provider, 'custom-gateway')
  assert.equal(chosen?._meta?.ordessaModel?.baseUrl, endpoint)
  assert.equal(select(apiBefore, 'reasoning_effort').currentValue, 'high')
  assert.equal((await api.request('authentication/status', {})).type, 'gateway')
  phase = 'api-local-change'
  await api.request('session/set_config_option', { sessionId, configId: 'reasoning_effort', value: 'medium' })
  const apiAfter = await readApi()
  assert.equal(select(apiAfter, 'reasoning_effort').currentValue, 'medium')
  assert.equal(apiAfter.generation, apiBefore.generation)
  const officialConfig = await official.request('config/read', { includeLayers: false })
  assert.equal(officialConfig.config.model_reasoning_effort, 'low')
  const officialRead = await official.request('thread/read', { threadId, includeTurns: false })
  assert.equal(officialRead.thread.modelProvider, 'openai')
  phase = 'authentication-after'
  const after = await official.request('account/read', { refreshToken: false })
  assert.deepEqual(after.account, before.account)
  assert.equal((await api.request('authentication/status', {})).type, 'gateway')
  assert.equal(httpRequests, 0)
  assert.equal(inferenceRequests, 0)
  phase = 'owned-cleanup'
  await api.request('session/close', { sessionId }); sessionId = null
  await official.request('thread/unsubscribe', { threadId }); threadId = null
  await api.close(); api = null
  assert.equal(containsFixtureSecret(apiHome, Buffer.from(fixtureSecret)), false)
  report = { scope: 'installed-native-official-and-installed-acp-api-no-model',
    officialAccountUnchanged: true, apiUnauthenticatedBeforeInjection: true,
    apiGatewayWithoutOfficialLogin: true, officialNativeProvider: 'openai', apiNativeProvider: 'custom-gateway',
    nativeConfigurationIndependent: true, apiConfigurationChangeDidNotChangeOfficial: true,
    apiCredentialPersisted: false, modelCalls: 0, providerHttpRequests: httpRequests,
    desktopProfileIntegrationVerified: false }
} catch {
  report = { scope: 'installed-native-official-and-installed-acp-api-no-model',
    state: 'failed', phase, modelCalls: 0 }
  process.exitCode = 1
} finally {
  if (api && sessionId) try { await api.request('session/close', { sessionId }) } catch {}
  if (official && threadId) try { await official.request('thread/unsubscribe', { threadId }) } catch {}
  await Promise.all([api?.close(), official?.close()])
  if (provider.listening) await new Promise(resolve => provider.close(resolve))
  // All paths below were allocated by this invocation, not user data.
  rmSync(temporary, { recursive: true, force: true })
}
console.log(JSON.stringify(report))
