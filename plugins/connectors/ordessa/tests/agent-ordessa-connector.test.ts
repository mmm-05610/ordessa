import { expect, it, vi } from 'vitest'
import type { PluginContext } from '@ordessa/extension-api'
import type { AgentConnections } from '@extensions/ordessa.agent-contracts/contract.js'
import createPlugin from '../../../../plugins/connectors/ordessa/src/entry'
import { OrdessaClient, connectorIdFor } from '../../../../plugins/connectors/ordessa/src/client'
// Type-only host declaration import (erased at build time): AgentNativeBridge is declared by the desktop renderer.
import type { AgentNativeBridge } from '../../../../apps/desktop/renderer/agent-native'

const SERVER = 'http://127.0.0.1:41207'
const INSTANCE = `${SERVER}|server_1`
const LOCATOR = '/run/ordessa/data-root/secrets/http-token'
const capability = (id: string) => ({ id, supported: true })
const ROUTES = ['workspaces.list', 'workspaces.open', 'workspaces.archive', 'profiles.list', 'sessions.list',
  'sessions.createAndSend', 'sessions.send', 'sendOutcome.query', 'history.snapshot', 'runs.stop', 'approvals.decide']

const identityFor = (serverInstanceId: string, routes = ROUTES) => ({
  serverInstanceId, protocolVersion: 'wire/1',
  capabilities: routes.map(capability), harnesses: [{ id: 'pi' }],
})

class Bridge implements AgentNativeBridge {
  order: string[] = []
  sent: { instanceId: string; frame: any }[] = []
  closed: string[] = []
  listeners = new Set<(event: { instanceId: string; frame?: unknown; error?: string }) => void>()
  identity = identityFor(INSTANCE)
  openError: unknown
  responses = new Map<string, unknown>()
  errors = new Map<string, unknown>()
  private instances = 0
  private active = ''
  async open(adapterId: string) {
    this.order.push('open')
    if (this.openError) throw this.openError
    expect(adapterId).toBe('ordessa.agent-server')
    this.active = `instance-${++this.instances}`
    return this.active
  }
  async close(instanceId: string) { this.order.push('close'); this.closed.push(instanceId); if (this.active === instanceId) this.active = '' }
  subscribe(listener: (event: { instanceId: string; frame?: unknown; error?: string }) => void) {
    this.listeners.add(listener); return () => { this.listeners.delete(listener) }
  }
  /** The instance the client under test holds: whoever opened last. */
  get instanceId() { return `instance-${this.instances}` }
  frames(method: string) { return this.sent.filter(item => item.frame.method === method) }
  frame(method: string) { return this.frames(method).at(-1)?.frame }
  emit(sessionId: string, event: Record<string, unknown>) {
    this.deliver({ method: 'ordessa/event', params: { sessionId, frame: {
      eventId: `event_${String(this.sent.length)}`, sessionId, seq: 1, cursor: `w1:${sessionId}:1:sig`, emittedAt: '2026-09-23T00:00:00Z', event } } })
  }
  down(reason = 'event stream closed') { this.deliver({ method: 'ordessa/down', params: { sessionId: 'session_9', reason } }) }
  deliver(frame: unknown, instanceId = this.instanceId) {
    for (const listener of this.listeners) listener({ instanceId, frame })
  }
  async send(instanceId: string, frame: any) {
    this.order.push(`send:${frame.method}`)
    this.sent.push({ instanceId, frame })
    if (this.errors.has(frame.method)) throw this.errors.get(frame.method)
    if (this.responses.has(frame.method)) return this.responses.get(frame.method)
    switch (frame.method) {
      case 'identity': return this.identity
      case 'history': return { outcome: 'snapshot', frames: [], resumeCursor: `w1:session_9:7:head` }
      case 'projects': return [{ id: 'ws_1', normalizedPath: '/repo/app' }]
      case 'openProject': return { id: frame.params.id, normalizedPath: '/repo/app' }
      case 'sessions': return [{ id: 'session_9', title: 'Refactor', workspaceId: 'ws_1' }]
      default: return {}
    }
  }
}

const connectionsOf = (added: { id: string; title: string }[], order: string[] = []) => ({
  forScope: () => ({ add: (connector: { id: string; title: string }) => { order.push(`add:${connector.id}`); added.push(connector); return { dispose() {} } } }),
} as unknown as AgentConnections)
const context = { resources: { isDisposed: false, add: () => {} } } as unknown as PluginContext
const connect = async (bridge: Bridge) => await OrdessaClient.connect(bridge, connectorIdFor(INSTANCE), INSTANCE)

