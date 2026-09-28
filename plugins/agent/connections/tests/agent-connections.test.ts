import { expect, it } from 'vitest'
import { OwnedResources } from '@ordessa/extension-api'
import { createConnections } from '../../../../packages/desktop-platform/connections/src/index'
import { createAgentConnections } from '../../../../plugins/agent/connections/src/entry'

// Since T028 the Agent facade is a consumer of the @ordessa/connections platform: in the product
// the platform service arrives through ConnectionsToken, so a direct factory call has to supply
// the real platform itself (the same implementation the `ordessa.connections` extension activates,
// no stub, no second registry). Nothing else about these tests changed.

it('lets independent adapters register and releases each with its own scope', async () => {
  const serviceScope = new OwnedResources()
  const a = new OwnedResources(), b = new OwnedResources()
  const service = createAgentConnections(serviceScope, createConnections(serviceScope))
  let changes = 0
  const unsubscribe = service.subscribe(() => { changes++ })
  service.forScope(a).add({ id: 'codex', title: 'Codex', connect: async () => { throw Error('offline') } })
  service.forScope(b).add({ id: 'pi', title: 'Pi', connect: async () => { throw Error('offline') } })
  expect(service.getSnapshot().map(item => item.id)).toEqual(['codex', 'pi'])
  expect(service.getSnapshot()).toBe(service.getSnapshot())
  a.dispose()
  expect(service.getSnapshot().map(item => item.id)).toEqual(['pi'])
  await expect(service.connect('codex')).rejects.toThrow('unavailable')
  expect(changes).toBe(3)
  unsubscribe()
  b.dispose()
  serviceScope.dispose()
  expect(service.getSnapshot()).toEqual([])
  expect(() => service.forScope(b).add({ id: 'late', title: 'Late', connect: async () => { throw Error() } })).toThrow('closed')
})

import { hasAwaitingInteraction, hasOpenRun } from '../../../../plugins/agent/contracts/src/connections'
import { createAgentSessions } from '../../../../plugins/agent/sessions/src/model'
import type { AgentClient, AgentReleaseState, AgentSnapshot } from '../../../../plugins/agent/contracts/src/contract'

function snapshotWith(overrides: Partial<AgentSnapshot>): AgentSnapshot {
  return { connection: { id: 'A', title: 'A', status: 'connected', capabilities: {
    history: 'unknown', reasoning: 'unknown', tools: 'unknown', stop: 'supported', interactions: 'unknown', models: 'unknown', modes: 'unknown',
  } }, sessions: [], sessionList: 'ready', messages: {}, runs: {}, interactions: [], options: [], ...overrides }
}

it('gate predicates match run/interaction state only, across every connection', () => {
  expect(hasOpenRun([])).toBe(false)
  expect(hasOpenRun([snapshotWith({})])).toBe(false)
  for (const status of ['starting', 'running', 'stop-requested'] as const)
    expect(hasOpenRun([snapshotWith({ runs: { r: { id: 'r', sessionId: 's', status } } })])).toBe(true)
  for (const status of ['completed', 'cancelled', 'failed', 'unknown'] as const)
    expect(hasOpenRun([snapshotWith({ runs: { r: { id: 'r', sessionId: 's', status } } })])).toBe(false)
  expect(hasAwaitingInteraction([])).toBe(false)
  for (const state of ['pending', 'responding'] as const)
    expect(hasAwaitingInteraction([snapshotWith({ interactions: [{ id: 'i', sessionId: 's', kind: 'approval', title: 't', state }] })])).toBe(true)
  for (const state of ['resolved', 'expired', 'unknown'] as const)
    expect(hasAwaitingInteraction([snapshotWith({ interactions: [{ id: 'i', sessionId: 's', kind: 'approval', title: 't', state }] })])).toBe(false)
})

/** Reactive mock: workspace clientSnapshots track it only through its subscribe channel. */
function liveClient(id: string, initial: AgentSnapshot) {
  const box = { current: initial }
  const listeners = new Set<() => void>()
  const value: AgentClient = {
    isDisposed: false, dispose() { listeners.clear() },
    getSnapshot: () => box.current, subscribe(listener) { listeners.add(listener); return () => { listeners.delete(listener) } },
    refreshSessions: async () => {}, newSession: async () => 's', openSession: async () => {},
    send: async () => {}, stop: async () => {}, respond: async () => {}, setOption: async () => {},
  }
  return { value, set(next: AgentSnapshot) { box.current = next; listeners.forEach(fn => fn()) } }
}

