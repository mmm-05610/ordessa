// @vitest-environment jsdom
import { act, type ReactNode } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, expect, it } from 'vitest'
import { OwnedResources, type PluginContext } from '@ordessa/extension-api'
import { createConnections } from '../../../../packages/desktop-platform/connections/src/index'
import { createAgentConnections } from '../../../../plugins/agent/connections/src/entry'
import { createAgentSessions } from '../../../../plugins/agent/sessions/src/model'
import { SessionBrowser } from '../../../../plugins/agent/sessions/src/view'
import createSessionsPlugin from '../../../../plugins/agent/sessions/src/entry'
import type { Commands, Workbench } from '../../../../packages/desktop-platform/contracts/foundation/src/contract'
import type { AgentClient, AgentSnapshot } from '../../../../plugins/agent/contracts/src/contract'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
const cleanup: (() => Promise<void>)[] = []
afterEach(async () => { for (const fn of cleanup.splice(0).reverse()) await fn() })

const capabilities = { history: 'supported', reasoning: 'unknown', tools: 'unknown', stop: 'supported',
  interactions: 'unknown', models: 'unknown', modes: 'unknown' } as const

async function mount(element: ReactNode) {
  const container = document.createElement('div')
  document.body.append(container)
  const root = createRoot(container)
  cleanup.push(async () => { await act(async () => root.unmount()); container.remove() })
  await act(async () => root.render(element))
  return container
}

/** The sessions view reads the `agent` slice through the thin facade only, so every group,
 *  badge and five-state input below is controlled without touching production code. */
async function openList(initial: Partial<AgentSnapshot> = {}) {
  let snapshot: AgentSnapshot = {
    connection: { id: 'A', title: 'A', status: 'connected', capabilities },
    sessions: [
      { id: 'P1', title: 'Project chat', workspaceId: '/home/u/proj-a' },
      { id: 'P2', title: 'Pinned chat', workspaceId: '/home/u/proj-a/', pinned: true },
      { id: 'S1', title: 'Standalone chat' },
    ],
    sessionList: 'ready', messages: {}, runs: {}, interactions: [], options: [], ...initial,
  }
  const listeners = new Set<() => void>()
  const write = (patch: Partial<AgentSnapshot>) => {
    snapshot = { ...snapshot, ...patch }
    for (const listener of [...listeners]) listener()
  }
  const client: AgentClient = {
    get isDisposed() { return false },
    dispose() { listeners.clear() },
    getSnapshot: () => snapshot,
    subscribe(listener) { listeners.add(listener); return () => { listeners.delete(listener) } },
    async refreshSessions() {},
    async newSession() { return 'S2' },
    async openSession(id) { write({ selectedSessionId: id }) },
    async send() {},
    async stop() {},
    async respond() {},
    async setOption() {},
  }
  const registryScope = new OwnedResources(), sessionScope = new OwnedResources(), connectorScope = new OwnedResources()
  cleanup.push(async () => { sessionScope.dispose(); connectorScope.dispose(); registryScope.dispose() })
  const registry = createAgentConnections(registryScope, createConnections(registryScope))
  registry.forScope(connectorScope).add({ id: 'A', title: 'A', connect: async () => client })
  const sessions = createAgentSessions(sessionScope, registry)
  await sessions.selectConnection('A')
  const container = await mount(<SessionBrowser service={sessions} />)
  return { container, sessions, write, snapshot: () => snapshot }
}

const itemButton = (container: Element, title: string) =>
  [...container.querySelectorAll('.agent-session-list button')].find(node => node.querySelector('strong')?.textContent === title)