it('proves the authenticated Server instance before one connector is registered', async () => {
  const bridge = new Bridge(), added: { id: string; title: string }[] = []
  vi.stubGlobal('window', { agentNative: bridge })
  expect(await createPlugin().activate(context, connectionsOf(added, bridge.order))).toBe(`ordessa:${INSTANCE}`)
  // The hello happens first, so the id AgentConnections freezes is already the real instance scope.
  expect(bridge.order).toEqual(['open', 'send:identity', 'close', `add:ordessa:${INSTANCE}`])
  expect(added.map(item => ({ id: item.id, title: item.title }))).toEqual([{ id: `ordessa:${INSTANCE}`, title: 'Ordessa Server' }])
  expect(bridge.closed).toEqual([bridge.instanceId])
  vi.unstubAllGlobals()
})

it('registers nothing and strips the IPC wrapper from the native refusal', async () => {
  const bridge = new Bridge(), added: { id: string; title: string }[] = []
  // Exactly what the privileged half produces; the token file suite owns the guarantee that
  // no token bytes or full locator can appear in it. The renderer only removes the IPC prefix.
  bridge.openError = new Error(`Error invoking remote method 'agent-native:open': Error: Ordessa Server token file is unreadable; http-token`)
  vi.stubGlobal('window', { agentNative: bridge })
  const failure = await createPlugin().activate(context, connectionsOf(added)).then(() => undefined, error => error)
  expect(String(failure)).toBe('Error: Ordessa Server token file is unreadable; http-token')
  expect(String(failure)).not.toContain('agent-native:open')
  expect(String(failure)).not.toContain(LOCATOR)
  expect(added).toEqual([])
  vi.unstubAllGlobals()
  // A renderer without the bridge cannot reach the token at all, and still registers no pseudo connection.
  vi.stubGlobal('window', {})
  const addedWithout = [] as { id: string; title: string }[]
  expect(await createPlugin().activate(context, connectionsOf(addedWithout)).catch((error: unknown) => String(error)))
    .toMatch(/native bridge/)
  expect(addedWithout).toEqual([])
  vi.unstubAllGlobals()
})

it('refuses to reuse a frozen connection when the Server behind the URL changed', async () => {
  const bridge = new Bridge()
  bridge.identity = identityFor(`${SERVER}|server_2`)
  const failure = await connect(bridge).then(() => undefined, error => error)
  expect(String(failure)).toMatch(/identity changed/)
  // The drifted instance is released rather than kept as a second owner of the old id.
  expect(bridge.closed).toEqual(['instance-1'])
  expect(bridge.frames('sessions')).toEqual([])
})

it('projects an approved first send only from a real session id', async () => {
  const bridge = new Bridge()
  bridge.responses.set('createAndSend', { sessionId: 'session_9', profileId: 'profile_1' })
  const client = await connect(bridge)
  // FC-0049: the caller ends its draft on this exact id, so it must be the Server's, never a local stand-in.
  expect(await client.createAndSend('ws_1', 'refactor this', 'req_abc123')).toEqual({ sessionId: 'session_9' })
  const sent = bridge.frame('createAndSend')
  // F2 owns the idempotency key, so the connector must forward it unchanged.
  expect(sent.params).toEqual({ workspaceId: 'ws_1', text: 'refactor this', requestId: 'req_abc123' })
  const state = client.getSnapshot()
  expect(state.selectedSessionId).toBe('session_9')
  // The Server's own record wins over the local placeholder, and it stays bound to the chosen project.
  expect(state.sessions).toEqual([{ id: 'session_9', title: 'Refactor', workspaceId: 'ws_1' }])
  expect(state.workspaces?.selectedWorkspaceId).toBe('ws_1')
  // Subscription resumes where the snapshot joined, never from a guessed cursor.
  expect(bridge.frame('stream').params).toEqual({ sessionId: 'session_9', cursor: 'w1:session_9:7:head' })
  client.dispose()
})

it('keeps an accepted session when the list read has not caught up yet', async () => {
  const bridge = new Bridge()
  bridge.responses.set('createAndSend', { sessionId: 'session_9' })
  bridge.responses.set('sessions', [])
  const client = await connect(bridge)
  await client.createAndSend('ws_1', 'text', 'req_abc123')
  expect(client.getSnapshot().sessions).toEqual([{ id: 'session_9', title: 'session_9', workspaceId: 'ws_1' }])
  client.dispose()
})

