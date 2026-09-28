// 014 P-C seam proofs at the FACADE level (PC-2/PC-3/PC-4/PC-5):
// command catalog passthrough, attachment prepare→ref→carry chain, the
// fail-closed admission precheck, the legacy resolve→accepted compatibility
// rule, and the runtimeGeneration snapshot projection. Every counterexample
// (absent member, not-ready admission, unknown reference, link down) must
// fail closed with a typed reason — never fake green.
import { afterEach, describe, expect, it } from 'vitest'
import { OwnedResources } from '@ordessa/extension-api'
import { createConnections } from '../../../../packages/desktop-platform/connections/src/index'
import { createAgentConnections } from '../../../../plugins/agent/connections/src/entry'
import { createAgentSessions } from '../../../../plugins/agent/sessions/src/model'
import type {
  AgentAdmissionEvidence, AgentAttachmentCapabilities, AgentAttachmentPreparation, AgentClient, AgentCommandCatalog,
  AgentNativeCommandCatalog, AgentPreparedAttachment, AgentSnapshot, AgentSubmissionOutcome,
} from '../../../../plugins/agent/contracts/src/contract'

const capabilities = { history: 'supported', reasoning: 'unknown', tools: 'unknown', stop: 'supported',
  interactions: 'unknown', models: 'unknown', modes: 'unknown', workspaces: 'supported' } as const

interface SeamOptions {
  commands?: (sessionKey: string) => AgentNativeCommandCatalog
  attachments?: {
    capabilities?: (sessionId: string) => Promise<AgentAttachmentCapabilities>
    prepare?: (sessionId: string, sourceId: string, idempotencyKey: string) => Promise<AgentPreparedAttachment>
    release?: (sessionId: string, preparedId: string) => Promise<void>
    carry?: (sessionId: string, text: string, attachments: readonly AgentPreparedAttachment[]) => Promise<AgentSubmissionOutcome>
  }
  admission?: () => AgentAdmissionEvidence | undefined
  sendOutcome?: AgentSubmissionOutcome | void
  sendThrows?: Error
}

/** A seam-rich fake client: every optional contract member is opt-in so the
 * tests can prove the facade's honest degradation when members are absent. */
function seamClient(options: SeamOptions = {}) {
  let snapshot: AgentSnapshot = {
    connection: { id: 'A', title: 'A', status: 'connected', serverInstanceId: 'https://s1', capabilities },
    sessions: [{ id: 'S1', title: 'Chat' }],
    sessionList: 'ready', messages: {}, runs: {}, interactions: [], options: [],
    workspaces: { state: 'ready', items: [{ id: '/srv/a', normalizedPath: '/srv/a' }], selectedWorkspaceId: '/srv/a' },
  }
  const listeners = new Set<() => void>()
  const write = (patch: Partial<AgentSnapshot>) => {
    snapshot = { ...snapshot, ...patch }
    for (const listener of [...listeners]) listener()
  }
  const calls: { send: { sessionId: string; text: string }[]; carry: { sessionId: string; text: string; refs: readonly AgentPreparedAttachment[] }[] } = {
    send: [], carry: [],
  }
  const client: AgentClient = {
    get isDisposed() { return false },
    dispose() { listeners.clear() },
    getSnapshot: () => snapshot,
    subscribe(listener) { listeners.add(listener); return () => { listeners.delete(listener) } },
    async refreshSessions() {}, async newSession() { return 'S1' }, async openSession(id) { write({ selectedSessionId: id }) },
    async stop() {}, async respond() {}, async setOption() {},
    async send(sessionId, text) {
      calls.send.push({ sessionId, text })
      if (options.sendThrows) throw options.sendThrows
      return options.sendOutcome
    },
    refreshWorkspaces: undefined,
    openWorkspace: undefined,
    addWorkspace: undefined,
  }
  if (options.commands) client.getNativeCommands = sessionKey => options.commands!(sessionKey)
  if (options.attachments) {
    const a = options.attachments
    const defaultCaps = async (): Promise<AgentAttachmentCapabilities> => ({ kind: 'available',
      mimeTypes: ['image/png'], uriSchemes: ['acp:'], maxBytes: 1024, maxCount: 4 })
    client.attachmentCapabilities = sessionId => (a.capabilities ?? defaultCaps)(sessionId)
    const defaultPrepare = async (_s: string, source: string): Promise<AgentPreparedAttachment> =>
      ({ preparedId: `p-${source}`, name: `${source}.bin`, uri: `acp://prepared/${source}`,
        mimeType: 'image/png', sha256: 'a'.repeat(64), byteLength: 7 })
    client.prepareAttachment = (sessionId, sourceId, idempotencyKey) =>
      (a.prepare ?? defaultPrepare)(sessionId, sourceId, idempotencyKey)
    const defaultRelease = async (): Promise<void> => {}
    client.releasePreparedAttachment = (sessionId, preparedId) => (a.release ?? defaultRelease)(sessionId, preparedId)
    const carry = a.carry
    if (carry) client.submitWithAttachments = (sessionId, text, refs) => {
      calls.carry.push({ sessionId, text, refs })
      return carry(sessionId, text, refs)
    }
  }
  if (options.admission) client.admissionEvidence = options.admission
  return { client, write, calls }
}