it('switching views over live work keeps the previous client, its run and its approvals alive', async () => {
  const registryScope = new OwnedResources(), facadeScope = new OwnedResources(), connectorScope = new OwnedResources()
  const base = { sessions: [] as never, sessionList: 'ready' as const, messages: {} as never, options: [] as never }
  const codex = liveClient('codex', { connection: { id: 'codex', title: 'Codex', status: 'connected', capabilities: {
    history: 'unknown', reasoning: 'unknown', tools: 'unknown', stop: 'supported', interactions: 'unknown', models: 'unknown', modes: 'unknown' } },
    ...base, runs: {}, interactions: [] })
  const pi = liveClient('pi', { connection: { id: 'pi', title: 'Pi', status: 'connected', capabilities: {
    history: 'unknown', reasoning: 'unknown', tools: 'unknown', stop: 'supported', interactions: 'unknown', models: 'unknown', modes: 'unknown' } },
    ...base, runs: {}, interactions: [] })
  const registry = createAgentConnections(registryScope, createConnections(registryScope))
  registry.forScope(connectorScope).add({ id: 'codex', title: 'Codex', connect: async () => codex.value })
  registry.forScope(connectorScope).add({ id: 'pi', title: 'Pi', connect: async () => pi.value })
  const sessions = createAgentSessions(facadeScope, registry)
  await sessions.selectConnection('codex')
  codex.set({ ...codex.value.getSnapshot(), runs: { t: { id: 't', sessionId: 's', status: 'running', stoppable: true } } })
  // A plain selection change is view-only: it succeeds over an open run and tears nothing down.
  await sessions.selectConnection('pi')
  expect(sessions.getSnapshot().selectedConnectionId).toBe('pi')
  expect(codex.value.getSnapshot().runs.t?.status).toBe('running')
  // Coming back still sees the same live run on the preserved client.
  await sessions.selectConnection('codex')
  expect(sessions.getSnapshot().agent?.runs.t?.status).toBe('running')
  // An awaiting approval survives being switched away from, still unanswered.
  codex.set({ ...codex.value.getSnapshot(), interactions: [{ id: 'i', sessionId: 's', kind: 'approval', title: 'Approve', state: 'pending' }] })
  await sessions.selectConnection('pi')
  expect(codex.value.getSnapshot().interactions[0]?.state).toBe('pending')
  await sessions.selectConnection('codex')
  expect(sessions.getSnapshot().agent?.interactions[0]?.state).toBe('pending')
  registryScope.dispose(); facadeScope.dispose(); connectorScope.dispose()
})