it('rejects a first send whose session the Server binds to another project', async () => {
  const bridge = new Bridge()
  bridge.responses.set('createAndSend', { sessionId: 'session_9' })
  bridge.responses.set('sessions', [{ id: 'session_9', title: 'Elsewhere', workspaceId: 'ws_other' }])
  const client = await connect(bridge)
  expect(await client.createAndSend('ws_1', 'text', 'req_abc123').catch((error: unknown) => String(error)))
    .toMatch(/different project/)
  // No draft may end on a session the Server says belongs somewhere else, so it is never presented as opened.
  expect(client.getSnapshot().sessions).toEqual([])
  expect(client.getSnapshot().selectedSessionId).toBeUndefined()
  expect(bridge.frames('stream')).toEqual([])
  client.dispose()
})

it('accepts a first send the Server binds to the same project by path', async () => {
  const bridge = new Bridge()
  const client = await connect(bridge)
  await client.refreshWorkspaces()
  await client.openWorkspace('ws_1')
  bridge.responses.set('createAndSend', { sessionId: 'session_9' })
  bridge.responses.set('sessions', [{ id: 'session_9', title: 'Refactor', workspaceId: '/repo/app' }])
  expect(await client.createAndSend('ws_1', 'text', 'req_abc123')).toEqual({ sessionId: 'session_9' })
  expect(client.getSnapshot().selectedSessionId).toBe('session_9')
  client.dispose()
})

it('never reports a first send the Server did not confirm, and keeps the caller request id', async () => {
  const bridge = new Bridge()
  bridge.errors.set('createAndSend', new Error('OUTCOME_UNKNOWN: the first send was not confirmed'))
  const client = await connect(bridge)
  expect(await client.createAndSend('ws_1', 'text', 'req_abc123').catch((error: unknown) => String(error)))
    .toMatch(/not confirmed/)
  // The connector re-issues nothing on its own; the same requestId is the caller's to retry with.
  expect(bridge.frames('createAndSend')).toHaveLength(1)
  expect(client.getSnapshot().sessions).toEqual([])
  expect(client.getSnapshot().selectedSessionId).toBeUndefined()
  expect(bridge.frames('stream')).toEqual([])
  bridge.responses.delete('createAndSend')
  bridge.errors.delete('createAndSend')
  bridge.responses.set('createAndSend', { sessionId: 'session_9' })
  await client.createAndSend('ws_1', 'text', 'req_abc123')
  expect(bridge.frames('createAndSend').map(item => item.frame.params.requestId)).toEqual(['req_abc123', 'req_abc123'])
  client.dispose()
})

it('keeps an unconfirmed first send out of the session list', async () => {
  const bridge = new Bridge()
  bridge.responses.set('createAndSend', { sessionId: null })
  const client = await connect(bridge)
  expect(await client.createAndSend('ws_1', 'text', 'req_abc123').catch((error: unknown) => String(error))).toMatch(/no session identity/)
  const state = client.getSnapshot()
  expect(state.sessions).toEqual([])
  expect(state.selectedSessionId).toBeUndefined()
  expect(bridge.frames('stream')).toEqual([])
  client.dispose()
})

it('answers a real approval through one approvals.decide call only', async () => {
  const bridge = new Bridge()
  const client = await connect(bridge)
  bridge.emit('session_9', { kind: 'approval.requested', approval: {
    approvalId: 'approval_1', sessionId: 'session_9', executionId: 'execution_1', version: 3,
    operation: { title: 'Run command', detail: [{ label: 'tool', value: 'bash' }] } } })
  const pending = client.getSnapshot().interactions[0]
  expect(pending).toMatchObject({ id: 'approval_1', kind: 'approval', state: 'pending', title: 'Run command', detail: 'tool: bash', turnId: 'execution_1' })
  expect(pending.choices).toEqual([{ id: 'allow', label: 'Allow' }, { id: 'deny', label: 'Deny' }])
  bridge.responses.set('decide', { outcome: 'recorded', decision: 'allow' })
  await client.respond('approval_1', { kind: 'choice', choiceId: 'allow' })
  expect(bridge.frames('decide').map(item => item.frame.params)).toEqual([
    { approvalId: 'approval_1', expectedVersion: 3, decision: 'allow', scope: { kind: 'once' } }])
  expect(client.getSnapshot().interactions[0].state).toBe('resolved')
  // A settled card cannot be answered twice, and the route stays consumed.
  expect(await client.respond('approval_1', { kind: 'choice', choiceId: 'deny' }).catch((error: unknown) => String(error))).toMatch(/not an answerable approval/)
  expect(bridge.frames('decide')).toHaveLength(1)
  client.dispose()
})

