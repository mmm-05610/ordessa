import { afterEach, expect, it } from 'vitest'
import { OwnedResources } from '@ordessa/extension-api'
import { createConnections } from '../../../../packages/desktop-platform/connections/src/index'
import { createAgentConnections } from '../../../../plugins/agent/connections/src/entry'
import { createAgentSessions } from '../../../../plugins/agent/sessions/src/model'
import type { AgentClient, AgentSnapshot } from '../../../../plugins/agent/contracts/src/contract'

const capabilities = { history: 'supported', reasoning: 'unknown', tools: 'unknown', stop: 'supported',
  interactions: 'unknown', models: 'unknown', modes: 'unknown', workspaces: 'supported' } as const

interface ProjectCall { workspaceId: string; text: string; requestId: string }

/** Reactive fake backend-capable client; every createAndSend/openWorkspace is recorded and
 * `fails` stays mutable so a project can become invalid after it was remembered. */
function projectClient(id: string, serverInstanceId: string | undefined, options: { rejectFirstSend?: boolean; ghostFirstSend?: boolean; drop?: string } = {}) {
  let snapshot: AgentSnapshot = {
    connection: { id, title: id, status: 'connected', ...(serverInstanceId ? { serverInstanceId } : {}), capabilities },
    sessions: [{ id: 'E1', title: 'Existing chat', workspaceId: '/srv/old' }],
    sessionList: 'ready', messages: {}, runs: {}, interactions: [], options: [],
    workspaces: { state: 'ready', items: [{ id: '/srv/a', normalizedPath: '/srv/a' }, { id: '/srv/b', normalizedPath: '/srv/b' }].filter(item => item.id !== options.drop) },
  }
  const listeners = new Set<() => void>()
  const write = (patch: Partial<AgentSnapshot>) => {
    snapshot = { ...snapshot, ...patch }
    for (const listener of [...listeners]) listener()
  }
  const fails = new Set<string>()
  const opens: string[] = []
  const sends: ProjectCall[] = []
  const continuations: { sessionId: string; text: string }[] = []
  let sendAttempt = 0
  const client: AgentClient = {
    get isDisposed() { return false },
    dispose() { listeners.clear() },
    getSnapshot: () => snapshot,
    subscribe(listener) { listeners.add(listener); return () => { listeners.delete(listener) } },
    async refreshSessions() {}, async newSession() { throw Error('CP UI must not call newSession') },
    async openSession(session) { write({ selectedSessionId: session }) },
    async send(sessionId, text) { continuations.push({ sessionId, text }); write({ messages: { ...snapshot.messages, [sessionId]: [{ id: 'm', role: 'user', text }] } }) },
    async stop() {}, async respond() {}, async setOption() {},
    async refreshWorkspaces() {},
    async openWorkspace(workspaceId) {
      opens.push(workspaceId)
      if (fails.has(workspaceId)) throw Error(`project unavailable: ${workspaceId}`)
      write({ workspaces: { ...snapshot.workspaces!, selectedWorkspaceId: workspaceId } })
      return { id: workspaceId, normalizedPath: workspaceId }
    },
    async createAndSend(workspaceId, text, requestId) {
      sends.push({ workspaceId, text, requestId })
      sendAttempt += 1
      if (options.rejectFirstSend && sendAttempt === 1) throw Error('outcome unknown after disconnect')
      if (options.ghostFirstSend && sendAttempt === 1) return { sessionId: 'ghost' } // "accepted" while the snapshot still lacks it (FC-0031)
      write({
        selectedSessionId: 'R1',
        sessions: [...snapshot.sessions, { id: 'R1', title: text.slice(0, 12), workspaceId }],
      })
      return { sessionId: 'R1' } // the client only resolves with the accepted real id (FC-0031)
    },
  }
  return { client, fails, calls: { opens, sends, continuations }, setWorkspaces: (selected: string | undefined) =>
    write({ workspaces: { ...snapshot.workspaces!, selectedWorkspaceId: selected } }) }
}

const cleanup: (() => Promise<void>)[] = []
afterEach(async () => { for (const fn of cleanup.splice(0).reverse()) await fn() })