it('gates reconnect with the same authority as switching and restores it once live work clears', async () => {
  const registryScope = new OwnedResources(), facadeScope = new OwnedResources(), connectorScope = new OwnedResources()
  const base = { sessions: [] as never, sessionList: 'ready' as const, messages: {} as never, options: [] as never }
  const codex = liveClient('codex', { connection: { id: 'codex', title: 'Codex', status: 'connected', capabilities: {
    history: 'unknown', reasoning: 'unknown', tools: 'unknown', stop: 'supported', interactions: 'unknown', models: 'unknown', modes: 'unknown' } },
    ...base, runs: {}, interactions: [] })
  const pi = liveClient('pi', { connection: { id: 'pi', title: 'Pi', status: 'connected', capabilities: {
    history: 'unknown', reasoning: 'unknown', tools: 'unknown', stop: 'supported', interactions: 'unknown', models: 'unknown', modes: 'unknown' } },
    ...base, runs: {}, interactions: [] })
  const registry = createAgentConnections(registryScope, createConnections(registryScope))
  registry.forScope(connectorScope).add({ id: 'codex', title: 'Codex', connect: async () => codex.value })
  registry.forScope(connectorScope).add({ id: 'pi', title: 'Pi', connect: async () => pi.value })
  const sessions = createAgentSessions(facadeScope, registry)
  await sessions.selectConnection('codex')
  // The selected connection's own open run blocks its reconnect, without cancelling the run.
  codex.set({ ...codex.value.getSnapshot(), runs: { t: { id: 't', sessionId: 's', status: 'running', stoppable: true } } })
  await expect(sessions.reconnect('codex')).rejects.toThrow('reconnect is blocked')
  expect(sessions.getSnapshot().selectedConnectionId).toBe('codex')
  expect(Object.keys(sessions.getSnapshot().agent?.runs ?? {})).toEqual(['t'])
  // A reconnect that would move the selection is gated by live work on any connection.
  pi.set({ ...pi.value.getSnapshot(), interactions: [{ id: 'i', sessionId: 's', kind: 'approval', title: 'Approve', state: 'pending' }] })
  await expect(sessions.reconnect('pi')).rejects.toThrow('reconnect is blocked')
  expect(sessions.getSnapshot().selectedConnectionId).toBe('codex')
  // Clearing live work restores the recovery path, and the reconnected client stays reactive.
  codex.set({ ...codex.value.getSnapshot(), runs: {} })
  pi.set({ ...pi.value.getSnapshot(), interactions: [] })
  await sessions.reconnect('pi')
  expect(sessions.getSnapshot().selectedConnectionId).toBe('pi')
  pi.set({ ...pi.value.getSnapshot(), runs: { u: { id: 'u', sessionId: 's', status: 'running', stoppable: true } } })
  expect(sessions.getSnapshot().agent?.runs.u?.status).toBe('running')
  // Reconnecting an unregistered id cannot leave the selection pointing at nothing.
  await expect(sessions.reconnect('stale')).rejects.toThrow('unavailable')
  expect(sessions.getSnapshot().selectedConnectionId).toBe('pi')
  registryScope.dispose(); facadeScope.dispose(); connectorScope.dispose()
})

/** Connector whose handshake is held by the test, so a connection can be mid-flight. */
function gatedClient(id: string, initial: AgentSnapshot) {
  const client = liveClient(id, initial)
  let release!: () => void
  const handshake = new Promise<void>(resolve => { release = resolve })
  return { client, connector: { id, title: id, connect: async () => { await handshake; return client.value } },
    settle() { release() } }
}

async function until(what: string, predicate: () => boolean, timeoutMs = 2_000) {
  const deadline = Date.now() + timeoutMs
  while (!predicate()) {
    if (Date.now() > deadline) throw new Error(`timed out waiting for ${what}`)
    await new Promise(resolve => setTimeout(resolve, 5))
  }
}

/** An ACP-shaped lifecycle: `dispose()` only STARTS the backend releases — announcing `in-flight`
 * synchronously per channel, before it returns — and answers arrive later, over the notification
 * channel and nowhere else. Tests drive channels by name: `attach` is a live channel (released at
 * dispose), `holdAcquire` is an acquire whose handle may only land AFTER dispose, `seedFailed` is
 * a release that already failed while the client was still current, and `answer` delivers one
 * backend response. `releasesSettled` mirrors the real client's attestation: it resolves only
 * when the client is disposed AND no acquire remains AND nothing stands unconfirmed — never
 * merely because the live view happens to be empty. The call counter proves joining an in-flight
 * attempt never doubles the backend request. */