it('groups sessions by workspace with the standalone group last and pinned first (P2-3 grouping)', async () => {
  const { container } = await openList()
  // Reachability first: the section root and the unconditional list container are in the document.
  expect(container.querySelector('section.agent-sessions')).not.toBeNull()
  expect(container.querySelector('.agent-session-list')).not.toBeNull()
  const groups = [...container.querySelectorAll('.agent-session-group')].map(node => node.textContent)
  expect(groups).toEqual(['proj-a', 'Standalone sessions'])
  // Positive control before any positional claim: all three known items are in the list.
  for (const title of ['Project chat', 'Pinned chat', 'Standalone chat']) expect(itemButton(container, title)).toBeDefined()
  const items = [...container.querySelectorAll('.agent-session-list button strong')].map(node => node.textContent)
  // Pinned leads inside its group; the standalone group renders after all project groups.
  expect(items).toEqual(['Pinned chat', 'Project chat', 'Standalone chat'])
})

it('keeps the flat list shape while no session carries a workspace (single standalone group)', async () => {
  const { container } = await openList({ sessions: [{ id: 'S1', title: 'Only chat' }] })
  expect(itemButton(container, 'Only chat')).toBeDefined()
  // No group headers are inserted for a lone standalone group — the pre-P2-3 shape is preserved.
  expect(container.querySelectorAll('.agent-session-group')).toHaveLength(0)
})

it('badges every session by scanning all its runs and interactions, not only the last run (FC-0015 predicates)', async () => {
  const { container, write } = await openList({
    runs: {
      R1: { id: 'R1', sessionId: 'P1', status: 'completed' },
      R2: { id: 'R2', sessionId: 'P1', status: 'running' },
      R3: { id: 'R3', sessionId: 'S1', status: 'stop-requested' },
    },
    interactions: [
      { id: 'I1', sessionId: 'P2', kind: 'approval', title: 'Approve?', state: 'pending' },
      { id: 'I2', sessionId: 'P2', kind: 'input', title: 'Answer?', state: 'resolved' },
    ],
  })
  // Positive control: three known items rendered before asserting per-item badges.
  expect(container.querySelectorAll('.agent-session-list button')).toHaveLength(3)
  expect(itemButton(container, 'Project chat')?.querySelector('.agent-session-state[data-status=running]')?.textContent).toBe('Running')
  expect(itemButton(container, 'Standalone chat')?.querySelector('.agent-session-state[data-status=running]')?.textContent).toBe('Running')
  expect(itemButton(container, 'Pinned chat')?.querySelector('.agent-session-state[data-status=awaiting]')?.textContent).toBe('Awaiting answer')  // Badge state follows the live snapshot, not the last run only.
  await act(async () => { write({ runs: {
    R1: { id: 'R1', sessionId: 'P1', status: 'running' },
    R2: { id: 'R2', sessionId: 'P1', status: 'completed' },
    R3: { id: 'R3', sessionId: 'S1', status: 'failed' },
  } }) })
  expect(itemButton(container, 'Project chat')?.querySelector('.agent-session-state[data-status=running]')?.textContent).toBe('Running')
  expect(itemButton(container, 'Standalone chat')?.querySelector('.agent-session-state')).toBeNull()
  // Resolved interactions never badge; kind is not consulted.
  await act(async () => { write({ interactions: [{ id: 'I2', sessionId: 'P2', kind: 'input', title: 'Answer?', state: 'resolved' }] }) })
  expect(container.querySelectorAll('.agent-session-state[data-status=awaiting]')).toHaveLength(0)
})

it('renders the five list states with their existing copy (empty is a count, not a null container)', async () => {
  const { container, write } = await openList({ sessions: [] })
  // Empty means: the unconditional container is present with zero item buttons, plus the ready-empty line.
  expect(container.querySelector('.agent-session-list')).not.toBeNull()
  expect(container.querySelectorAll('.agent-session-list button')).toHaveLength(0)
  expect(container.querySelector('p.agent-empty')?.textContent).toBe('No sessions yet. Start one above.')
  await act(async () => { write({ sessionList: 'loading' }) })
  expect(container.querySelector('p[role=status].agent-empty')?.textContent).toBe('Loading sessions…')
  await act(async () => { write({ sessionList: 'partial' }) })
  expect(container.querySelector('p.agent-notice')?.textContent).toBe('Only part of the history is available.')
  await act(async () => { write({ sessionList: 'error' }) })
  const alerts = [...container.querySelectorAll('[role=alert]')]
  expect(alerts.some(node => node.textContent === 'Session list failed. Refresh to try again.')).toBe(true)
})