async function harness(...connectors: { id: string; build: () => AgentClient }[]) {
  const scopes = { registry: new OwnedResources(), sessions: new OwnedResources(), connectors: new OwnedResources() }
  cleanup.push(async () => { scopes.sessions.dispose(); scopes.connectors.dispose(); scopes.registry.dispose() })
  const registry = createAgentConnections(scopes.registry, createConnections(scopes.registry))
  for (const connector of connectors)
    registry.forScope(scopes.connectors).add({ id: connector.id, title: connector.id, connect: async () => connector.build() })
  return createAgentSessions(scopes.sessions, registry)
}

it('New session and Discard produce zero backend calls and never a temporary session (FC-0021)', async () => {
  const a = projectClient('A', 'https://s1')
  const sessions = await harness({ id: 'A', build: () => a.client })
  await sessions.selectConnection('A')
  expect(sessions.getSnapshot().draft).toMatchObject({ active: false, canSend: false, blockReason: 'no-project', workspaceId: undefined })
  sessions.startDraft!()
  expect(sessions.getSnapshot().draft).toMatchObject({ active: true })
  expect(a.calls.sends).toEqual([]) // positive control: no createAndSend yet
  sessions.discardDraft!()
  expect(sessions.getSnapshot().draft?.active).toBe(false)
  expect(a.calls.sends).toHaveLength(0)
  expect(a.calls.opens).toHaveLength(0)
})

it('first send is blocked without a valid project and reaches no client create (拦截反例)', async () => {
  const a = projectClient('A', 'https://s1')
  const sessions = await harness({ id: 'A', build: () => a.client })
  await sessions.selectConnection('A')
  sessions.startDraft!()
  expect(sessions.getSnapshot().draft).toMatchObject({ active: true, canSend: false, blockReason: 'no-project' })
  await expect(sessions.send('hello')).rejects.toThrow('project gate: no-project')
  expect(a.calls.sends).toHaveLength(0)
})

it('restores the last valid project for the same Server instance and revalidates it on selection', async () => {
  const a = projectClient('A', 'https://s1')
  a.setWorkspaces(undefined)
  const sessions = await harness({ id: 'A', build: () => a.client })
  await sessions.selectConnection('A')
  await sessions.selectWorkspace!('/srv/a')
  expect(sessions.getSnapshot().draft).toMatchObject({ workspaceId: '/srv/a', canSend: true })
  sessions.startDraft!()
  await sessions.send('keep me') // accepted first send ends the draft
  expect(a.calls.sends).toHaveLength(1)
  expect(a.calls.sends[0]).toMatchObject({ workspaceId: '/srv/a', text: 'keep me' })
  expect(sessions.getSnapshot().draft?.active).toBe(false)
  // Re-selection triggers a revalidation open, not a fresh project state.
  a.setWorkspaces(undefined)
  await sessions.selectConnection('A')
  expect(a.calls.opens.at(-1)).toBe('/srv/a')
  expect(sessions.getSnapshot().draft).toMatchObject({ workspaceId: '/srv/a', canSend: true })
})

it('an invalid restored project clears the selection and blocks sends until reselect', async () => {
  const a = projectClient('A', 'https://s1')
  const sessions = await harness({ id: 'A', build: () => a.client })
  await sessions.selectConnection('A')
  await sessions.selectWorkspace!('/srv/a') // valid at first, so it is remembered per instance
  a.fails.add('/srv/a') // the Server no longer honors it
  await sessions.selectConnection('A') // revalidation on selection detects that
  expect(sessions.getSnapshot().draft).toMatchObject({ canSend: false, blockReason: 'project-invalid' })
  sessions.startDraft!()
  await expect(sessions.send('x')).rejects.toThrow('project gate: project-invalid')
  expect(a.calls.sends.filter(call => call.text === 'x')).toHaveLength(0)
  // Recovery: a valid reselection re-opens the gate and forgets the invalid record.
  await sessions.selectWorkspace!('/srv/b')
  expect(sessions.getSnapshot().draft).toMatchObject({ canSend: true, workspaceId: '/srv/b' })
})