function managedReleaseClient(id: string, initial: AgentSnapshot) {
  const base = liveClient(id, initial)
  const ledger = new Map<string, { status: 'in-flight' | 'failed'; reason?: string }>()
  const watchers = new Set<(state: AgentReleaseState) => void>()
  const attempts = new Map<string, Promise<void>>()
  const resolvers = new Map<string, { resolve: () => void; reject: (error: Error) => void }>()
  const live = new Set<string>()
  const acquiring = new Set<string>()
  let disposed = false, drained = false, calls = 0
  let settle!: () => void
  const releasesSettled = new Promise<void>(resolve => { settle = resolve })
  const maybeDrain = () => {
    if (drained || !disposed || ledger.size > 0 || acquiring.size > 0 || attempts.size > 0) return
    drained = true
    settle()
  }
  const announce = (connectionId: string, status: 'in-flight' | 'failed' | 'confirmed', reason?: string) => {
    if (status === 'confirmed') ledger.delete(connectionId)
    else ledger.set(connectionId, { status, ...(reason === undefined ? {} : { reason }) })
    const state: AgentReleaseState = { connectionId, status, ...(reason === undefined ? {} : { reason }) }
    for (const watcher of [...watchers]) watcher(state)
    maybeDrain()
  }
  const startRelease = (connectionId: string): Promise<void> => {
    const existing = attempts.get(connectionId)
    if (existing) return existing // join the one request: no second call
    calls++
    announce(connectionId, 'in-flight')
    const attempt = new Promise<void>((resolve, reject) => { resolvers.set(connectionId, { resolve, reject }) })
    attempts.set(connectionId, attempt)
    return attempt
  }
  const value: AgentClient = {
    ...base.value,
    get releaseFailures() {
      return [...ledger].filter(([, record]) => record.status === 'failed')
        .map(([connectionId, record]) => ({ connectionId, reason: record.reason ?? '' }))
    },
    releaseStates: () => [...ledger].map(([connectionId, record]) =>
      ({ connectionId, status: record.status, ...(record.reason === undefined ? {} : { reason: record.reason }) })),
    subscribeReleaseStates(listener) { watchers.add(listener); return () => { watchers.delete(listener) } },
    releasesSettled,
    dispose() {
      disposed = true
      base.value.dispose()
      for (const connectionId of live) void startRelease(connectionId).catch(() => {})
      maybeDrain()
    },
    retryReleases: async () => {
      const outcomes = await Promise.all([...ledger.keys()].map(connectionId =>
        startRelease(connectionId).then(() => undefined, (error: unknown) => error)))
      const refusal = outcomes.find(Boolean)
      if (refusal !== undefined) throw refusal
    },
  }
  return {
    value,
    backendCalls: () => calls,
    watcherCount: () => watchers.size,
    attach: (connectionId: string) => { live.add(connectionId) },
    holdAcquire: (connectionId: string) => { acquiring.add(connectionId) },
    /** The late handle lands after dispose: the acquire ends and the stand-down begins. */
    landAcquire: (connectionId: string) => {
      acquiring.delete(connectionId)
      void startRelease(connectionId).catch(() => {})
      maybeDrain()
    },
    seedFailed: (connectionId: string, reason: string) => announce(connectionId, 'failed', reason),
    answer(connectionId: string, confirms: boolean, reason = 'backend unreachable') {
      const pending = resolvers.get(connectionId)
      if (!pending) throw new Error(`no release attempt outstanding for ${connectionId}`)
      resolvers.delete(connectionId)
      attempts.delete(connectionId)
      if (confirms) { announce(connectionId, 'confirmed'); pending.resolve() }
      else { announce(connectionId, 'failed', reason); pending.reject(Error(reason)) }
      maybeDrain()
    },
  }
}

it('a release that fails after the reconnect completed reaches the subscriber and the snapshot on its own, and the explicit passes settle it', async () => {
  const registryScope = new OwnedResources(), connectorScope = new OwnedResources()
  const empty = (id: string): AgentSnapshot => ({ connection: { id, title: id, status: 'connected', capabilities: {
    history: 'unknown', reasoning: 'unknown', tools: 'unknown', stop: 'supported', interactions: 'unknown', models: 'unknown', modes: 'unknown' } },
    sessions: [], sessionList: 'ready', messages: {}, runs: {}, interactions: [], options: [] })
  const evicted = managedReleaseClient('acp', empty('acp'))
  evicted.attach('chan_acp')
  const current = liveClient('acp', empty('acp'))
  let connects = 0
  const registry = createAgentConnections(registryScope, createConnections(registryScope))
  registry.forScope(connectorScope).add({ id: 'acp', title: 'ACP', connect: async () => (++connects === 1 ? evicted.value : current.value) })
  const workspace = registry.workspace
  await workspace.selectConnection('acp')
  await workspace.reconnect('acp') // completes while the release answer is still withheld
  // The evicted client is gone from every current-connection surface…
  expect(workspace.selected()).toBe(current.value)
  // …and the release is visible as in-flight — an outstanding request is never presumed confirmed.
  expect(workspace.releaseCleanup!()).toEqual([{ connectionId: 'chan_acp', status: 'in-flight' }])
  expect(workspace.getSnapshot().pendingReleases).toEqual([{ connectionId: 'chan_acp', status: 'in-flight' }])
  let notified = 0
  const unsubscribe = workspace.subscribe(() => { notified++ })
  // The refusal lands after the whole reconnect flow is done, and nothing else happens: no
  // selection, no click, no forced publish — the client's own announcement must move the host.
  evicted.answer('chan_acp', false)
  await until('the announced failure to reach the reactive surface', () =>
    (workspace.getSnapshot().pendingReleases ?? []).some(item => item.status === 'failed'))
  expect(notified).toBeGreaterThan(0)
  expect(workspace.getSnapshot().pendingReleases).toEqual([{ connectionId: 'chan_acp', status: 'failed', reason: 'backend unreachable' }])
  // The explicit pass reports the backend still refusing, and the reference stays held.
  const refusing = workspace.retryReleaseCleanup!()
  evicted.answer('chan_acp', false)
  await expect(refusing).rejects.toThrow('backend unreachable')
  expect((workspace.releaseCleanup?.() ?? []).length).toBe(1)
  // The confirming pass clears the surface, and the client's drain attestation ends the retention.
  const settling = workspace.retryReleaseCleanup!()
  evicted.answer('chan_acp', true)
  await settling
  expect(workspace.releaseCleanup!()).toEqual([])
  expect(workspace.getSnapshot().pendingReleases).toEqual([])
  await until('the attested client to be forgotten', () => evicted.watcherCount() === 0)
  // Exactly one eviction attempt plus two explicit passes — nothing retried by itself.
  expect(evicted.backendCalls()).toBe(3)
  expect(current.value.isDisposed).toBe(false)
  unsubscribe(); registryScope.dispose(); connectorScope.dispose()
})