const cleanup: (() => Promise<void>)[] = []
afterEach(async () => { for (const fn of cleanup.splice(0).reverse()) await fn() })

async function harness(client: AgentClient) {
  const scopes = { registry: new OwnedResources(), sessions: new OwnedResources(), connectors: new OwnedResources() }
  cleanup.push(async () => { scopes.sessions.dispose(); scopes.connectors.dispose(); scopes.registry.dispose() })
  const registry = createAgentConnections(scopes.registry, createConnections(scopes.registry))
  registry.forScope(scopes.connectors).add({ id: 'A', title: 'A', connect: async () => client })
  const sessions = createAgentSessions(scopes.sessions, registry)
  await sessions.selectConnection('A')
  await sessions.openSession('S1')
  return sessions
}

describe('PC-2 command catalog passthrough', () => {
  it('available catalogs pass through with the connector commands', async () => {
    const { client } = seamClient({ commands: key => key === 'S1'
      ? { kind: 'available', connectionId: 'c1', nativeSessionId: 'n1', commands: [{ name: 'compact', description: 'Summarize', inputHint: 'focus?' }] }
      : { kind: 'absent' } })
    const sessions = await harness(client)
    expect(sessions.commandCatalog('S1')).toEqual({
      kind: 'available', connectionId: 'c1', nativeSessionId: 'n1',
      commands: [{ name: 'compact', description: 'Summarize', inputHint: 'focus?' }],
    })
  })

  it('a connector without the member and an unobserved session answer absent, never a fake menu', async () => {
    const { client } = seamClient()
    const sessions = await harness(client)
    expect(sessions.commandCatalog('S1')).toEqual({ kind: 'absent' })
    expect(sessions.commandCatalog('no-such-key')).toEqual({ kind: 'absent' })
  })

  it('every connector unknown verdict becomes a typed error carrying the reason', async () => {
    for (const reason of ['malformed', 'stale-session', 'channel-down', 'unobservable'] as const) {
      const { client } = seamClient({ commands: () => ({ kind: 'unknown', reason }) })
      const sessions = await harness(client)
      expect(sessions.commandCatalog('S1')).toEqual({ kind: 'error', reason })
    }
  })
})