it('refuses an answer that is not an allow or deny without touching the wire', async () => {
  const bridge = new Bridge()
  const client = await connect(bridge)
  bridge.emit('session_9', { kind: 'approval.requested', approval: { approvalId: 'approval_2', version: 1, operation: { title: 'Run' } } })
  expect(await client.respond('approval_2', { kind: 'text', value: 'yes' }).catch((error: unknown) => String(error))).toMatch(/allow or deny only/)
  expect(await client.respond('approval_2', { kind: 'choice', choiceId: 'maybe' }).catch((error: unknown) => String(error))).toMatch(/allow or deny only/)
  expect(bridge.frames('decide')).toEqual([])
  expect(bridge.frames('send')).toEqual([])
  expect(client.getSnapshot().interactions[0].state).toBe('pending')
  client.dispose()
})

it('never presents an ordinary request as answerable, and keeps approvals answerable (FC-0041)', async () => {
  const bridge = new Bridge()
  const client = await connect(bridge)
  for (const kind of ['input.requested', 'editor.requested', 'choice.requested', 'confirm.requested']) {
    bridge.emit('session_9', { kind, id: 'ui_1', title: 'Your name' })
  }
  expect(client.getSnapshot().interactions).toEqual([])
  const unprojected = client.getSnapshot().diagnostic
  expect(unprojected).toMatch(/Unknown Ordessa event kind: confirm.requested/)
  // A Server event with no contract slot is skipped quietly; an unknown kind still diagnoses, so the two never blur.
  bridge.emit('session_9', { kind: 'workspace.connection', workspaceId: 'ws_1', connection: { state: 'reconnecting' } })
  expect(client.getSnapshot().diagnostic).toBe(unprojected)
  expect(client.getSnapshot().interactions).toEqual([])
  expect(await client.respond('ui_1', { kind: 'text', value: 'x' }).catch((error: unknown) => String(error))).toMatch(/not an answerable approval/)
  expect(bridge.frames('decide')).toEqual([])
  expect(bridge.frames('send')).toEqual([])
  // The whole enum must not collapse because the ordinary kinds have no route: the approval still answers.
  bridge.emit('session_9', { kind: 'approval.requested', approval: { approvalId: 'approval_3', version: 1, operation: { title: 'Run' } } })
  const capabilities = client.getSnapshot().connection.capabilities
  expect(capabilities.interactions).toBe('supported')
  expect([capabilities.models, capabilities.modes]).toEqual(['unsupported', 'unsupported'])
  expect(client.getSnapshot().interactions.at(-1)).toMatchObject({ id: 'approval_3', state: 'pending' })
  client.dispose()
})

it('shows an approval it cannot record as unanswerable instead of a button', async () => {
  const bridge = new Bridge()
  bridge.identity = identityFor(INSTANCE, ROUTES.filter(route => route !== 'approvals.decide'))
  const client = await connect(bridge)
  expect(client.getSnapshot().connection.capabilities.interactions).toBe('unsupported')
  bridge.emit('session_9', { kind: 'approval.requested', approval: { approvalId: 'approval_4', version: 1, operation: { title: 'Run' } } })
  const item = client.getSnapshot().interactions[0]
  expect(item).toMatchObject({ id: 'approval_4', kind: 'approval', state: 'unknown' })
  expect(item.choices).toBeUndefined()
  expect(client.getSnapshot().diagnostic).toMatch(/not answerable/)
  expect(await client.respond('approval_4', { kind: 'choice', choiceId: 'allow' }).catch((error: unknown) => String(error))).toMatch(/not an answerable approval/)
  expect(bridge.frames('decide')).toEqual([])
  client.dispose()
})

it('makes an open run and a pending approval unknown when the event channel drops', async () => {
  const bridge = new Bridge()
  const client = await connect(bridge)
  bridge.emit('session_9', { kind: 'execution.state', sessionId: 'session_9', executionId: 'execution_1', state: 'running' })
  bridge.emit('session_9', { kind: 'approval.requested', approval: { approvalId: 'approval_5', version: 1, operation: { title: 'Run' } } })
  expect(client.getSnapshot().runs['execution_1']).toMatchObject({ status: 'running', stoppable: true })
  bridge.down('event stream closed (4403)')
  expect(client.getSnapshot().runs['execution_1'].status).toBe('unknown')
  expect(client.getSnapshot().interactions[0].state).toBe('unknown')
  expect(await client.respond('approval_5', { kind: 'choice', choiceId: 'allow' }).catch((error: unknown) => String(error))).toMatch(/not an answerable approval/)
  expect(bridge.frames('decide')).toEqual([])
  // A lost channel never verdicts a run: unknown stays unknown, and the stop is refused.
  expect(await client.stop('session_9', 'execution_1').catch((error: unknown) => String(error))).toMatch(/not available to stop/)
  client.dispose()
})