it('a cleanup pass started while the first release is in-flight joins that request and keeps the reference for the failure that follows', async () => {
  const registryScope = new OwnedResources(), connectorScope = new OwnedResources()
  const empty = (id: string): AgentSnapshot => ({ connection: { id, title: id, status: 'connected', capabilities: {
    history: 'unknown', reasoning: 'unknown', tools: 'unknown', stop: 'supported', interactions: 'unknown', models: 'unknown', modes: 'unknown' } },
    sessions: [], sessionList: 'ready', messages: {}, runs: {}, interactions: [], options: [] })
  const evicted = managedReleaseClient('acp', empty('acp'))
  evicted.attach('chan_acp')
  const current = liveClient('acp', empty('acp'))
  let connects = 0
  const registry = createAgentConnections(registryScope, createConnections(registryScope))
  registry.forScope(connectorScope).add({ id: 'acp', title: 'ACP', connect: async () => (++connects === 1 ? evicted.value : current.value) })
  const workspace = registry.workspace
  await workspace.selectConnection('acp')
  await workspace.reconnect('acp')
  expect(evicted.backendCalls()).toBe(1)
  // The host runs its cleanup pass while the first release has not answered yet. An empty
  // failure record is not evidence of confirmation — the pass must join the one request,
  // never double it, and never drop the reference on the strength of "nothing failed".
  const cleanup = workspace.retryReleaseCleanup!()
  expect(evicted.backendCalls()).toBe(1)
  expect((workspace.releaseCleanup?.() ?? []).length).toBe(1)
  // The joined request then refuses: the refusal reaches this pass and the reference stays.
  evicted.answer('chan_acp', false)
  await expect(cleanup).rejects.toThrow('backend unreachable')
  expect(workspace.getSnapshot().pendingReleases).toEqual([{ connectionId: 'chan_acp', status: 'failed', reason: 'backend unreachable' }])
  // The late failure is still retryable — one further attempt per reference, and it confirms.
  const retrying = workspace.retryReleaseCleanup!()
  evicted.answer('chan_acp', true)
  await retrying
  expect(workspace.releaseCleanup!()).toEqual([])
  expect(evicted.backendCalls()).toBe(2)
  registryScope.dispose(); connectorScope.dispose()
})