describe('PC-3 attachment seam (plugin half)', () => {
  it('a client without the full chain answers absent with the S-05 reason — partial surfaces never activate', async () => {
    const { client } = seamClient({ attachments: { capabilities: async () => ({ kind: 'available',
      mimeTypes: ['image/png'], uriSchemes: ['acp:'], maxBytes: 8, maxCount: 1 }), prepare: async () => { throw Error('unreachable') } } })
    const sessions = await harness(client) // capabilities+prepare present, release/carry absent
    expect(sessions.attachments.capability('S1')).toEqual({
      kind: 'absent', reason: '当前连接未提供附件传输通道（生产 prepare owner 缺席，S-05）。',
    })
    const preparation = await sessions.attachments.prepare({ sessionId: 'S1', sourceId: 'x', idempotencyKey: 'k1' })
    expect(preparation.kind).toBe('refused')
  })

  it('a draft (no native session) answers absent with its reason; a live session is available', async () => {
    const { client } = seamClient({ attachments: { carry: async () => ({ kind: 'accepted' }) } })
    const sessions = await harness(client)
    expect(sessions.attachments.capability()).toEqual({
      kind: 'absent', reason: '新会话还没有原生活动会话，附件在第一条消息发出后可用。',
    })
    expect(sessions.attachments.capability('S1')).toEqual({ kind: 'available' })
  })

  it('prepare registers the opaque token; the carry path receives the SAME prepared reference', async () => {
    const prepared: AgentPreparedAttachment = { preparedId: 'p-1', name: 'a.png', uri: 'acp://prepared/1',
      mimeType: 'image/png', sha256: 'b'.repeat(64), byteLength: 9 }
    const { client, calls } = seamClient({ attachments: {
      prepare: async () => prepared,
      carry: async (_s, _t, refs) => ({ kind: 'accepted' }),
    } })
    const sessions = await harness(client)
    const outcome = await sessions.attachments.prepare({ sessionId: 'S1', sourceId: 'img', idempotencyKey: 'k-1' })
    expect(outcome).toEqual({ kind: 'prepared', reference: prepared })
    // The token Chat holds is the prepared id; the carry expansion must be the
    // full reference with the SAME sha256 (the A06 round trip's facade half).
    const carried = await sessions.send('with attachment', ['p-1'])
    expect(carried).toEqual({ kind: 'accepted' })
    expect(calls.carry[0]).toMatchObject({ sessionId: 'S1', text: 'with attachment' })
    expect(calls.carry[0]!.refs).toEqual([prepared])
  })

  it('an unknown reference refuses before any client call — refs are never dropped', async () => {
    const { client, calls } = seamClient({ attachments: { carry: async () => ({ kind: 'accepted' }) } })
    const sessions = await harness(client)
    const outcome = await sessions.send('x', ['bogus'])
    expect(outcome).toEqual({ kind: 'refused', code: 'INVALID_REQUEST', reason: 'unknown prepared attachment reference' })
    expect(calls.carry).toEqual([])
  })

  it('a refused carry passes through typed; a lost answer during carry becomes unknown', async () => {
    const prepared: AgentPreparedAttachment = { preparedId: 'p-1', name: 'a.png', uri: 'acp://prepared/1',
      mimeType: 'image/png', sha256: 'c'.repeat(64), byteLength: 3 }
    const refused = seamClient({ attachments: {
      prepare: async () => prepared,
      carry: async () => ({ kind: 'refused', code: 'BUSY', reason: 'channel busy' }),
    } })
    const sessions = await harness(refused.client)
    await sessions.attachments.prepare({ sessionId: 'S1', sourceId: 'img', idempotencyKey: 'k' })
    expect(await sessions.send('x', ['p-1'])).toEqual({ kind: 'refused', code: 'BUSY', reason: 'channel busy' })

    const dropped = seamClient({ attachments: {
      prepare: async () => prepared,
      carry: async () => { throw Error('connection lost') },
    } })
    dropped.client.getSnapshot && (dropped.write({ connection: { ...dropped.client.getSnapshot().connection, status: 'disconnected' } }))
    const sessions2 = await harness(dropped.client)
    await sessions2.attachments.prepare({ sessionId: 'S1', sourceId: 'img', idempotencyKey: 'k' })
    const unknown = await sessions2.send('x', ['p-1'])
    expect(unknown.kind).toBe('unknown')
    expect((unknown as { operationId: string }).operationId).toBeTruthy()
  })

  it('release removes the token from the registry and reaches the client with the prepared session', async () => {
    const prepared: AgentPreparedAttachment = { preparedId: 'p-1', name: 'a.png', uri: 'acp://prepared/1',
      mimeType: 'image/png', sha256: 'd'.repeat(64), byteLength: 3 }
    const released: { sessionId: string; preparedId: string }[] = []
    const { client } = seamClient({ attachments: {
      prepare: async () => prepared,
      carry: async () => ({ kind: 'accepted' }),
      release: async (sessionId, preparedId) => { released.push({ sessionId, preparedId }) },
    } })
    const sessions = await harness(client)
    await sessions.attachments.prepare({ sessionId: 'S1', sourceId: 'img', idempotencyKey: 'k' })
    await sessions.attachments.release('p-1', 'draft-removed')
    expect(released).toEqual([{ sessionId: 'S1', preparedId: 'p-1' }])
    // The token is gone: a later send can no longer resolve it.
    expect(await sessions.send('x', ['p-1'])).toMatchObject({ kind: 'refused', code: 'INVALID_REQUEST' })
  })
})