it('project records are isolated per Server instance, never shared across connections (跨连接不串)', async () => {
  const a1 = projectClient('A1', 'https://shared')
  const a2 = projectClient('A2', 'https://other')
  a2.setWorkspaces(undefined)
  const sessions = await harness({ id: 'A1', build: () => a1.client }, { id: 'A2', build: () => a2.client })
  await sessions.selectConnection('A1')
  await sessions.selectWorkspace!('/srv/a')
  await sessions.selectConnection('A2')
  expect(a2.calls.opens).toHaveLength(0) // no restore aimed at the other Server
  expect(sessions.getSnapshot().draft).toMatchObject({ workspaceId: undefined, canSend: false, blockReason: 'no-project' })
})

it('an unknown first-send outcome keeps one requestId and never creates a second session id', async () => {
  const a = projectClient('A', 'https://s1', { rejectFirstSend: true })
  const sessions = await harness({ id: 'A', build: () => a.client })
  await sessions.selectConnection('A')
  await sessions.selectWorkspace!('/srv/a')
  sessions.startDraft!()
  await expect(sessions.send('hi')).rejects.toThrow('outcome unknown')
  expect(sessions.getSnapshot().draft?.active).toBe(true) // draft survives the failure; F3 keeps the text
  await sessions.send('hi')
  expect(a.calls.sends).toHaveLength(2)
  expect(a.calls.sends[0]!.requestId).toBe(a.calls.sends[1]!.requestId)
  expect(a.calls.sends[1]).toMatchObject({ workspaceId: '/srv/a', text: 'hi' })
  expect(sessions.getSnapshot().draft?.active).toBe(false)
  expect(a.client.getSnapshot().sessions.filter(s => s.id === 'R1')).toHaveLength(1) // one real id entered history
})

it('continuing an existing session never consults the draft gate or a new create (续聊沿原项目)', async () => {
  const a = projectClient('A', 'https://s1')
  const sessions = await harness({ id: 'A', build: () => a.client })
  await sessions.selectConnection('A')
  await sessions.openSession('E1')
  await sessions.selectWorkspace!('/srv/elsewhere') // a global selection change must not migrate the binding
  await sessions.send('follow-up')
  expect(a.calls.sends).toHaveLength(0)
  expect(a.client.getSnapshot().messages.E1?.at(-1)?.text).toBe('follow-up')
})

/** A process-independent localStorage double so one identity's record can be observed from a
 * freshly built facade — the simulated desktop restart the FC-0030 gate demands. */
function stubStorage() {
  const entries = new Map<string, string>()
  Object.defineProperty(globalThis, 'localStorage', { configurable: true, value: {
    getItem: (key: string) => entries.get(key) ?? null,
    setItem: (key: string, value: string) => { entries.set(key, value) },
    removeItem: (key: string) => { entries.delete(key) },
  } })
  return { entries, clear: () => Object.defineProperty(globalThis, 'localStorage', { configurable: true, value: undefined }) }
}

it('the last valid project survives a simulated renderer restart and is revalidated before use (FC-0030)', async () => {
  const storage = stubStorage()
  try {
    const a = projectClient('A', 'https://s1')
    const first = await harness({ id: 'A', build: () => a.client })
    await first.selectConnection('A')
    await first.selectWorkspace!('/srv/a')
    expect(storage.entries.get('ordessa.agent.project.https://s1')).toBe('/srv/a') // non-secret id→id only
    const b = projectClient('B', 'https://s1')
    b.setWorkspaces(undefined)
    const second = await harness({ id: 'B', build: () => b.client })
    await second.selectConnection('B')
    expect(b.calls.opens.at(-1)).toBe('/srv/a') // recalled from storage, then revalidated via open
    expect(second.getSnapshot().draft).toMatchObject({ workspaceId: '/srv/a', canSend: true })
  } finally { storage.clear() }
})