it('a release that failed before the eviction is seeded into the host view the moment the reference is taken over', async () => {
  const registryScope = new OwnedResources(), connectorScope = new OwnedResources()
  const empty = (id: string): AgentSnapshot => ({ connection: { id, title: id, status: 'connected', capabilities: {
    history: 'unknown', reasoning: 'unknown', tools: 'unknown', stop: 'supported', interactions: 'unknown', models: 'unknown', modes: 'unknown' } },
    sessions: [], sessionList: 'ready', messages: {}, runs: {}, interactions: [], options: [] })
  const evicted = managedReleaseClient('acp', empty('acp'))
  // A channel churned during the client's own life: its release already refused BEFORE the host
  // ever took over observing. A subscription alone cannot reach backwards — without seeding,
  // this failure is silently lost the moment the client is evicted.
  evicted.seedFailed('chan_gone', 'backend unreachable')
  evicted.attach('chan_acp')
  const current = liveClient('acp', empty('acp'))
  let connects = 0
  const registry = createAgentConnections(registryScope, createConnections(registryScope))
  registry.forScope(connectorScope).add({ id: 'acp', title: 'ACP', connect: async () => (++connects === 1 ? evicted.value : current.value) })
  const workspace = registry.workspace
  await workspace.selectConnection('acp')
  await workspace.reconnect('acp')
  // Both the pre-existing failure and the eviction's own in-flight release enter the view at once,
  // and the reactive surface carries them with no forced publish.
  expect(workspace.releaseCleanup!()).toEqual([
    { connectionId: 'chan_gone', status: 'failed', reason: 'backend unreachable' },
    { connectionId: 'chan_acp', status: 'in-flight' },
  ])
  expect(workspace.getSnapshot().pendingReleases).toEqual([
    { connectionId: 'chan_gone', status: 'failed', reason: 'backend unreachable' },
    { connectionId: 'chan_acp', status: 'in-flight' },
  ])
  // The eviction's own release refuses too; one explicit pass settles both channels.
  evicted.answer('chan_acp', false)
  const settling = workspace.retryReleaseCleanup!()
  evicted.answer('chan_gone', true)
  evicted.answer('chan_acp', true)
  await settling
  expect(workspace.releaseCleanup!()).toEqual([])
  await until('the fully-confirmed client to be forgotten', () => evicted.watcherCount() === 0)
  // One dispose attempt plus one explicit pass per failed channel — no silent extras.
  expect(evicted.backendCalls()).toBe(3)
  registryScope.dispose(); connectorScope.dispose()
})

it('a client whose first release confirms while another channel is still acquiring is forgotten only after that later release settles', async () => {
  const registryScope = new OwnedResources(), connectorScope = new OwnedResources()
  const empty = (id: string): AgentSnapshot => ({ connection: { id, title: id, status: 'connected', capabilities: {
    history: 'unknown', reasoning: 'unknown', tools: 'unknown', stop: 'supported', interactions: 'unknown', models: 'unknown', modes: 'unknown' } },
    sessions: [], sessionList: 'ready', messages: {}, runs: {}, interactions: [], options: [] })
  const evicted = managedReleaseClient('acp', empty('acp'))
  evicted.attach('chan_a')
  // At eviction, chan_b's handle has not landed yet: its release cannot even have started.
  evicted.holdAcquire('chan_b')
  const current = liveClient('acp', empty('acp'))
  let connects = 0
  const registry = createAgentConnections(registryScope, createConnections(registryScope))
  registry.forScope(connectorScope).add({ id: 'acp', title: 'ACP', connect: async () => (++connects === 1 ? evicted.value : current.value) })
  const workspace = registry.workspace
  await workspace.selectConnection('acp')
  await workspace.reconnect('acp')
  expect(workspace.releaseCleanup!()).toEqual([{ connectionId: 'chan_a', status: 'in-flight' }])
  // A confirms: the live view goes EMPTY while B is still acquiring. This is the exact moment
  // the old rule forgot the client — the reference (and subscription) must survive it.
  evicted.answer('chan_a', true)
  expect(workspace.releaseCleanup!()).toEqual([])
  expect(evicted.watcherCount()).toBe(1)
  // B's handle lands late, its release fails — and the host, still subscribed, must see it.
  evicted.landAcquire('chan_b')
  evicted.answer('chan_b', false)
  expect(workspace.getSnapshot().pendingReleases).toEqual([{ connectionId: 'chan_b', status: 'failed', reason: 'backend unreachable' }])
  // Only once that later release confirms can the client attest silence — then the host forgets.
  const settling = workspace.retryReleaseCleanup!()
  evicted.answer('chan_b', true)
  await settling
  expect(workspace.releaseCleanup!()).toEqual([])
  await until('the attested client to be forgotten', () => evicted.watcherCount() === 0)
  registryScope.dispose(); connectorScope.dispose()
})