it('keeps exactly one selection marker, moved by clicks and restored on a fresh mount (FC-0004 selection)', async () => {
  const { container, sessions } = await openList()
  const target = itemButton(container, 'Project chat')!
  expect(target.getAttribute('aria-current')).toBeNull()
  await act(async () => { target.click() })
  // Positive control: the click reached the service and the marker moved.
  expect(itemButton(container, 'Project chat')?.getAttribute('aria-current')).toBe('true')
  expect(container.querySelectorAll('.agent-session-list button[aria-current=true]')).toHaveLength(1)
  await act(async () => { itemButton(container, 'Standalone chat')!.click() })
  expect(itemButton(container, 'Project chat')?.getAttribute('aria-current')).toBeNull()
  expect(itemButton(container, 'Standalone chat')?.getAttribute('aria-current')).toBe('true')
  // Selection lives in the service snapshot, so a remounted browser restores the same marker.
  const again = await mount(<SessionBrowser service={sessions} />)
  expect(itemButton(again, 'Standalone chat')?.getAttribute('aria-current')).toBe('true')
  expect(again.querySelectorAll('.agent-session-list button[aria-current=true]')).toHaveLength(1)
})

it('draft UI: New session opens the picker with zero backend calls, picking clears the block, Discard closes it (FC-0021)', async () => {
  const cpCapabilities = { ...capabilities, workspaces: 'supported' } as const
  let snapshot: AgentSnapshot = {
    connection: { id: 'A', title: 'A', status: 'connected', serverInstanceId: 'https://s1', capabilities: cpCapabilities },
    sessions: [], sessionList: 'ready', messages: {}, runs: {}, interactions: [], options: [],
    workspaces: { state: 'ready', items: [{ id: '/srv/a', normalizedPath: '/srv/a' }, { id: '/srv/b', normalizedPath: '/srv/b' }] },
  }
  const listeners = new Set<() => void>()
  const write = (patch: Partial<AgentSnapshot>) => {
    snapshot = { ...snapshot, ...patch }
    for (const listener of [...listeners]) listener()
  }
  const backend: string[] = []
  const client: AgentClient = {
    get isDisposed() { return false },
    dispose() { listeners.clear() },
    getSnapshot: () => snapshot,
    subscribe(listener) { listeners.add(listener); return () => { listeners.delete(listener) } },
    async refreshSessions() {}, async newSession() { backend.push('newSession'); return 'S' },
    async openSession(id) { write({ selectedSessionId: id }) }, async send() { backend.push('send') },
    async stop() {}, async respond() {}, async setOption() {},
    async refreshWorkspaces() { backend.push('refreshWorkspaces') },
    async openWorkspace(id) { write({ workspaces: { ...snapshot.workspaces!, selectedWorkspaceId: id } }); return { id, normalizedPath: id } },
    async addWorkspace(path) {
      backend.push(`addWorkspace:${path}`)
      const added = { id: path, normalizedPath: path }
      write({ workspaces: { state: 'ready', items: [...snapshot.workspaces!.items, added], selectedWorkspaceId: path } })
      return added
    },
    async createAndSend(workspaceId) { backend.push(`createAndSend:${workspaceId}`) },
  }
  const registryScope = new OwnedResources(), sessionScope = new OwnedResources(), connectorScope = new OwnedResources()
  cleanup.push(async () => { sessionScope.dispose(); connectorScope.dispose(); registryScope.dispose() })
  const registry = createAgentConnections(registryScope, createConnections(registryScope))
  registry.forScope(connectorScope).add({ id: 'A', title: 'A', connect: async () => client })
  const sessions = createAgentSessions(sessionScope, registry)
  await sessions.selectConnection('A')
  const container = await mount(<SessionBrowser service={sessions} />)
  const newButton = [...container.querySelectorAll('button')].find(node => node.textContent === 'New session')!
  await act(async () => { newButton.click() })
  // The FE-only draft: picker and block notice render while the client sees no session operation.
  expect(container.querySelector('.agent-draft')).not.toBeNull()
  expect(container.querySelector('p.agent-notice')?.textContent).toBe('Send is blocked until a valid project is selected.')
  expect(container.querySelectorAll('.agent-project-picker button')).toHaveLength(2)
  expect(backend).toEqual([]) // positive control: still zero backend calls after opening the draft
  const project = [...container.querySelectorAll('.agent-project-picker button')].find(node => node.textContent === '/srv/a')!
  await act(async () => { project.click() })
  expect(project.getAttribute('aria-pressed')).toBe('true')
  expect(container.querySelector('p.agent-notice')).toBeNull()
  // Renderer remount (FC-0030): the draft and its validated selection live in the service, so a
  // freshly mounted browser restores the same picker state without any new backend operation.
  const again = await mount(<SessionBrowser service={sessions} />)
  expect(again.querySelector('.agent-draft')).not.toBeNull()
  expect([...again.querySelectorAll('.agent-project-picker button')]
    .find(node => node.textContent === '/srv/a')?.getAttribute('aria-pressed')).toBe('true')
  expect(again.querySelector('p.agent-notice')).toBeNull()
  const discard = [...container.querySelectorAll('button')].find(node => node.textContent === 'Discard draft')!
  await act(async () => { discard.click() })
  expect(container.querySelector('.agent-draft')).toBeNull()
  expect(backend).toEqual([]) // newSession/send/createAndSend are never reached through the draft UI
  window.projectDirectory = { choose: async () => '/srv/new' }
  await act(async () => { [...container.querySelectorAll('button')].find(node => node.textContent?.includes('Add project'))!.click() })
  expect(backend).toEqual(['addWorkspace:/srv/new'])
  expect(container.querySelector('.agent-project-name[title="/srv/new"]')).not.toBeNull()
  delete window.projectDirectory
})

