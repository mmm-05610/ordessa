import { afterEach, expect, it, vi } from 'vitest'
import { chmodSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import type { PluginContext } from '@ordessa/extension-api'
import { OwnedResources } from '@ordessa/extension-api'
import { createConnections } from '../../../../packages/desktop-platform/connections/src/index'
import { createAgentConnections } from '../../../../plugins/agent/connections/src/entry'
import type { AgentClient, AgentConnector, AgentConnections } from '@extensions/ordessa.agent-contracts/contract.js'
// Type-only import of the renderer's host bridge declaration: this wiring test documents the real host seam.
import type { AgentNativeBridge } from '../../../../apps/desktop/renderer/agent-native'
import type { NativeConnection } from '../../../../packages/desktop-platform/native-bridge/src/index'
import createPlugin from '../../../../plugins/connectors/acp/src/entry'
import createTransport from '../../../../plugins/connectors/acp/src/native'
import { HarnessPeer } from '../../../../tests/integration/acp-connector/fixtures/acp-peer'

/**
 * Full-stack wiring of the ACP connector: the real main-side transport (`native.ts`), the real
 * renderer bridge half (`host.ts`), the real `AcpClient` and the real plugin activation, with only
 * the two external boundaries faked. The HTTP fake is built from the backend's implemented seam —
 * `bc-native/src/agent_box/server/wire/handlers.py` (param-shape gate, `server.hello.nativeExecution`
 * identity, `workspaces.list`/`workspaces.open`, `acp.channel.open`/`acp.channel.release`) and the
 * `/wire/v1/acp-channel/{connectionId}` route — and an in-process `HarnessPeer` per granted channel
 * sits behind a fake WebSocket relay. These are controlled-passing tests: they prove the frontend
 * wiring against the real contract; they do NOT prove real desktop integration.
 */

const SERVER_ORIGIN = 'http://127.0.0.1:41233'
const TOKEN = 'wiring-bearer-1'
const INSTANCE_ID = 'native-instance-1'
const PAIR = `${SERVER_ORIGIN}|server_1|pi`
/** Exactly what the backend's dispatch table can answer for this seam (handlers.py `_PARAM_SHAPES`). */
const WIRE_CAPABILITIES = ['server.hello', 'workspaces.list', 'workspaces.open', 'acp.channel.open', 'acp.channel.release', 'executions.get']
const PARAM_SHAPES: Record<string, [readonly string[], readonly string[]]> = {
  'server.hello': [['clientVersions', 'clientPresentationSupports'], []],
  'workspaces.list': [['includeArchived'], []],
  'workspaces.open': [['requestId', 'environment', 'path'], ['expectedVersion']],
  'acp.channel.open': [['harnessId', 'projectId'], ['requestId']],
  'acp.channel.release': [['connectionId'], ['requestId']],
}

class ServerRefusal extends Error {
  constructor(readonly code: string, message: string) { super(message) }
}

interface ChannelRecord { id: string; projectId: string; executionId: string; peer: HarnessPeer; socket: FakeSocket | undefined }
/** Module-level because the fake WebSocket constructor must reach these before `startServer` returns. */
const channels = new Map<string, ChannelRecord>()
const attaches = new Map<string, number>()
let wire: { method: string; params: Record<string, unknown>; authorization: string | undefined; redirect: string | undefined }[] = []
let calls: string[] = []
let releases: string[] = []
/** Makes the next `acp.channel.release` be refused with a real failure (not the benign
 * already-ended NOT_FOUND), once — the backend-side half of the failed-release receipt. */
let refuseNextRelease = false
/** Makes the next `acp.channel.release` answer a *successful* RPC carrying `released:false`
 * (the backend's honest unconfirmed-release shape), once — the channel stays live. */
let unconfirmedNextRelease = false

const WORKSPACES = [
  { id: 'ws_app', displayName: 'app', normalizedPath: '/repo/app' },
  { id: 'ws_docs', displayName: 'docs', normalizedPath: '/repo/docs' },
]
/** The backend's own WorkspaceRecord projection (projection.py `workspace_record`). */
const workspaceRecord = (row: { id: string; displayName: string; normalizedPath: string }) => ({
  ...row, version: 1, environment: { kind: 'local', host: null, user: null },
  accessibility: { state: 'available' }, connection: { state: 'connected' },
  archivedAt: null, createdAt: '2026-09-01T00:00:00Z', updatedAt: '2026-09-01T00:00:00Z',
})

class FakeSocket {
  closed = false
  private readonly listeners = new Map<string, ((event: any) => void)[]>()
  channel: ChannelRecord | undefined
  constructor(readonly url: string, readonly options: { headers: Record<string, string> }) {
    // The real route takes the connectionId as a path segment, not a query.
    const connectionId = decodeURIComponent(new URL(url).pathname.split('/').pop() ?? '')
    setTimeout(() => {
      const channel = channels.get(connectionId)
      if (!channel) {
        this.fire('error', {})
        this.fire('close', { code: 4400, reason: 'UNKNOWN_CONNECTION' })
        return
      }
      attaches.set(connectionId, (attaches.get(connectionId) ?? 0) + 1)
      this.channel = channel
      channel.socket = this
      const reader = channel.peer.stream.readable.getReader()
      const pump = async () => {
        for (;;) {
          const { value, done } = await reader.read()
          if (done) break
          this.fire('message', { data: JSON.stringify(value) })
        }
      }
      void pump().catch(() => undefined)
      this.fire('open', {})
    }, 0)
  }
  addEventListener(type: string, listener: (event: any) => void) {
    const list = this.listeners.get(type) ?? []
    list.push(listener)
    this.listeners.set(type, list)
  }
  fire(type: string, event: unknown) { for (const listener of [...this.listeners.get(type) ?? []]) listener(event) }
  send(data: string) {
    if (!this.channel) throw new Error('relay without channel')
    const writer = this.channel.peer.stream.writable.getWriter()
    void writer.write(JSON.parse(data)).catch(() => undefined).then(() => writer.releaseLock())
  }
  close() {
    if (this.closed) return
    this.closed = true
    this.fire('close', { code: 1000, reason: 'released' })
  }
}

// ——— host-facing release lifecycle, read through the typed `AgentClient` members only ———
const hostDiagnostics = (client: AgentClient) => (client.releaseFailures ?? []).map(failure => ({ ...failure }))
async function hostRetry(client: AgentClient) {
  if (!client.retryReleases) throw new Error('host retry entry point missing')
  await client.retryReleases()
}

/** The implemented managed-ACP-channel seam, answered the way the backend answers it. */
function startServer(options: { offerAcp: boolean }) {
  channels.clear()
  attaches.clear()
  wire = []
  calls = []
  releases = []
  refuseNextRelease = false
  unconfirmedNextRelease = false
  let sequence = 0
  const liveByPair = new Map<string, ChannelRecord>()
  const handle = (method: string, params: Record<string, unknown>): unknown => {
    calls.push(method)
    const shape = PARAM_SHAPES[method]
    if (!shape) throw new ServerRefusal('INVALID_REQUEST', `${method} is not a wire/1 method`)
    const keys = Object.keys(params)
    const missing = shape[0].filter(key => !keys.includes(key))
    const extra = keys.filter(key => !shape[0].includes(key) && !shape[1].includes(key))
    if (missing.length || extra.length) {
      throw new ServerRefusal('INVALID_REQUEST', `params shape is invalid: ${missing.length ? 'missing ' : 'unexpected '}${[...missing, ...extra].join(', ')}`)
    }
    switch (method) {
      case 'server.hello': return {
        serverId: 'server_1', protocolVersion: 'wire/1',
        capabilities: (options.offerAcp ? WIRE_CAPABILITIES : ['server.hello', 'workspaces.list']).map(id => ({ id, supported: true })),
        auth: { required: true, schemes: ['session_token'] },
        harnesses: [{ id: 'pi' }],
        ...(options.offerAcp ? { nativeExecution: { mode: 'native', harness: 'pi', profileId: 'profile_fake' } } : {}),
      }
      case 'workspaces.list': return { items: WORKSPACES.map(workspaceRecord), nextCursor: null }
      case 'workspaces.open': {
        const found = WORKSPACES.find(row => row.normalizedPath === params.path)
        if (!found) throw new ServerRefusal('NOT_FOUND', `no project at ${String(params.path)}`)
        return { created: false, workspace: workspaceRecord(found) }
      }
      case 'acp.channel.open': {
        // Identity first, project second, launch last — a refusal starts nothing (handlers.py).
        if (params.harnessId !== 'pi') {
          throw new ServerRefusal('CAPABILITY_UNSUPPORTED', `${String(params.harnessId)} is not the native Harness this Server answers channels for`)
        }
        const projectId = String(params.projectId)
        const workspace = WORKSPACES.find(row => row.id === projectId)
        if (!workspace) throw new ServerRefusal('NOT_FOUND', `no workspace record ${projectId}`)
        const pair = `pi|${projectId}`
        const existing = liveByPair.get(pair)
        if (existing) {
          return { connectionId: existing.id, executionId: existing.executionId,
            binding: { harnessId: 'pi', projectId: existing.projectId, cwd: workspace.normalizedPath } }
        }
        const id = `conn_${++sequence}`
        const peer = new HarnessPeer({ capabilities: { promptCapabilities: {} } })
        const record: ChannelRecord = { id, projectId, executionId: `turn_${id}`, peer, socket: undefined }
        channels.set(id, record)
        liveByPair.set(pair, record)
        return { connectionId: id, executionId: record.executionId,
          binding: { harnessId: 'pi', projectId, cwd: workspace.normalizedPath } }
      }
      case 'acp.channel.release': {
        const id = String(params.connectionId)
        const record = channels.get(id)
        if (!record) throw new ServerRefusal('NOT_FOUND', 'no live managed channel carries that connectionId')
        if (refuseNextRelease) {
          // A real transient failure: the channel stays live, the stand-down is NOT done.
          refuseNextRelease = false
          throw new ServerRefusal('UNAVAILABLE', 'the backend could not stand the channel down')
        }
        if (unconfirmedNextRelease) {
          // The backend's honest failure-over-a-successful-RPC shape (fix round): the entry's
          // receipt admitted a survivor, so `released` is false with a reason and the channel
          // stays live. This exact member set is what `acp.channel.release` answers.
          unconfirmedNextRelease = false
          return { released: false, connectionId: id, executionId: record.executionId,
            sessionId: `sess_${id}`, reason: 'release-unconfirmed' }
        }
        releases.push(id)
        liveByPair.delete(`pi|${record.projectId}`)
        record.peer.close()
        channels.delete(id)
        return { released: true, connectionId: id, executionId: record.executionId, sessionId: `sess_${id}`, endReason: 'released' }
      }
    }
    throw new ServerRefusal('INVALID_REQUEST', `${method} is not wired in this fake`)
  }
  vi.stubGlobal('fetch', async (rawUrl: unknown, init: any) => {
    const body = JSON.parse(String(init.body))
    wire.push({ method: body.method, params: body.params ?? {}, authorization: init.headers?.authorization, redirect: init.redirect })
    try {
      return new Response(JSON.stringify({ jsonrpc: '2.0', id: body.id, result: handle(body.method, body.params ?? {}) }), { status: 200 })
    } catch (error) {
      if (!(error instanceof ServerRefusal)) throw error
      return new Response(JSON.stringify({ jsonrpc: '2.0', id: body.id, error: { code: error.code, message: error.message } }), { status: 200 })
    }
  })
  vi.stubGlobal('WebSocket', FakeSocket)
}

let tokenLocator: string | undefined
function serverEnv() {
  const root = mkdtempSync(path.join(tmpdir(), 'ordessa-acp-wiring-'))
  mkdirSync(path.join(root, 'secrets'))
  tokenLocator = path.join(root, 'secrets', 'http-token')
  writeFileSync(tokenLocator, `${TOKEN}\n`)
  chmodSync(tokenLocator, 0o600)
  process.env.ORDESSA_SERVER_ORIGIN = SERVER_ORIGIN
  process.env.ORDESSA_SERVER_TOKEN_FILE = tokenLocator
  return root
}

/** The Electron main side of the bridge, without the IPC hop: same transport, same events. */
class MainBridge implements AgentNativeBridge {
  readonly closed: string[] = []
  private readonly listeners = new Set<(event: { instanceId: string; frame?: unknown; error?: string }) => void>()
  private connection: NativeConnection | undefined
  async open(adapterId: string) {
    if (adapterId !== 'ordessa.agent-acp') throw new Error('Native adapter unavailable')
    this.connection = await createTransport().open(frame => {
      for (const listener of [...this.listeners]) listener({ instanceId: INSTANCE_ID, frame })
    })
    return INSTANCE_ID
  }
  async send(instanceId: string, frame: unknown) {
    if (!this.connection || instanceId !== INSTANCE_ID) throw new Error('Native instance unavailable')
    return await this.connection.send(frame)
  }
  async close(instanceId: string) {
    if (!this.connection || instanceId !== INSTANCE_ID) return
    this.closed.push(instanceId)
    const connection = this.connection
    this.connection = undefined
    await connection.close()
  }
  subscribe(listener: (event: { instanceId: string; frame?: unknown; error?: string }) => void) {
    this.listeners.add(listener)
    return () => { this.listeners.delete(listener) }
  }
}

function activationOf(added: AgentConnector[], disposables: { dispose(): unknown }[]) {
  const context = {
    resources: { isDisposed: false, add: <T extends { dispose(): unknown }>(item: T) => { disposables.push(item); return item } },
  } as unknown as PluginContext
  const connections = {
    forScope: () => ({ add: (connector: AgentConnector) => { added.push(connector); return { dispose() {} } } }),
  } as unknown as AgentConnections
  return () => createPlugin().activate(context, connections) as Promise<unknown>
}

async function until(what: string, predicate: () => boolean, timeoutMs = 2_000) {
  const deadline = Date.now() + timeoutMs
  while (!predicate()) {
    if (Date.now() > deadline) throw new Error(`timed out waiting for ${what}`)
    await new Promise(resolve => setTimeout(resolve, 5))
  }
}

let tempRoot: string | undefined
afterEach(() => {
  for (const channel of channels.values()) channel.peer.close()
  channels.clear()
  if (tempRoot) rmSync(tempRoot, { recursive: true, force: true })
  tempRoot = undefined
  delete process.env.ORDESSA_SERVER_ORIGIN
  delete process.env.ORDESSA_SERVER_TOKEN_FILE
  vi.unstubAllGlobals()
})

it('activates through bridge, transport and host: the native pair is offered once, and the reviewed loop runs over the real contract', async () => {
  tempRoot = serverEnv()
  startServer({ offerAcp: true })
  const bridge = new MainBridge()
  vi.stubGlobal('window', { agentNative: bridge })
  const added: AgentConnector[] = []
  const disposables: { dispose(): unknown }[] = []
  expect(await activationOf(added, disposables)()).toEqual([`acp:${PAIR}`])
  expect(added.map(item => ({ id: item.id, title: item.title }))).toEqual([{ id: `acp:${PAIR}`, title: 'ACP · pi' }])

  const client = await added[0].connect!() as AgentClient
  expect(client.getSnapshot().connection.serverInstanceId).toBe(PAIR)
  expect(client.getSnapshot().workspaces?.items.map(item => item.id)).toEqual(['ws_app', 'ws_docs'])
  // The project list rides the existing workspaces surface, exactly as the backend requires it.
  expect(wire.find(call => call.method === 'workspaces.list')?.params).toEqual({ includeArchived: false })
  await client.openWorkspace!('ws_app')
  const [record] = [...channels.values()]
  expect(record.projectId).toBe('ws_app')
  expect(record.peer.recorded('initialize')).toHaveLength(1)
  // The open names only {harnessId, projectId} — no invented instance/harness envelope reaches the wire,
  // and the project was re-opened through workspaces.open with the record's own environment and path.
  expect(wire.find(call => call.method === 'acp.channel.open')?.params).toEqual({ harnessId: 'pi', projectId: 'ws_app' })
  const opened = wire.find(call => call.method === 'workspaces.open')?.params
  expect(opened).toMatchObject({ environment: { kind: 'local' }, path: '/repo/app' })
  expect(String(opened?.requestId)).toMatch(/^workspace_/)
  // The relay rides the real route: connectionId as path segment, bearer header, loopback ws.
  expect(record.socket?.url).toBe(`ws://127.0.0.1:41233/wire/v1/acp-channel/${record.id}`)
  expect(record.socket?.options.headers.authorization).toBe(`Bearer ${TOKEN}`)
  for (const call of wire) expect(call.authorization).toBe(`Bearer ${TOKEN}`)
  // The open is idempotent per live pair: same connection, same run, and the relay is attached once.
  const again = await bridge.send(INSTANCE_ID, { method: 'acp/channel/open', params: { instanceId: PAIR, projectId: 'ws_app' } }) as Record<string, unknown>
  expect(again).toEqual({ connectionId: record.id, executionId: record.executionId, binding: { id: 'ws_app', normalizedPath: '/repo/app' } })
  await until('the second attach attempt to settle', () => (attaches.get(record.id) ?? 0) >= 1)
  await new Promise(resolve => setTimeout(resolve, 20))
  expect(attaches.get(record.id)).toBe(1)

  record.peer.queueTurn(async api => {
    await api.update({ sessionUpdate: 'agent_message_chunk', content: { type: 'text', text: 'pong over the bridge' } })
    return 'end_turn'
  })
  const { sessionId } = await client.createAndSend!('ws_app', 'ping', 'req_1')
  // The authoritative cwd comes from the Server's binding, not from anything this side assumed.
  expect(record.peer.recorded('session/new')[0].params).toMatchObject({ cwd: '/repo/app' })
  await until('the turn settles', () => Object.values(client.getSnapshot().runs).some(run => run.sessionId === sessionId && run.status === 'completed'))
  expect((client.getSnapshot().messages[sessionId] ?? []).map(message => message.text).join('')).toContain('pong over the bridge')

  // Nothing but the seam's own methods was ever called, in exactly this order.
  expect(calls).toEqual(['server.hello', 'workspaces.list', 'workspaces.list', 'workspaces.open', 'acp.channel.open', 'acp.channel.open'])
  client.dispose()
  await until('the explicit backend release lands', () => releases.length === 1)
  expect(releases).toEqual([record.id])
  // The relay is now stood down only after the backend's confirmed answer (a `released:false`
  // must leave it live), so the local close follows the landing — bounded wait, same demand.
  await until('the confirmed stand-down to close the local relay', () => record.socket?.closed === true)
  expect(calls.at(-1)).toBe('acp.channel.release')
  await bridge.close(INSTANCE_ID)
  expect(disposables.length).toBeGreaterThan(0)
})

it('a Server whose hello carries no native-execution identity activates as an honest not-offered and registers nothing', async () => {
  tempRoot = serverEnv()
  startServer({ offerAcp: false })
  const bridge = new MainBridge()
  vi.stubGlobal('window', { agentNative: bridge })
  const added: AgentConnector[] = []
  expect(await activationOf(added, [])()).toBe('not-offered')
  expect(added).toEqual([])
  // The handshake is all the wire ever saw; no channel was invented behind the Server's back.
  expect(calls).toEqual(['server.hello'])
  expect(bridge.closed).toEqual([INSTANCE_ID])
})

it('refuses bridge frames the transport does not know, and they never reach the wire', async () => {
  tempRoot = serverEnv()
  startServer({ offerAcp: true })
  const bridge = new MainBridge()
  vi.stubGlobal('window', { agentNative: bridge })
  await activationOf([], [])()
  expect(String(await bridge.send(INSTANCE_ID, { method: 'bogus/method' }).catch((error: unknown) => error))).toMatch(/Unsupported ACP native frame/)
  expect(String(await bridge.send(INSTANCE_ID, { noMethod: true }).catch((error: unknown) => error))).toMatch(/Invalid ACP native frame/)
  expect(String(await bridge.send(INSTANCE_ID, { method: 'acp/channel/send', params: { connectionId: 'conn_missing', frame: {} } }).catch((error: unknown) => error)))
    .toMatch(/ACP channel relay unavailable/)
  expect(calls).toEqual(['server.hello'])
})

it('refuses controlled admission when Server has no submission authority', async () => {
  tempRoot = serverEnv()
  startServer({ offerAcp: true })
  const bridge = new MainBridge()
  vi.stubGlobal('window', { agentNative: bridge })
  await activationOf([], [])()
  const opened = await bridge.send(INSTANCE_ID, { method: 'acp/channel/open',
    params: { instanceId: PAIR, projectId: 'ws_app' } }) as Record<string, unknown>
  const before = [...calls]
  const result = await bridge.send(INSTANCE_ID, { method: 'acp/channel/authorizeSubmission',
    params: { connectionId: opened.connectionId, submission: { submissionId: 'one',
      nativeSessionId: 'session-1', text: 'hello', configurationDigest: 'a'.repeat(64), attachments: [] } } })
    .catch((error: unknown) => error)
  expect(String(result)).toMatch(/acp\.submission\.authorize is not available/)
  const permission = await bridge.send(INSTANCE_ID, { method: 'acp/channel/authorizePermission',
    params: { connectionId: opened.connectionId, decision: { nativeSessionId: 'session-1',
      interactionId: 'interaction-1', runId: 'run-1', optionId: 'allow-once' } } })
    .catch((error: unknown) => error)
  expect(String(permission)).toMatch(/acp\.permission\.authorize is not available/)
  expect(calls).toEqual(before)
  expect(channels.get(String(opened.connectionId))?.peer.recorded('session/prompt')).toHaveLength(0)
  await until('the relay attaches before release', () => (attaches.get(String(opened.connectionId)) ?? 0) === 1)
  await bridge.send(INSTANCE_ID, { method: 'acp/channel/release', params: { connectionId: opened.connectionId } })
  await bridge.close(INSTANCE_ID)
})

it('a refused open launches nothing: an unopened project answers NOT_FOUND and a foreign instance is refused locally', async () => {
  tempRoot = serverEnv()
  startServer({ offerAcp: true })
  const bridge = new MainBridge()
  vi.stubGlobal('window', { agentNative: bridge })
  await activationOf([], [])()
  expect(String(await bridge.send(INSTANCE_ID, { method: 'acp/channel/open', params: { instanceId: PAIR, projectId: 'ws_missing' } }).catch((error: unknown) => error)))
    .toMatch(/NOT_FOUND|no workspace record/)
  expect(channels.size).toBe(0)
  expect(attaches.size).toBe(0)
  // An instance this Server never offered is refused before any request leaves this side.
  expect(String(await bridge.send(INSTANCE_ID, { method: 'acp/projects', params: { instanceId: 'http://127.0.0.1:9|server_9|pi' } }).catch((error: unknown) => error)))
    .toMatch(/never offered/)
  expect(calls).toEqual(['server.hello', 'acp.channel.open'])
})

it('a relay death is never a release: it errors the stream, cancels nothing, and the stand-down stays explicit', async () => {
  tempRoot = serverEnv()
  startServer({ offerAcp: true })
  const bridge = new MainBridge()
  vi.stubGlobal('window', { agentNative: bridge })
  const added: AgentConnector[] = []
  await activationOf(added, [])()
  const client = await added[0].connect!() as AgentClient
  await client.openWorkspace!('ws_app')
  const [record] = [...channels.values()]
  // The leading chunk is the acceptance proof the reviewed loop requires; the turn then parks, so
  // the link genuinely dies mid-turn here.
  record.peer.queueTurn(async api => {
    await api.update({ sessionUpdate: 'agent_message_chunk', content: { type: 'text', text: 'stalling' } })
    await api.cancelled()
    return 'cancelled'
  })
  await client.createAndSend!('ws_app', 'parked', 'req_1')
  await until('the prompt to leave', () => record.peer.recorded('session/prompt').length === 1)
  record.peer.drop(new Error('link reset'))
  record.socket?.fire('close', { code: 1006, reason: 'link reset' })
  // The death arrives in the renderer as a stream error and the open turn is held as unknown —
  // never dressed up as a cancellation this side did not ask for.
  await until('the dropped run to land as unknown', () => Object.values(client.getSnapshot().runs).some(run => run.status === 'unknown'))
  expect(Object.values(client.getSnapshot().runs).every(run => run.status !== 'cancelled')).toBe(true)
  // Dropping the relay tore no backend channel down on its own.
  expect(releases).toEqual([])
  // And the dead relay answers nothing: a send into it is refused, not queued into the void.
  expect(String(await bridge.send(INSTANCE_ID, { method: 'acp/channel/send', params: { connectionId: record.id, frame: {} } }).catch((error: unknown) => error)))
    .toMatch(/ACP channel relay unavailable/)
  // The explicit release still stands the channel down after death — the backend gets the call.
  client.dispose()
  await until('the release after death lands', () => releases.length === 1)
  expect(releases).toEqual([record.id])
})

it('a refused release reaches the host as a typed diagnostic and the explicit retry lands over the same still-open bridge', async () => {
  tempRoot = serverEnv()
  startServer({ offerAcp: true })
  const bridge = new MainBridge()
  vi.stubGlobal('window', { agentNative: bridge })
  const added: AgentConnector[] = []
  const disposables: { dispose(): unknown }[] = []
  await activationOf(added, disposables)()
  const client = await added[0].connect!() as AgentClient
  await client.openWorkspace!('ws_app')
  const [record] = [...channels.values()]
  refuseNextRelease = true
  client.dispose()
  // The backend's refusal survives every hop (wire envelope → native rpc → bridge frame → handle
  // release → client) and lands on the contract-typed diagnostic surface, naming the connection
  // with the Server's own message.
  await until('the refused release to surface as a host-visible diagnostic', () => hostDiagnostics(client).length === 1)
  expect(hostDiagnostics(client)).toEqual([{ connectionId: record.id, reason: 'the backend could not stand the channel down' }])
  expect(releases).toEqual([])
  // The bridge instance belongs to the plugin scope, not to the disposed client (entry.ts binds
  // its lease to context.resources): the one path a retry needs is verifiably still open.
  expect(bridge.closed).toEqual([])
  await hostRetry(client)
  expect(releases).toEqual([record.id])
  expect(hostDiagnostics(client)).toEqual([])
  // A further retry pass on confirmed work books no additional backend call — no silent loop.
  await hostRetry(client)
  expect(calls.filter(method => method === 'acp.channel.release')).toEqual(['acp.channel.release', 'acp.channel.release'])
  // And the lease that owns the bridge is still the plugin's: standing the scope down closes it.
  for (const item of disposables) item.dispose()
  expect(bridge.closed).toEqual([INSTANCE_ID])
})

it('a release answered released:false over a successful RPC is never booked as success, and the retry confirms', async () => {
  // Cross-layer pin (backend fix round): `acp.channel.release` may answer HTTP-OK with
  // {released:false, connectionId, executionId, sessionId, reason}; the transport must check the
  // field — an RPC that merely did not throw is not a release.
  tempRoot = serverEnv()
  startServer({ offerAcp: true })
  const bridge = new MainBridge()
  vi.stubGlobal('window', { agentNative: bridge })
  const added: AgentConnector[] = []
  await activationOf(added, [])()
  const client = await added[0].connect!() as AgentClient
  await client.openWorkspace!('ws_app')
  const [record] = [...channels.values()]
  unconfirmedNextRelease = true
  client.dispose()
  // The unconfirmed answer arrives on the same typed diagnostic surface as a refusal, naming the
  // backend's own reason; nothing on either side was stood down.
  await until('the unconfirmed release to surface as a host-visible diagnostic', () => hostDiagnostics(client).length === 1)
  expect(hostDiagnostics(client)).toEqual([{ connectionId: record.id, reason: 'ACP channel release unconfirmed: release-unconfirmed' }])
  expect(releases).toEqual([])
  expect(channels.has(record.id)).toBe(true)
  // The retry goes out over the same live pair; only the confirmed answer clears both sides.
  await hostRetry(client)
  expect(releases).toEqual([record.id])
  expect(hostDiagnostics(client)).toEqual([])
  expect(calls.filter(method => method === 'acp.channel.release')).toEqual(['acp.channel.release', 'acp.channel.release'])
})

it('the real workspace reconnect flow proves the host consumption: an evicted ACP client with a refused release stays visible and retryable through the workspace surface', async () => {
  tempRoot = serverEnv()
  startServer({ offerAcp: true })
  const bridge = new MainBridge()
  vi.stubGlobal('window', { agentNative: bridge })
  const added: AgentConnector[] = []
  await activationOf(added, [])()
  // The actual host: connections service + real workspace owning the real ACP connector.
  const serviceScope = new OwnedResources(), connectorScope = new OwnedResources()
  const registry = createAgentConnections(serviceScope, createConnections(serviceScope))
  registry.forScope(connectorScope).add(added[0])
  const workspace = registry.workspace
  await workspace.selectConnection(added[0].id)
  const old = workspace.selected()
  await old.openWorkspace!('ws_app')
  const [record] = [...channels.values()]
  refuseNextRelease = true
  await workspace.reconnect(added[0].id)
  // The old client has left every current-connection surface — the workspace now owns a new one.
  expect(workspace.selected()).not.toBe(old)
  // And still, the refusal reaches the host as an ANNOUNCED state — the cleanup read never has to
  // infer it, and no extra selection or forced publish is involved on the way there.
  await until('the announced failure to reach the host cleanup read', () => (workspace.releaseCleanup?.() ?? []).some(item => item.status === 'failed'))
  expect(workspace.releaseCleanup!()).toEqual([{ connectionId: record.id, status: 'failed', reason: 'the backend could not stand the channel down' }])
  // The reactive snapshot carries the same state, re-published by the client's own notification.
  expect(workspace.getSnapshot().pendingReleases).toEqual([{ connectionId: record.id, status: 'failed', reason: 'the backend could not stand the channel down' }])
  // The bridge is plugin-scoped, not client-scoped: the host's retry path is verifiably alive.
  expect(bridge.closed).toEqual([])
  await workspace.retryReleaseCleanup!()
  expect(releases).toEqual([record.id])
  expect(workspace.releaseCleanup!()).toEqual([])
  expect(workspace.getSnapshot().pendingReleases).toEqual([])
  // Exactly two release calls ever: the eviction's attempt and the host's one explicit pass.
  expect(calls.filter(method => method === 'acp.channel.release')).toEqual(['acp.channel.release', 'acp.channel.release'])
  connectorScope.dispose(); serviceScope.dispose()
})

it('privileged-input refusals register nothing: no origin, and a token file group-readable', async () => {
  startServer({ offerAcp: true })
  const added: AgentConnector[] = []
  const bridge = new MainBridge()
  vi.stubGlobal('window', { agentNative: bridge })
  // No ORDESSA_SERVER_ORIGIN at all: the transport refuses before any request leaves.
  let failure = await activationOf(added, [])().catch((error: unknown) => error)
  expect(String(failure)).toMatch(/Ordessa Server ORDESSA_SERVER_ORIGIN is not set/)
  expect(added).toEqual([])
  expect(calls).toEqual([])
  // A bearer the group could read is refused by name-of-reason only, and still registers nothing.
  tempRoot = serverEnv()
  chmodSync(tokenLocator!, 0o644)
  failure = await activationOf(added, [])().catch((error: unknown) => error)
  expect(String(failure)).toMatch(/token file is readable by group or other/)
  expect(String(failure)).not.toContain(TOKEN)
  expect(added).toEqual([])
  expect(calls).toEqual([])
})

it('closing the bridge instance tears every live relay down and nothing flows afterwards', async () => {
  tempRoot = serverEnv()
  startServer({ offerAcp: true })
  const bridge = new MainBridge()
  vi.stubGlobal('window', { agentNative: bridge })
  const added: AgentConnector[] = []
  await activationOf(added, [])()
  const client = await added[0].connect!() as AgentClient
  await client.openWorkspace!('ws_app')
  const [record] = [...channels.values()]
  expect(record.socket).toBeDefined()
  await bridge.close(INSTANCE_ID)
  expect(record.socket!.closed).toBe(true)
  expect(bridge.closed).toEqual([INSTANCE_ID])
  expect(String(await bridge.send(INSTANCE_ID, { method: 'acp/identity' }).catch((error: unknown) => error))).toMatch(/Native instance unavailable/)
  // The client still holds a channel whose transport is gone; standing it down is the client's call,
  // and after the instance is closed even that refuses instead of hanging or faking a release.
  client.dispose()
  await new Promise(resolve => setTimeout(resolve, 20))
  expect(releases).toEqual([])
  record.peer.close()
})