it('evicting a client without the managed-release lifecycle retains nothing to confirm', async () => {
  const registryScope = new OwnedResources(), connectorScope = new OwnedResources()
  const plain = (id: string) => liveClient(id, { connection: { id, title: id, status: 'connected', capabilities: {
    history: 'unknown', reasoning: 'unknown', tools: 'unknown', stop: 'supported', interactions: 'unknown', models: 'unknown', modes: 'unknown' } },
    sessions: [] as never, sessionList: 'ready' as const, messages: {} as never, runs: {}, interactions: [], options: [] as never } as AgentSnapshot)
  const first = plain('codex'), second = plain('codex')
  let connects = 0
  const registry = createAgentConnections(registryScope, createConnections(registryScope))
  registry.forScope(connectorScope).add({ id: 'codex', title: 'Codex', connect: async () => (++connects === 1 ? first.value : second.value) })
  const workspace = registry.workspace
  await workspace.selectConnection('codex')
  await workspace.reconnect('codex')
  expect(workspace.releaseCleanup!()).toEqual([])
  expect(workspace.getSnapshot().pendingReleases).toEqual([])
  await workspace.retryReleaseCleanup!()
  expect(workspace.releaseCleanup!()).toEqual([])
  registryScope.dispose(); connectorScope.dispose()
})

it('re-evaluates the gate once a held handshake lands, so reconnect cannot cancel a run started during it', async () => {
  const registryScope = new OwnedResources(), facadeScope = new OwnedResources(), connectorScope = new OwnedResources()
  const base = { sessions: [] as never, sessionList: 'ready' as const, messages: {} as never, options: [] as never }
  // The connector answers with a client that already has an open run.
  const pi = gatedClient('pi', { connection: { id: 'pi', title: 'Pi', status: 'connected', capabilities: {
    history: 'unknown', reasoning: 'unknown', tools: 'unknown', stop: 'supported', interactions: 'unknown', models: 'unknown', modes: 'unknown' } },
    ...base, runs: { t: { id: 't', sessionId: 's', status: 'running', stoppable: true } }, interactions: [] })
  const registry = createAgentConnections(registryScope, createConnections(registryScope))
  registry.forScope(connectorScope).add(pi.connector)
  const sessions = createAgentSessions(facadeScope, registry)
  const connecting = sessions.selectConnection('pi')
  // Reconnect starts while the handshake is still held: the client is not in the map yet,
  // so a gate that reads state only once would wave it through and then dispose the run.
  const reconnecting = sessions.reconnect('pi')
  pi.settle()
  await connecting
  await expect(reconnecting).rejects.toThrow('reconnect is blocked')
  // The live run survives the refused reconnect instead of being silently cancelled.
  expect(sessions.getSnapshot().agent?.runs.t?.status).toBe('running')
  registryScope.dispose(); facadeScope.dispose(); connectorScope.dispose()
})

it('leaves the connecting indicator owned by the handshake that is still pending', async () => {
  const registryScope = new OwnedResources(), facadeScope = new OwnedResources(), connectorScope = new OwnedResources()
  const base = { sessions: [] as never, sessionList: 'ready' as const, messages: {} as never, options: [] as never }
  const empty = (id: string) => ({ connection: { id, title: id, status: 'connected', capabilities: {
    history: 'unknown', reasoning: 'unknown', tools: 'unknown', stop: 'supported', interactions: 'unknown', models: 'unknown', modes: 'unknown' } },
    ...base, runs: {}, interactions: [] }) as AgentSnapshot
  const codex = gatedClient('codex', empty('codex')), pi = gatedClient('pi', empty('pi'))
  const registry = createAgentConnections(registryScope, createConnections(registryScope))
  registry.forScope(connectorScope).add(codex.connector)
  registry.forScope(connectorScope).add(pi.connector)
  const sessions = createAgentSessions(facadeScope, registry)
  const first = sessions.selectConnection('codex')
  const second = sessions.reconnect('pi')
  // pi is the connection still handshaking and the one currently selected, so a codex
  // handshake landing first must not clear pi's indicator or make pi look idle.
  codex.settle()
  await first
  expect(sessions.getSnapshot().connectingId).toBe('pi')
  pi.settle()
  await second
  expect(sessions.getSnapshot().connectingId).toBeUndefined()
  registryScope.dispose(); facadeScope.dispose(); connectorScope.dispose()
})