function fakeWorkbench() {
  const views: { id: string }[] = [], uis: { id: string }[] = [], opened: string[] = []
  const value = {
    forScope: () => ({
      addView: (view: { id: string }) => { views.push(view) },
      addUI: (ui: { id: string }) => { uis.push(ui) },
    }),
    open: (id: string) => { opened.push(id) },
  } as unknown as Workbench
  return { value, views, uis, opened }
}

function fakeCommands() {
  const added: { id: string; execute: () => void }[] = []
  const value = { forScope: () => ({ add: (command: { id: string; execute: () => void }) => { added.push(command) } }) } as unknown as Commands
  return { value, added }
}

it('registers view, command and navigation exactly once in the sessions entry and opens only live views (FC-0004 unique registration)', async () => {
  const scope = new OwnedResources(), registryScope = new OwnedResources()
  cleanup.push(async () => { scope.dispose(); registryScope.dispose() })
  const context = { resources: scope } as unknown as PluginContext
  const sessionsWb = fakeWorkbench(), sessionsCmds = fakeCommands()
  const sessions = createSessionsPlugin().activate(
    context, createAgentConnections(registryScope, createConnections(registryScope)), sessionsCmds.value, sessionsWb.value)
  expect(sessionsWb.views.map(view => view.id)).toEqual(['agent.sessions'])
  expect(sessionsWb.uis.map(ui => ui.id)).toEqual(['agent.navigation'])
  expect(sessionsCmds.added.map(command => command.id)).toEqual(['agent.open'])
  // agent.open opens exactly the live sessions view. The retired
  // ordessa.agent-conversation view (014 P-C PC-6) is never referenced: the
  // Chat page (ordessa.chat) is the conversation surface now.
  sessionsCmds.added[0].execute()
  expect(sessionsWb.opened).toEqual(['agent.sessions'])
  void sessions
})