it('a record never restores across Server identities, and storage loss forces manual selection (不串+缺storage)', async () => {
  const storage = stubStorage()
  try {
    const a = projectClient('A', 'https://s1|one')
    const first = await harness({ id: 'A', build: () => a.client })
    await first.selectConnection('A')
    await first.selectWorkspace!('/srv/a')
    // Same origin but a different serverId: a new Server root must not inherit the choice.
    const b = projectClient('B', 'https://s1|two')
    b.setWorkspaces(undefined)
    const second = await harness({ id: 'B', build: () => b.client })
    await second.selectConnection('B')
    expect(b.calls.opens).toHaveLength(0)
    expect(second.getSnapshot().draft).toMatchObject({ workspaceId: undefined, canSend: false, blockReason: 'no-project' })
    // Same identity but storage and memory gone: manual selection is required again, sends stay blocked.
    storage.entries.clear()
    const c = projectClient('C', 'https://s1|one')
    c.setWorkspaces(undefined)
    const third = await harness({ id: 'C', build: () => c.client })
    await third.selectConnection('C')
    expect(c.calls.opens).toHaveLength(0)
    expect(third.getSnapshot().draft?.canSend).toBe(false)
    await third.selectWorkspace!('/srv/a') // manual recovery works
    expect(third.getSnapshot().draft).toMatchObject({ canSend: true, workspaceId: '/srv/a' })
  } finally { storage.clear() }
})

it('a stored id no longer listed unarchived blocks sends without opening it, and nothing restores without identity', async () => {
  const storage = stubStorage()
  try {
    const a = projectClient('A', 'https://s1')
    const first = await harness({ id: 'A', build: () => a.client })
    await first.selectConnection('A')
    await first.selectWorkspace!('/srv/b')
    // A Server that no longer lists the archived/removed project must not even be asked to open it.
    const b = projectClient('B', 'https://s1', { drop: '/srv/b' })
    b.setWorkspaces(undefined)
    const second = await harness({ id: 'B', build: () => b.client })
    await second.selectConnection('B')
    expect(b.calls.opens).toHaveLength(0)
    expect(second.getSnapshot().draft).toMatchObject({ canSend: false, blockReason: 'project-invalid' })
    await second.selectWorkspace!('/srv/a')
    expect(second.getSnapshot().draft).toMatchObject({ canSend: true, workspaceId: '/srv/a' })
  } finally { storage.clear() }
  // Without an authenticated Server identity there is no restore path at all — live selection only.
  const live = projectClient('L', undefined)
  const sessions = await harness({ id: 'L', build: () => live.client })
  await sessions.selectConnection('L')
  await sessions.selectWorkspace!('/srv/a')
  expect(sessions.getSnapshot().draft).toMatchObject({ canSend: true, workspaceId: '/srv/a' })
  const fresh = projectClient('L2', undefined)
  fresh.setWorkspaces(undefined)
  const later = await harness({ id: 'L2', build: () => fresh.client })
  await later.selectConnection('L2')
  expect(fresh.calls.opens).toHaveLength(0)
  expect(later.getSnapshot().draft).toMatchObject({ canSend: false, blockReason: 'no-project' })
})

it('an accepted-but-unverifiable first send never lists a ghost session and keeps the same requestId for the retry (FC-0031)', async () => {
  const a = projectClient('A', 'https://s1', { ghostFirstSend: true })
  const sessions = await harness({ id: 'A', build: () => a.client })
  await sessions.selectConnection('A')
  await sessions.selectWorkspace!('/srv/a')
  sessions.startDraft!()
  await expect(sessions.send('hi')).rejects.toThrow('first-send session mismatch')
  expect(a.client.getSnapshot().sessions.map(s => s.id)).not.toContain('ghost') // no fabricated history entry or draft end
  expect(sessions.getSnapshot().draft?.active).toBe(true)
  await sessions.send('hi') // a retry replays the same requestId; only the snapshot-confirmed id ends the draft
  expect(a.calls.sends).toHaveLength(2)
  expect(a.calls.sends[0]!.requestId).toBe(a.calls.sends[1]!.requestId)
  expect(sessions.getSnapshot().draft?.active).toBe(false)
  expect(a.client.getSnapshot().sessions.filter(s => s.id === 'R1')).toHaveLength(1)
})

