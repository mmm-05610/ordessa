import { afterEach, expect, it } from 'vitest'
import { OwnedResources, type PluginContext } from '@ordessa/extension-api'
import { createConnections } from '../../../../packages/frontend/connections/src/index'
import type { Commands, Workbench } from '../../../../packages/frontend/contracts/foundation/src/contract'
import { createAgentConnections } from '../../../../plugins/agent/connections/src/entry'
import type { AgentClient, AgentSnapshot } from '../../../../plugins/agent/contracts/src/contract'
import createSessionsPlugin from '../src/entry'

const capabilities = { history: 'supported', reasoning: 'unknown', tools: 'unknown', stop: 'supported',
  interactions: 'unknown', models: 'unknown', modes: 'unknown', workspaces: 'supported' } as const

function controlledClient(label: string) {
  let snapshot: AgentSnapshot = {
    connection: { id: 'A', title: label, status: 'connected', serverInstanceId: 'https://server.test', capabilities },
    sessions: [{ id: 'S1', title: 'Existing session', workspaceId: '/project' }], selectedSessionId: 'S1',
    sessionList: 'ready', messages: {}, runs: {}, interactions: [], options: [],
    workspaces: { state: 'ready', items: [{ id: '/project', normalizedPath: '/project' }], selectedWorkspaceId: '/project' },
  }
  const calls = { send: 0, carry: 0, newSession: 0, createAndSend: 0, prepareSession: 0, nativeOwner: 0 }
  const listeners = new Set<() => void>()
  const client: AgentClient = {
    get isDisposed() { return false },
    dispose() { listeners.clear() },
    getSnapshot: () => snapshot,
    subscribe(listener) { listeners.add(listener); return () => listeners.delete(listener) },
    async refreshSessions() {},
    async newSession() { calls.newSession += 1; return 'S2' },
    async openSession(id) { snapshot = { ...snapshot, selectedSessionId: id }; for (const listener of [...listeners]) listener() },
    async send() { calls.send += 1 },
    async submitWithAttachments() { calls.carry += 1; return { kind: 'accepted' } },
    async createAndSend() { calls.createAndSend += 1; return { sessionId: 'S2' } },
    async prepareSession() { calls.prepareSession += 1; return { sessionId: 'S2', serverInstanceId: 'https://server.test',
      connectionId: 'native-connection', nativeSessionId: 'native-S2', harnessId: 'harness', workspaceId: '/project' } },
    nativeSessionOwner(sessionId) { calls.nativeOwner += 1; return { sessionId, serverInstanceId: 'https://server.test',
      connectionId: 'native-connection', nativeSessionId: 'native-S1', harnessId: 'harness', workspaceId: '/project' } },
    async stop() {}, async respond() {}, async setOption() {},
    async openWorkspace(id) { return { id, normalizedPath: id } },
  }
  return { client, calls }
}

function productDependencies() {
  const addedCommands: { id: string; execute: () => void }[] = []
  const commands = { forScope: () => ({ add: (command: { id: string; execute: () => void }) => { addedCommands.push(command) } }) } as unknown as Commands
  const views: unknown[] = [], uis: unknown[] = [], opened: string[] = []
  const workbench = { forScope: () => ({
    addView: (view: unknown) => { views.push(view) },
    addUI: (ui: unknown) => { uis.push(ui) },
  }), open: (id: string) => { opened.push(id) } } as unknown as Workbench
  return { commands, workbench }
}

const cleanup: (() => void)[] = []
afterEach(() => { for (const dispose of cleanup.splice(0).reverse()) dispose() })

it('production AgentSessions fences raw submit, attachment carry, native create and preparation while retaining read-only session navigation', async () => {
  const resources = new OwnedResources(), adapterScope = new OwnedResources()
  cleanup.push(() => { adapterScope.dispose(); resources.dispose() })
  const platformConnections = createConnections(resources)
  const connections = createAgentConnections(resources, platformConnections)
  const first = controlledClient('first'), second = controlledClient('replacement')
  let current = first
  connections.forScope(adapterScope).add({ id: 'A', title: 'A', connect: async () => current.client })

  const dependencies = productDependencies()
  const sessions = createSessionsPlugin().activate(
    { resources } as unknown as PluginContext, connections, dependencies.commands, dependencies.workbench,
  )
  await sessions.selectConnection('A')

  // The ordinary selected-session raw route, repeated raw sends, and the raw
  // attachment carry route must all be rejected before reaching the client.
  for (const text of ['first attempt', 'second attempt'])
    expect(await sessions.send(text)).toMatchObject({ kind: 'refused', code: 'CAPABILITY_UNSUPPORTED' })
  expect(await sessions.send('with refs', ['opaque-ref'])).toMatchObject({ kind: 'refused', code: 'CAPABILITY_UNSUPPORTED' })

  // These legacy facade methods must refuse before native session creation or
  // preparation, even though the selected connection reports a usable project.
  await expect(sessions.newSession()).rejects.toMatchObject({ code: 'CAPABILITY_UNSUPPORTED' })
  await expect(sessions.prepareSubmission!()).rejects.toMatchObject({ code: 'CAPABILITY_UNSUPPORTED' })

  // Reconnect installs a different controlled client. The production policy
  // remains attached to the facade and does not reopen a raw escape hatch.
  current = second
  await sessions.reconnect('A')
  expect(await sessions.send('after replacement')).toMatchObject({ kind: 'refused', code: 'CAPABILITY_UNSUPPORTED' })
  sessions.startDraft!()
  expect(sessions.getSnapshot().draft?.active).toBe(true)
  await expect(sessions.prepareSubmission!()).rejects.toMatchObject({ code: 'CAPABILITY_UNSUPPORTED' })
  expect(await sessions.send('draft first text')).toMatchObject({ kind: 'refused', code: 'CAPABILITY_UNSUPPORTED' })

  // Read-only review and selection of a front-end draft remain usable.
  await sessions.openSession('S1')
  expect(sessions.getSnapshot().agent?.selectedSessionId).toBe('S1')
  expect(sessions.getSnapshot().agent?.sessions.map(item => item.id)).toContain('S1')
  sessions.discardDraft!()
  expect(sessions.getSnapshot().draft?.active).toBe(false)

  for (const counters of [first.calls, second.calls])
    expect(counters).toEqual({ send: 0, carry: 0, newSession: 0, createAndSend: 0, prepareSession: 0, nativeOwner: 0 })
})
