import { spawn } from 'node:child_process'
import { mkdtempSync, mkdirSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { createInterface } from 'node:readline'
import { createServer } from 'node:http'
import { configurationDigest } from '../pi-profile/configuration-query.mjs'

// Default: registration only. --restore-no-model uses an isolated synthetic
// provider and one empty native session; it never permits inference or prompt.
const root = process.argv[2]
const restoreProbe = process.argv.includes('--restore-no-model')
const initialProbe = process.argv.includes('--initial-no-model')
if (restoreProbe && initialProbe) throw new Error('Creation and restoration are separate probes')
const selectedBrand = process.argv.find(arg => arg.startsWith('--brand='))?.slice(8)
if (selectedBrand && !['codex', 'claude-code'].includes(selectedBrand)) throw new Error('Unknown probe brand')
if (!root || !path.isAbsolute(root)) throw new Error('Expected absolute candidate asset root')
for (const [brand, relative] of [
  ['codex', 'codex-runtime/node_modules/@agentclientprotocol/codex-acp/dist/index.js'],
  ['claude-code', 'claude-runtime/node_modules/@agentclientprotocol/claude-agent-acp/dist/index.js'],
]) {
  if (selectedBrand && brand !== selectedBrand) continue
  const home = mkdtempSync(path.join(tmpdir(), 'ordessa-native-registration-'))
  const instance = path.join(home, 'instance'); mkdirSync(instance, { mode: 0o700 })
  let providerServer, providerEndpoint, attemptedModelRequests = 0
  if (restoreProbe || initialProbe) {
    providerServer = createServer((request, response) => {
      if (/\/(responses|messages|chat\/completions)(?:\?|$)/u.test(request.url)) attemptedModelRequests++
      response.writeHead(403, { 'content-type': 'application/json' })
      response.end(JSON.stringify({ error: 'No-model probe does not offer inference' }))
    })
    await new Promise(resolve => providerServer.listen(0, '127.0.0.1', resolve))
    providerEndpoint = 'http://127.0.0.1:' + providerServer.address().port
  }
  const child = spawn(process.execPath, [path.join(root, relative)], {
    env: { PATH: process.env.PATH, HOME: home, CODEX_HOME: instance,
      CLAUDE_CONFIG_DIR: instance, XDG_CONFIG_HOME: instance, NO_COLOR: '1' },
    stdio: ['pipe', 'pipe', 'pipe'], detached: true,
  })
  let next = 0
  const pending = new Map()
  const lines = createInterface({ input: child.stdout })
  lines.on('line', line => {
    let reply
    try { reply = JSON.parse(line) } catch { return }
    if (reply.method && reply.id != null) {
      child.stdin.write(JSON.stringify({ jsonrpc: '2.0', id: reply.id,
        error: { code: -32601, message: 'Probe does not provide client operations' } }) + '\n')
    } else if (pending.has(reply.id)) { pending.get(reply.id)(reply); pending.delete(reply.id) }
  })
  const diagnosticCodes = new Set()
  child.stderr.on('data', chunk => {
    // Retain only fixed OS failure codes, never upstream diagnostic text.
    for (const code of ['ENOENT', 'EACCES', 'ENAMETOOLONG', 'EDQUOT', 'ENOSPC', 'SyntaxError'])
      if (chunk.toString().includes(code)) diagnosticCodes.add(code)
  })
  const request = (method, params) => new Promise((resolve, reject) => {
    const id = ++next
    const timer = setTimeout(() => { pending.delete(id); reject(new Error(`${brand} registration request timed out: ${method}; exit=${child.exitCode}; codes=${[...diagnosticCodes].join(',')}`)) }, 20000)
    pending.set(id, reply => { clearTimeout(timer); resolve(reply) })
    child.stdin.write(JSON.stringify({ jsonrpc: '2.0', id, method, params }) + '\n')
  })
  try {
    const initialized = await request('initialize', { protocolVersion: 1, clientCapabilities: {},
      clientInfo: { name: 'ordessa-no-model-registration', version: '1' } })
    if (initialized.error) throw new Error(`${brand} initialize refused: ${initialized.error.code}`)
    if (initialized.result?._meta?.ordessaConfiguration?.version !== 1)
      throw new Error(`${brand} did not declare configuration evidence version`)
    const reply = await request('_ordessa/session/configuration', { sessionId: 'not-created-by-probe' })
    if (!reply.error || reply.error.code === -32601
        || !JSON.stringify(reply.error).includes('Session is not live'))
      throw new Error(`${brand} evidence request did not reach the live-instance reader`)
    const malformedRestore = await request('_ordessa/session/configuration/restore', { sessionId: 'not-created-by-probe' })
    if (malformedRestore.error?.code !== -32602) throw new Error(`${brand} restoration parser is not registered`)
    if (restoreProbe || initialProbe) {
      const provider = { providerId: brand === 'codex' ? 'custom-gateway' : 'main',
        apiType: brand === 'codex' ? 'openai' : 'anthropic', baseUrl: providerEndpoint,
        headers: { authorization: 'Bearer ordessa-synthetic-no-model-key' } }
      const initialModel = process.argv.find(arg => arg.startsWith('--model='))?.slice(8)
        ?? (brand === 'codex' ? 'gpt-5.5' : 'sonnet')
      const initialInput = { operationId: 'create:registration-probe', model: initialModel, provider }
      const configured = initialProbe
        ? await request('_ordessa/channel/configuration/prepare', initialInput)
        : await request('providers/set', provider)
      if (configured.error) throw new Error(`${brand} synthetic provider setup refused: ${configured.error.code}`)
      if (initialProbe && configured.result?.state !== 'prepared') throw new Error(`${brand} initial configuration not prepared`)
      const created = await request('session/new', { cwd: home, mcpServers: [] })
      if (created.error || typeof created.result?.sessionId !== 'string') {
        const detail = JSON.stringify(created.error ?? {})
        const reason = /readback differs/iu.test(detail) ? 'initial-model-readback-mismatch'
          : /model/iu.test(detail) ? 'native-model-rejected'
            : /config/iu.test(detail) ? 'native-configuration-rejected' : 'native-creation-rejected'
        const runtimeFault = ['is not a function', 'not iterable', 'Cannot read properties', 'undefined', 'permission']
          .filter(term => detail.includes(term)).join(',')
        // Only this probe's isolated HOME/synthetic provider are in scope.
        // Public model/phase fields are safe; never expose upstream error text.
        const retained = initialProbe ? await request('_ordessa/channel/configuration/operation',
          { operationId: initialInput.operationId }) : null
        const actualModel = retained?.result?.after?.configOptions?.find(item => item.id === 'model')?.currentValue
        const values = retained?.result?.after?.configOptions?.find(item => item.id === 'model')?.options
          ?.flatMap(item => item.options ?? [item]).map(item => item.value)
        throw new Error(`${brand} no-model native creation refused: ${created.error?.code} (${reason}; ${runtimeFault}); phase=${retained?.result?.phase}; model=${JSON.stringify(actualModel)}; options=${JSON.stringify(values)}`)
      }
      const sessionId = created.result.sessionId
      const observed = await request('_ordessa/session/configuration', { sessionId })
      if (observed.error) throw new Error(`${brand} independent query refused`)
      const model = observed.result.configOptions.find(item => item.id === 'model')?.currentValue
      if (typeof model !== 'string') throw new Error(`${brand} has no native model observation`)
      if (initialProbe) {
        const retained = await request('_ordessa/channel/configuration/operation', { operationId: initialInput.operationId })
        if (retained.error || retained.result.state !== 'observed' || model !== initialModel
            || retained.result.after.generation !== observed.result.generation)
          throw new Error(`${brand} independent initial model differs`)
        if (attemptedModelRequests !== 0) throw new Error(`${brand} attempted an inference request`)
        await request('session/close', { sessionId })
        console.log(JSON.stringify({ brand, providerConfiguredBeforeCreation: true, modelConfiguredBeforeReturn: true,
          independentModelReadback: true, sessionNew: 1, resume: 0, prompt: 0, inferenceRequests: 0,
          scope: 'native-adapter-initial-model-not-server-profile' }))
        continue
      }
      const restoreInput = { sessionId, operationId: 'restore:registration-probe',
        expectedGeneration: observed.result.generation, expectedConfigDigest: configurationDigest(observed.result),
        model, provider: { ...provider, baseUrl: providerEndpoint + '/restored' },
        target: { server_id: 'controlled-probe', session_id: 'controlled-canonical',
          channel_id: 'controlled-channel', runtime_generation: 1 } }
      const restored = await request('_ordessa/session/configuration/restore', restoreInput)
      if (restored.error || restored.result?.state !== 'observed')
        throw new Error(`${brand} native restoration unconfirmed: ${restored.error?.code ?? restored.result?.phase} (${restored.result?.failureStep ?? 'readback'} / ${restored.result?.failureReason ?? 'unclassified'})`)
      const after = await request('_ordessa/session/configuration', { sessionId })
      if (after.error || after.result.generation !== restored.result.after.generation
          || after.result.generation === observed.result.generation)
        throw new Error(`${brand} independent restored generation mismatch`)
      const replay = await request('_ordessa/session/configuration/restore', restoreInput)
      if (JSON.stringify(replay.result) !== JSON.stringify(restored.result)) throw new Error(`${brand} restore replay differs`)
      if (attemptedModelRequests !== 0) throw new Error(`${brand} attempted an inference request`)
      await request('session/close', { sessionId })
      console.log(JSON.stringify({ brand, providerRestored: true, conversationIdentityPreserved: true,
        generationChanged: true, independentReadback: true, idempotentReplay: true, sessionNew: 1,
        prompt: 0, inferenceRequests: 0, scope: 'native-adapter-controlled-provider-not-server-profile' }))
      continue
    }
    console.log(JSON.stringify({ brand, initialize: true, liveReaderRegistered: true,
      unknownSessionRejected: true, sessionNew: 0, prompt: 0, scope: 'registration-only' }))
  } finally {
    lines.close()
    child.stdin.end()
    // This process group was created by this probe, not a user-facing service.
    try { process.kill(-child.pid, 'SIGTERM') } catch {}
    await new Promise(resolve => {
      if (child.exitCode !== null || child.signalCode !== null) return resolve()
      const timer = setTimeout(() => { try { process.kill(-child.pid, 'SIGKILL') } catch {} }, 5000)
      child.once('exit', () => { clearTimeout(timer); resolve() })
    })
    if (providerServer) await new Promise(resolve => providerServer.close(resolve))
  }
}