it('maps the wire run states without inventing a verdict the protocol never carries', async () => {
  const bridge = new Bridge()
  const client = await connect(bridge)
  bridge.emit('session_9', { kind: 'execution.state', executionId: 'execution_1', state: 'queued' })
  expect(client.getSnapshot().runs['execution_1']).toMatchObject({ status: 'starting' })
  bridge.emit('session_9', { kind: 'execution.state', executionId: 'execution_1', state: 'running' })
  bridge.responses.set('stop', { outcome: 'stop_requested', executionId: 'execution_1' })
  await client.stop('session_9', 'execution_1')
  // A requested stop is only a request; no message may show a verdict yet.
  expect(client.getSnapshot().runs['execution_1'].status).toBe('stop-requested')
  expect(client.getSnapshot().messages['session_9'] ?? []).toEqual([])
  bridge.emit('session_9', { kind: 'execution.state', executionId: 'execution_1', state: 'stopping' })
  expect(client.getSnapshot().runs['execution_1'].status).toBe('stop-requested')
  // 'stopped' is the Server's own cancelled state, so it confirms the request rather than contradicting it.
  bridge.emit('session_9', { kind: 'execution.state', executionId: 'execution_1', state: 'stopped' })
  expect(client.getSnapshot().runs['execution_1'].status).toBe('cancelled')
  bridge.emit('session_9', { kind: 'message.delta', messageId: 'execution_1', role: 'assistant', text: 'half ' })
  bridge.emit('session_9', { kind: 'message.final', messageId: 'execution_1', role: 'assistant', text: 'half a sentence', displayKind: 'visible' })
  expect(client.getSnapshot().messages['session_9'].at(-1)).toMatchObject({ id: 'execution_1', text: 'half a sentence' })
  bridge.responses.set('stop', { outcome: 'already_finished', executionId: 'execution_2', reason: 'gone' })
  bridge.emit('session_9', { kind: 'execution.state', executionId: 'execution_2', state: 'running' })
  await client.stop('session_9', 'execution_2')
  expect(client.getSnapshot().runs['execution_2'].status).toBe('unknown')
  expect(client.getSnapshot().diagnostic).toMatch(/not confirmed/)
  client.dispose()
})

it('keeps the project selection scoped to what the Server actually offers', async () => {
  const bridge = new Bridge()
  const client = await connect(bridge)
  await client.refreshWorkspaces()
  // The native half never forwards the raw Server environment, so the renderer cannot replay it.
  expect(client.getSnapshot().workspaces).toMatchObject({ state: 'ready', items: [{ id: 'ws_1', normalizedPath: '/repo/app' }] })
  const opened = await client.openWorkspace('ws_1')
  expect(opened).toEqual({ id: 'ws_1', normalizedPath: '/repo/app' })
  expect(client.getSnapshot().workspaces?.selectedWorkspaceId).toBe('ws_1')
  // A refresh that still lists the pick keeps it; only the Server's own answer may change the selection.
  await client.refreshWorkspaces()
  expect(client.getSnapshot().workspaces?.selectedWorkspaceId).toBe('ws_1')
  expect(client.getSnapshot().diagnostic).toBeUndefined()
  // A project the Server stopped listing is never kept as a live selection.
  bridge.responses.set('projects', [{ id: 'ws_2', normalizedPath: '/repo/other' }])
  await client.refreshWorkspaces()
  expect(client.getSnapshot().workspaces?.state).toBe('ready')
  expect(client.getSnapshot().workspaces?.selectedWorkspaceId).toBeUndefined()
  expect(client.getSnapshot().diagnostic).toMatch(/no longer offered/)
  // FC-0032: a refused revalidation clears the pick instead of leaving one that could still unlock Send.
  bridge.errors.set('openProject', new Error('project-invalid: the project is archived'))
  expect(await client.openWorkspace('ws_2').catch((error: unknown) => String(error))).toMatch(/archived/)
  expect(client.getSnapshot().workspaces?.selectedWorkspaceId).toBeUndefined()
  client.dispose()
})