it('draft first send reaches createAndSend exactly once and never the previously open session (C-0030 拦截反例)', async () => {
  const a = projectClient('A', 'https://s1')
  const sessions = await harness({ id: 'A', build: () => a.client })
  await sessions.selectConnection('A')
  await sessions.openSession('E1') // an old session is selected before New session is clicked
  await sessions.selectWorkspace!('/srv/a')
  sessions.startDraft!()
  expect(a.client.getSnapshot().selectedSessionId).toBe('E1') // startDraft deliberately keeps it for discard-restore
  await sessions.send('draft text')
  expect(a.calls.sends).toHaveLength(1)
  expect(a.calls.continuations).toHaveLength(0) // no call to client.send(E1) while the draft is active
  expect(a.calls.sends[0]).toMatchObject({ workspaceId: '/srv/a', text: 'draft text' })
  expect(a.client.getSnapshot().messages.E1).toBeUndefined() // the old session never captured the draft text
  expect(a.client.getSnapshot()).toMatchObject({ selectedSessionId: 'R1' })
  const draft = sessions.getSnapshot().draft
  expect(draft?.active).toBe(false)
  expect(draft?.endedBy).toBeUndefined() // an accepted send is distinguishable from discard/away
  await sessions.openSession('E1')
  await sessions.send('existing follow-up')
  expect(a.calls.continuations).toEqual([{ sessionId: 'E1', text: 'existing follow-up' }]) // continuation remains available after draft success
  expect(a.calls.sends).toHaveLength(1)
})

it('discardDraft restores the previously selected session in place and reports endedBy discarded (恢复定义)', async () => {
  const a = projectClient('A', 'https://s1')
  const sessions = await harness({ id: 'A', build: () => a.client })
  await sessions.selectConnection('A')
  await sessions.openSession('E1')
  await sessions.selectWorkspace!('/srv/a')
  sessions.startDraft!()
  sessions.discardDraft!()
  expect(sessions.getSnapshot().draft).toMatchObject({ active: false, endedBy: 'discarded' })
  expect(a.client.getSnapshot().selectedSessionId).toBe('E1') // restore = the selection was never cleared
  expect(a.calls.sends).toHaveLength(0)
})

it('openSession during an active draft ends it as opened and sends nothing (可区分下游语义)', async () => {
  const a = projectClient('A', 'https://s1')
  const sessions = await harness({ id: 'A', build: () => a.client })
  await sessions.selectConnection('A')
  await sessions.openSession('E1')
  await sessions.selectWorkspace!('/srv/a')
  sessions.startDraft!()
  await sessions.openSession('E1')
  expect(sessions.getSnapshot().draft).toMatchObject({ active: false, endedBy: 'opened' })
  expect(a.calls.sends).toHaveLength(0)
  // The step-away is resumable: a re-start keeps the held requestId path intact and ends cleanly.
  sessions.startDraft!()
  expect(sessions.getSnapshot().draft).toMatchObject({ active: true })
  expect(sessions.getSnapshot().draft?.endedBy).toBeUndefined() // startDraft clears the previous ending
})

it('an unknown draft outcome with an old session selected keeps the requestId and never falls back to it (unknown 不降级)', async () => {
  const a = projectClient('A', 'https://s1', { rejectFirstSend: true })
  const sessions = await harness({ id: 'A', build: () => a.client })
  await sessions.selectConnection('A')
  await sessions.openSession('E1')
  await sessions.selectWorkspace!('/srv/a')
  sessions.startDraft!()
  await expect(sessions.send('hi')).rejects.toThrow('outcome unknown')
  expect(sessions.getSnapshot().draft?.active).toBe(true)
  await sessions.send('hi')
  expect(a.calls.sends).toHaveLength(2)
  expect(a.calls.sends[0]!.requestId).toBe(a.calls.sends[1]!.requestId)
  expect(a.client.getSnapshot().messages.E1).toBeUndefined() // retry also goes only through createAndSend
})

it('switching connections with a live draft sends nothing on either side (切换零发送)', async () => {
  const a1 = projectClient('A1', 'https://s1')
  const a2 = projectClient('A2', 'https://s2')
  const sessions = await harness({ id: 'A1', build: () => a1.client }, { id: 'A2', build: () => a2.client })
  await sessions.selectConnection('A1')
  sessions.startDraft!()
  await sessions.selectConnection('A2')
  expect(sessions.getSnapshot().draft).toMatchObject({ active: false, canSend: false, blockReason: 'no-project' })
  expect(a2.calls.sends).toHaveLength(0)
  await sessions.selectConnection('A1')
  expect(sessions.getSnapshot().draft?.active).toBe(true) // draft state is per-connection, never leaked or sent
  expect(a1.calls.sends).toHaveLength(0)
  expect(a2.calls.sends).toHaveLength(0)
})
