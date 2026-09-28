import { expect, it } from 'vitest'
import { OwnedResources } from '@ordessa/extension-api'
import { createConnections } from '../../../../packages/desktop-platform/connections/src/index'
import { createAgentConnections } from '../../../../plugins/agent/connections/src/entry'
import { createAgentSessions } from '../../../../plugins/agent/sessions/src/model'
import { projectSessionGroups, sessionActivity, workspaceLabel } from '../../../../plugins/agent/sessions/src/projection'
import type { AgentClient, AgentSnapshot } from '../../../../plugins/agent/contracts/src/contract'

function client(id: string) {
  let snapshot: AgentSnapshot = { connection: { id, title: id, status: 'connected', capabilities: {
    history: 'supported', reasoning: 'unknown', tools: 'unknown', stop: 'supported', interactions: 'unknown', models: 'unknown', modes: 'unknown',
  } }, sessions: [], sessionList: 'ready', messages: {}, runs: {}, interactions: [], options: [] }
  let disposed = false
  const calls: string[] = [], listeners = new Set<() => void>()
  const value: AgentClient = {
    get isDisposed() { return disposed }, dispose() { disposed = true; listeners.clear() },
    getSnapshot: () => snapshot, subscribe(listener) { listeners.add(listener); return () => { listeners.delete(listener) } },
    async refreshSessions() { calls.push('refresh') },
    async newSession() { calls.push('new'); return 'S' },
    async openSession(session) { calls.push(`open:${session}`); snapshot = { ...snapshot, selectedSessionId: session }; listeners.forEach(fn => fn()) },
    async send(session, text) { calls.push(`send:${session}:${text}`) },
    async stop(session, run) { calls.push(`stop:${session}:${run}`) },
    async respond() { calls.push('respond') }, async setOption() { calls.push('option') },
  }
  return { value, calls }
}

it('keeps separate clients alive on selection changes and disposes them with the connections service scope', async () => {
  const registryScope = new OwnedResources(), sessionScope = new OwnedResources()
  const aScope = new OwnedResources(), bScope = new OwnedResources()
  const registry = createAgentConnections(registryScope, createConnections(registryScope))
  const a = client('A'), b = client('B')
  registry.forScope(aScope).add({ id: 'A', title: 'A', connect: async () => a.value })
  registry.forScope(bScope).add({ id: 'B', title: 'B', connect: async () => b.value })
  const sessions = createAgentSessions(sessionScope, registry)
  await sessions.selectConnection('A'); await sessions.openSession('one')
  await sessions.selectConnection('B'); await sessions.openSession('two')
  expect(a.value.isDisposed).toBe(false)
  expect(a.calls).toEqual(['open:one'])
  await sessions.selectConnection('A'); await sessions.send('hello')
  expect(a.calls).toEqual(['open:one', 'send:one:hello'])
  expect(sessions.getSnapshot().agent?.selectedSessionId).toBe('one')
  // P2-1: client holding moved to the connections service workspace — its scope now owns client teardown.
  registryScope.dispose()
  expect(a.value.isDisposed).toBe(true)
  expect(b.value.isDisposed).toBe(true)
  sessionScope.dispose(); aScope.dispose(); bScope.dispose()
})

it('projects sessions into ordered workspace groups with the standalone group last (P2-3 projection)', () => {
  const groups = projectSessionGroups([
    { id: 'A', title: 'a', workspaceId: '/srv/x/alpha' },
    { id: 'B', title: 'b' },
    { id: 'C', title: 'c', workspaceId: '/srv/x/beta/', pinned: true },
    { id: 'D', title: 'd', workspaceId: '/srv/x/alpha', pinned: true },
    { id: 'E', title: 'e', workspaceId: '' },
  ])
  expect(groups.map(group => group.key)).toEqual(['/srv/x/alpha', '/srv/x/beta', 'standalone'])
  expect(groups.map(group => group.title)).toEqual(['alpha', 'beta', 'Standalone sessions'])
  expect(groups[0].sessions.map(session => session.id)).toEqual(['D', 'A'])
  // Empty-string workspaceId counts as standalone alongside missing ones (wire NULL parity).
  expect(groups[2].sessions.map(session => session.id)).toEqual(['B', 'E'])
  expect(projectSessionGroups([])).toEqual([])
  expect(workspaceLabel('/srv/x/')).toBe('x')
})

it('derives per-session badge state through the shared gate predicates over all items', () => {
  const base = { connection: { id: 'A', title: 'A', status: 'connected', capabilities: {
    history: 'supported', reasoning: 'unknown', tools: 'unknown', stop: 'supported', interactions: 'unknown', models: 'unknown', modes: 'unknown',
  } }, sessions: [], sessionList: 'ready', messages: {}, runs: {}, interactions: [], options: [] } as const satisfies AgentSnapshot
  const snapshot: AgentSnapshot = { ...base,
    runs: {
      R1: { id: 'R1', sessionId: 'P1', status: 'completed' },
      R2: { id: 'R2', sessionId: 'P1', status: 'stop-requested' },
      R3: { id: 'R3', sessionId: 'P1', status: 'failed' },
      R4: { id: 'R4', sessionId: 'S1', status: 'unknown' },
    },
    interactions: [
      { id: 'I1', sessionId: 'S1', kind: 'approval', title: 't', state: 'responding' },
      { id: 'I2', sessionId: 'P1', kind: 'input', title: 't', state: 'expired' },
    ] }
  // Any open run anywhere for the session badges, regardless of ordering or last-run status.
  expect(sessionActivity(snapshot, 'P1')).toEqual({ openRun: true, awaiting: false })
  // Unknown run outcome is never an open run; responding interactions badge without any run.
  expect(sessionActivity(snapshot, 'S1')).toEqual({ openRun: false, awaiting: true })
  expect(sessionActivity(snapshot, 'ZZ')).toEqual({ openRun: false, awaiting: false })
})