it('clears the pick behind a first send the Server refused for a lost project, and only that one', async () => {
  const bridge = new Bridge()
  const client = await connect(bridge)
  await client.refreshWorkspaces()
  await client.openWorkspace('ws_1')
  expect(client.getSnapshot().workspaces?.selectedWorkspaceId).toBe('ws_1')
  // FC-0057: this is the Electron-shaped rejection, so the marker is only readable past the IPC wrapper,
  // and what reaches the renderer stays a stale-pick prompt rather than a channel complaint.
  bridge.errors.set('createAndSend', new Error("Error invoking remote method 'agent-native': Error: project-invalid: the Server will not run in the selected project (NOT_FOUND/LOCAL_PATH_MISSING)"))
  expect(await client.createAndSend('ws_1', 'text', 'req_abc123').catch((error: unknown) => String(error)))
    .toMatch(/LOCAL_PATH_MISSING/)
  expect(client.getSnapshot().workspaces?.selectedWorkspaceId).toBeUndefined()
  expect(client.getSnapshot().workspaces?.state).toBe('ready')
  expect(client.getSnapshot().workspaces?.items).toHaveLength(1)
  expect(client.getSnapshot().diagnostic).toMatch(/^project-invalid: /)
  expect(client.getSnapshot().sessions).toEqual([])
  expect(bridge.frames('createAndSend')).toHaveLength(1)
  // A refusal that says nothing about the project keeps the pick: re-selecting cannot answer it.
  await client.openWorkspace('ws_1')
  bridge.errors.set('createAndSend', new Error('Ordessa operation timed out: createAndSend'))
  expect(await client.createAndSend('ws_1', 'text', 'req_abc123').catch((error: unknown) => String(error))).toMatch(/timed out/)
  expect(client.getSnapshot().workspaces?.selectedWorkspaceId).toBe('ws_1')
  client.dispose()
})

it('opens a session from its log and refuses the operations this product has no route for', async () => {
  const bridge = new Bridge()
  const client = await connect(bridge)
  bridge.responses.set('history', { outcome: 'snapshot', resumeCursor: 'w1:session_9:12:head', olderCursor: 'w1o:session_9:1:old', frames: [
    { eventId: 'event_1', sessionId: 'session_9', seq: 1, cursor: 'w1:session_9:1:a', emittedAt: '2026-09-23T00:00:00Z',
      event: { kind: 'message.final', messageId: 'message_1', role: 'user', text: 'start', displayKind: 'visible' } },
    { eventId: 'event_2', sessionId: 'session_9', seq: 2, cursor: 'w1:session_9:2:b', emittedAt: '2026-09-23T00:00:01Z',
      event: { kind: 'message.final', messageId: 'message_hidden', role: 'assistant', text: 'internal', displayKind: 'hidden' } },
    { eventId: 'event_3', sessionId: 'session_9', seq: 3, cursor: 'w1:session_9:3:c', emittedAt: '2026-09-23T00:00:02Z',
      event: { kind: 'tool.update', toolCallId: 'call_1', tool: 'bash', state: 'completed', resultExcerpt: 'ok' } },
    { eventId: 'event_4', sessionId: 'session_9', seq: 4, cursor: 'w1:session_9:4:d', emittedAt: '2026-09-23T00:00:03Z',
      event: { kind: 'message.final', messageId: 'message_2', role: 'system', text: 'notice', displayKind: 'visible' } },
  ] })
  await client.openSession('session_9')
  expect(bridge.frame('history').params).toEqual({ sessionId: 'session_9' })
  // Only the live resume cursor may rejoin the stream, never the older-history one.
  expect(bridge.frame('stream').params).toEqual({ sessionId: 'session_9', cursor: 'w1:session_9:12:head' })
  const messages = client.getSnapshot().messages['session_9']
  expect(messages.map(message => message.id)).toEqual(['message_1', 'ordessa-tool-call_1'])
  expect(messages[1].tools?.[0]).toMatchObject({ id: 'call_1', name: 'bash', status: 'completed', result: 'ok' })
  bridge.deliver({ method: 'unknown-frame' })
  expect(client.getSnapshot().diagnostic).toMatch(/Unknown Ordessa native event/)
  expect(await client.newSession().catch((error: unknown) => String(error))).toMatch(/first send into a project/)
  expect(await client.setOption('model', 'x').catch((error: unknown) => String(error))).toMatch(/does not offer/)
  client.dispose()
  expect(bridge.closed.at(-1)).toBe('instance-1')
})