describe('PC-4 fail-closed admission precheck', () => {
  const evidence = (over: Partial<AgentAdmissionEvidence> = {}): AgentAdmissionEvidence => ({
    connectionId: 'c1', nativeSessionId: 'n1', runtimeGeneration: 5, admissionSupported: true,
    q5Ready: true, chatApiReady: true, outputInProgress: false, ...over,
  })

  it('not-ready admission evidence refuses BEFORE any send reaches the client (S-05/S-06)', async () => {
    for (const over of [{ admissionSupported: false }, { q5Ready: false }, { chatApiReady: false }]) {
      const { client, calls } = seamClient({ admission: () => evidence(over) })
      const sessions = await harness(client)
      const outcome = await sessions.send('hello')
      expect(outcome).toEqual({ kind: 'refused', code: 'CAPABILITY_UNSUPPORTED', reason: 'ACP backend admission dependencies are unavailable' })
      expect(calls.send).toEqual([])
    }
  })

  it('an output in progress refuses BUSY before the wire', async () => {
    const { client, calls } = seamClient({ admission: () => evidence({ outputInProgress: true }) })
    const sessions = await harness(client)
    expect(await sessions.send('hello')).toEqual({ kind: 'refused', code: 'BUSY', reason: 'ACP output is still in progress' })
    expect(calls.send).toEqual([])
  })

  it('ready evidence proceeds; a client with no observable evidence takes the legacy path (registered S-05 limitation)', async () => {
    const ready = seamClient({ admission: () => evidence(), sendOutcome: { kind: 'accepted' } })
    const sessions = await harness(ready.client)
    expect(await sessions.send('hello')).toEqual({ kind: 'accepted' })
    expect(ready.calls.send).toHaveLength(1)

    const legacy = seamClient() // no admissionEvidence member at all
    const sessions2 = await harness(legacy.client)
    expect(await sessions2.send('hello')).toEqual({ kind: 'accepted' }) // void resolve → send-path acceptance
    expect(legacy.calls.send).toHaveLength(1)
  })

  it('a link-down continuation send becomes unknown; a typed refusal keeps its code', async () => {
    const dropped = seamClient({ sendThrows: Error('socket gone') })
    const sessions = await harness(dropped.client)
    dropped.write({ connection: { ...dropped.client.getSnapshot().connection, status: 'disconnected' } })
    const unknown = await sessions.send('hello')
    expect(unknown.kind).toBe('unknown')

    const refused = seamClient({ sendThrows: Error('the harness refused the turn') })
    const sessions2 = await harness(refused.client)
    const outcome = await sessions2.send('hello')
    expect(outcome).toEqual({ kind: 'refused', code: 'SUBMISSION_REFUSED', reason: 'the harness refused the turn' })
  })
})

describe('PC-5 runtimeGeneration snapshot projection', () => {
  it('the selected client admission generation lands in the workspace snapshot; absence stays absent', async () => {
    const { client } = seamClient({ admission: () => ({
      connectionId: 'c1', nativeSessionId: 'n1', runtimeGeneration: 7, admissionSupported: true,
      q5Ready: true, chatApiReady: true, outputInProgress: false,
    }) })
    const sessions = await harness(client)
    expect(sessions.getSnapshot().runtimeGeneration).toBe(7)

    const bare = seamClient()
    const sessions2 = await harness(bare.client)
    expect(sessions2.getSnapshot().runtimeGeneration).toBeUndefined()
  })
})
