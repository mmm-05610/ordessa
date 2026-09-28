/** PC-10 controlled probe: does the pinned official Claude ACP adapter
 * (agent-box-harness-runtime-claude closure, `@agentclientprotocol/claude-agent-acp`
 * 0.81.2) announce a native command catalog (`available_commands_update`)?
 *
 * Architecture mirrors plugins/harness/packaging/claude/provider-routing-smoke.mjs
 * (read-only reference): a loopback fake Anthropic API, a throwaway
 * CLAUDE_CONFIG_DIR, a fake token — zero real models, zero real credentials,
 * zero plugins/harness tracked-file changes (the closure is consumed as
 * installed node_modules). Every inbound ACP frame is recorded, so the
 * conclusion (announced / not announced) carries first-hand evidence either way.
 *
 * Run: node plugins/chat/probes/claude-native-commands.probe.mjs
 * (requires `npm ci` in plugins/harness/packaging/claude — an untracked closure)
 */
import { spawn } from 'node:child_process'
import { once } from 'node:events'
import { createServer } from 'node:http'
import { mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { Readable, Writable } from 'node:stream'
import { fileURLToPath } from 'node:url'

import { PROTOCOL_VERSION, client, methods, ndJsonStream } from '@agentclientprotocol/sdk'

const CLOSURE = fileURLToPath(new URL('../../harness/packaging/claude/', import.meta.url))
const ADAPTER_ENTRY = join(CLOSURE, 'node_modules/@agentclientprotocol/claude-agent-acp/dist/index.js')

const timeout = (work, label) => {
  let timer
  return Promise.race([
    work,
    new Promise((_, reject) => { timer = setTimeout(() => reject(new Error(`${label} timed out`)), 45_000) }),
  ]).finally(() => clearTimeout(timer))
}

const clip = line => (line.length > 800 ? `${line.slice(0, 800)}…(${line.length}B)` : line)
const transcript = []
const record = (direction, frame) => { transcript.push(`${direction} ${clip(JSON.stringify(frame))}`) }

let adapter
const servers = []
try {
  // The fake Anthropic API: minimal /v1/messages SSE answer, count_tokens stub.
  const calls = []
  const fakeApi = createServer(async (request, response) => {
    let raw = ''
    for await (const chunk of request) raw += chunk
    if (request.url?.startsWith('/v1/messages/count_tokens')) {
      response.writeHead(200, { 'content-type': 'application/json' })
      response.end(JSON.stringify({ input_tokens: 20 }))
      return
    }
    if (!request.url?.startsWith('/v1/messages')) { response.writeHead(404); response.end(); return }
    calls.push(JSON.parse(raw))
    const send = (type, data) => response.write(`event: ${type}\ndata: ${JSON.stringify(data)}\n\n`)
    response.writeHead(200, { 'content-type': 'text/event-stream' })
    send('message_start', { type: 'message_start', message: { id: 'msg_probe', type: 'message', role: 'assistant',
      model: 'controlled-model', content: [], stop_reason: null, stop_sequence: null, usage: { input_tokens: 20, output_tokens: 0 } } })
    send('content_block_start', { type: 'content_block_start', index: 0, content_block: { type: 'text', text: '' } })
    send('content_block_delta', { type: 'content_block_delta', index: 0, delta: { type: 'text_delta', text: 'probe' } })
    send('content_block_stop', { type: 'content_block_stop', index: 0 })
    send('message_delta', { type: 'message_delta', delta: { stop_reason: 'end_turn', stop_sequence: null }, usage: { output_tokens: 3 } })
    response.end('event: message_stop\ndata: {"type":"message_stop"}\n\n')
  })
  fakeApi.listen(0, '127.0.0.1')
  await once(fakeApi, 'listening')
  servers.push(fakeApi)
  const baseUrl = `http://127.0.0.1:${fakeApi.address().port}`

  const scratch = await mkdtemp(join(tmpdir(), 'ordessa-pc10-claude-'))
  const env = {
    ...process.env,
    CLAUDE_CONFIG_DIR: join(scratch, 'claude-config'),
    CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC: '1',
    DISABLE_TELEMETRY: '1',
  }
  for (const key of Object.keys(env)) {
    if (key.startsWith('ANTHROPIC_') || key.startsWith('CLAUDE_CODE_OAUTH')) delete env[key]
  }
  adapter = spawn(process.execPath, [ADAPTER_ENTRY], { env, stdio: ['pipe', 'pipe', 'pipe'], cwd: scratch })
  let stderr = ''
  adapter.stderr.on('data', chunk => { stderr += chunk })
  adapter.on('exit', code => transcript.push(`adapter exited code=${code}`))

  const commandUpdates = []
  const route = {
    claudeCode: { options: {
      env: { ANTHROPIC_BASE_URL: baseUrl, ANTHROPIC_AUTH_TOKEN: 'controlled-local-token',
        CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC: '1' },
      settings: { env: { ANTHROPIC_BASE_URL: baseUrl, ANTHROPIC_AUTH_TOKEN: 'controlled-local-token' } },
    } },
  }
  const stream = ndJsonStream(Writable.toWeb(adapter.stdin), Readable.toWeb(adapter.stdout))
  const connection = client({ name: 'ordessa-pc10-command-probe' })
    .onNotification(methods.client.session.update, params => {
      record('inbound session/update', params)
      if (params?.update?.sessionUpdate === 'available_commands_update') commandUpdates.push(params.update)
    })
    .onRequest(methods.client.session.requestPermission, () => ({ outcome: { outcome: 'cancelled' } }))
    .onRequest(methods.client.fs.readTextFile, () => ({ content: '' }))
    .onRequest(methods.client.fs.writeTextFile, () => ({}))
    .connect(stream)
  const agent = connection.agent
  record('outbound initialize', { protocolVersion: PROTOCOL_VERSION })
  const initialized = await timeout(agent.request(methods.agent.initialize, {
    protocolVersion: PROTOCOL_VERSION,
    clientCapabilities: { fs: { readTextFile: true, writeTextFile: true }, terminal: false },
  }), 'initialize')
  record('inbound initialize result', initialized)

  const session = await timeout(agent.request(methods.agent.session.new, {
    cwd: scratch, mcpServers: [], _meta: route,
  }), 'session/new')
  record('inbound session/new result', session)

  const prompt = await timeout(agent.request(methods.agent.session.prompt, {
    sessionId: session.sessionId, prompt: [{ type: 'text', text: 'probe turn' }],
  }), 'prompt')
  record('inbound prompt result', prompt)
  // A brand may publish its catalog only after the turn warms up; wait a beat.
  await new Promise(resolve => setTimeout(resolve, 3_000))

  const conclusion = commandUpdates.length > 0
    ? { announced: true, catalogs: commandUpdates }
    : { announced: false, reason: 'no available_commands_update frame on the whole controlled channel' }
  console.log(JSON.stringify({
    result: 'PROBE_COMPLETE', conclusion,
    fakeApiCalls: calls.length,
    transcript,
    stderrTail: stderr.split('\n').filter(Boolean).slice(-12),
  }, null, 2))
  adapter.kill()
  fakeApi.close()
  await rm(scratch, { recursive: true, force: true })
} catch (error) {
  console.error(JSON.stringify({ result: 'PROBE_FAILED', error: String(error), transcript }, null, 2))
  adapter?.kill()
  for (const server of servers) server.close()
  process.exitCode = 1
}
