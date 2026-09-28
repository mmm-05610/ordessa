// @vitest-environment jsdom
import { act, type ReactNode } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, expect, it } from 'vitest'
import { OwnedResources } from '@ordessa/extension-api'
import { createConnections } from '../../../../packages/desktop-platform/connections/src/index'
import { createAgentConnections } from '../../../../plugins/agent/connections/src/entry'
import { createAgentSessions } from '../../../../plugins/agent/sessions/src/model'
import { Conversation } from '../../../../plugins/agent/conversation/src/view'
import type { AgentClient, AgentSnapshot } from '../../../../plugins/agent/contracts/src/contract'
;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
// jsdom has no geometry; assistant-ui reads resize and scroll on mount.
window.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} }
Element.prototype.scrollTo = () => {}
Element.prototype.scrollIntoView = () => {}
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

/** The whole `agent` slice is read verbatim from the client snapshot (plugins/agent/sessions/src/model.ts),
 *  so every gate input below is controlled without adding any mechanism to production code. */
async function openConversation(initial: Partial<AgentSnapshot> = {}) {
  let snapshot: AgentSnapshot = {
    connection: { id: 'A', title: 'A', status: 'disconnected', capabilities },
    sessions: [{ id: 'S1', title: 'Session one' }, { id: 'S2', title: 'Session two' }],
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
    async newSession() { return 'S3' },
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
  await sessions.openSession('S1')
  const container = await mount(<Conversation service={sessions} />)
  return { container, sessions, write, snapshot: () => snapshot }
}

it('keeps an unknown run outcome distinct from a failure (gate 1)', async () => {
  const { container, write } = await openConversation({ runs: { R1: { id: 'R1', sessionId: 'S1', status: 'unknown' } } })
  const badge = container.querySelector('.agent-run-state')
  expect(badge?.getAttribute('data-status')).toBe('unknown')
  expect(badge?.textContent).toBe('unknown')
  // The disconnect notice and the "unknown outcome" notice are different elements with different roles.
  const notices = [...container.querySelectorAll('p[role=status].agent-notice')].map(node => node.textContent)
  expect(notices).toContain('Run outcome unknown after disconnect.')
  expect(container.querySelector('[data-status=failed]')).toBeNull()
  // Only rendered text may read as a failure: the stylesheet legitimately names a failed tool state.
  const section = container.querySelector('section.agent-conversation')!
  expect([...section.childNodes].filter(node => node.nodeName !== 'STYLE').map(node => node.textContent).join('')).not.toContain('failed')
  // A disconnected connection always renders the loss alert, so alert presence is asserted by its text, not by role count.
  await act(async () => { write({ connection: { id: 'A', title: 'A', status: 'connected', capabilities } }) })
  expect(container.querySelector('[role=alert].agent-error')).toBeNull()
  expect(container.querySelector('.agent-run-state')?.getAttribute('data-status')).toBe('unknown')
  await act(async () => { write({ connection: { id: 'A', title: 'A', status: 'error', error: 'socket closed', capabilities } }) })
  const alerts = [...container.querySelectorAll('[role=alert]')]
  expect(alerts).toHaveLength(1)
  expect(alerts[0].textContent).toContain('The result of an active run is unknown.')
})

it('renders no model entry in the conversation while other options survive (gate 2)', async () => {
  const modelOption = { id: 'model', title: 'Model for next turn', value: 'gpt-5.6-luna', availability: 'supported' as const,
    values: [{ id: 'gpt-5.6-luna', title: 'Luna' }, { id: 'other', title: 'Other' }] }
  const probeOption = { id: 'probe', title: 'Response style', value: 'brief', availability: 'supported' as const,
    values: [{ id: 'brief', title: 'Brief' }] }
  const { container, snapshot } = await openConversation({ options: [modelOption, probeOption] })
  // Reachability first: the thread renders only after connection, agent snapshot and session selection are all present.
  expect(container.querySelector('section.agent-conversation .agent-thread')).not.toBeNull()
  // Counting happens inside the conversation section, never inside .agent-thread (its sibling holds the options).
  const section = container.querySelector('section.agent-conversation')!
  const selects = [...section.querySelectorAll('select')]
  expect(selects).toHaveLength(1)
  expect(selects[0].closest('label')?.textContent).toContain('Response style')
  expect(section.textContent).not.toContain('Model for next turn')
  // The suppression is UI-only: the contract still carries the model option.
  expect(snapshot().options.map(option => option.id)).toContain('model')
})

it('hides thinking and effort alongside the model while a supported option survives (gate 3)', async () => {
  const option = (id: string, title: string) => ({ id, title, value: 'a', availability: 'supported' as const, values: [{ id: 'a', title: 'A' }] })
  const { container } = await openConversation({ options: [option('model', 'Model'), option('thinking', 'Thinking budget'),
    option('effort', 'Reasoning effort'), option('style', 'Response style')] })
  const section = container.querySelector('section.agent-conversation')!
  const selects = [...section.querySelectorAll('select')]
  expect(selects).toHaveLength(1)
  // Positive control in the same render: an unrelated supported option really does reach this surface.
  expect(selects[0].closest('label')?.textContent).toContain('Response style')
  for (const hidden of ['Model', 'Thinking budget', 'Reasoning effort']) expect(section.textContent).not.toContain(hidden)
})

it('labels each tool outcome with the state the connector reported (gate 4)', async () => {
  const tool = (id: string, status: 'running' | 'completed' | 'failed' | 'unknown', result?: string) => ({ id, name: `tool-${id}`, arguments: { path: id }, result, status })
  const message = { id: 'm1', role: 'assistant' as const, text: 'Working', status: 'running' as const,
    tools: [tool('t1', 'running'), tool('t2', 'completed', 'ok'), tool('t3', 'failed', 'denied'), tool('t4', 'unknown')] }
  const { container } = await openConversation({ messages: { S1: [message] } })
  const states = [...container.querySelectorAll('.agent-tool')].map(node => node.getAttribute('data-tool-state'))
  expect(states).toEqual(['running', 'completed', 'failed', 'unknown'])
  // A tool whose outcome is unknown must not read as still running, and a failed one must not read as a result.
  const summaries = [...container.querySelectorAll('.agent-tool summary')].map(node => node.textContent)
  expect(summaries).toEqual(['tool-t1 · Running', 'tool-t2 · Result', 'tool-t3 · Failed', 'tool-t4 · Outcome unknown'])
  expect(container.querySelector('.agent-tool[data-tool-state=unknown] pre')?.textContent).toContain('"path": "t4"')
})

/** Draft-mode harness: the same F2 facade and registry, with a project-capable fake client whose
 *  createAndSend answers however the individual gate needs. */
type Create = (workspaceId: string, text: string, requestId: string) => Promise<{ sessionId: string }>
async function openDraft(initial: Partial<AgentSnapshot> = {}, create?: Create) {
  let snapshot: AgentSnapshot = {
    connection: { id: 'A', title: 'A', status: 'connected', capabilities: { ...capabilities, workspaces: 'supported' } },
    sessions: [{ id: 'S1', title: 'Session one' }],
    sessionList: 'ready', messages: {}, runs: {}, interactions: [], options: [],
    workspaces: { state: 'ready', items: [{ id: 'W1', normalizedPath: '/srv/project' }] }, ...initial,
  }
  const calls = { newSession: 0, create: [] as { workspaceId: string; text: string; requestId: string }[], send: [] as string[] }
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
    async newSession() { calls.newSession++; throw Error('the draft surface must not create a backend session') },
    async openSession(id) { write({ selectedSessionId: id }) },
    async send(_sessionId, text) {
      // A disconnected instance rejects in its own client; the surface must not swallow the text over that.
      if (snapshot.connection.status !== 'connected') throw Error('connection lost before the message was accepted')
      calls.send.push(text)
    },
    async stop() {},
    async respond() {},
    async setOption() {},
    async refreshWorkspaces() {},
    async openWorkspace(id) {
      write({ workspaces: { ...snapshot.workspaces!, selectedWorkspaceId: id } })
      return { id, normalizedPath: '/srv/project' }
    },
    createAndSend: async (workspaceId, text, requestId) => {
      calls.create.push({ workspaceId, text, requestId })
      if (create) return create(workspaceId, text, requestId)
      // Default: the Server accepts and the snapshot confirms the real id, selected and bound to the project.
      write({ sessions: [...snapshot.sessions, { id: 'S9', title: 'Draft run', workspaceId: 'W1' }], selectedSessionId: 'S9' })
      return { sessionId: 'S9' }
    },
  }
  const registryScope = new OwnedResources(), sessionScope = new OwnedResources(), connectorScope = new OwnedResources()
  cleanup.push(async () => { sessionScope.dispose(); connectorScope.dispose(); registryScope.dispose() })
  const registry = createAgentConnections(registryScope, createConnections(registryScope))
  registry.forScope(connectorScope).add({ id: 'A', title: 'A', connect: async () => client })
  const sessions = createAgentSessions(sessionScope, registry)
  await sessions.selectConnection('A')
  const container = await mount(<Conversation service={sessions} />)
  const field = () => container.querySelector<HTMLTextAreaElement>('textarea[aria-label=Message]')!.value
  const typeText = async (value: string) => {
    await act(async () => {
      const input = container.querySelector('textarea[aria-label=Message]')!
      // React tracks the node's value, so only the native setter makes the change look user-made.
      const nativeValue = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value')!.set!
      nativeValue.call(input, value)
      input.dispatchEvent(new Event('input', { bubbles: true }))
    })
  }
  const clickSend = async () => { await act(async () => { container.querySelector<HTMLButtonElement>('.agent-compose button[type=submit]')!.click() }) }
  return { container, sessions, write, calls, field, typeText, clickSend }
}

it('opens a readable draft without touching the client, and blocks send until a project is valid (gate 5)', async () => {
  const { container, sessions, calls, typeText, clickSend, field } = await openDraft()
  // Negative control for reachability: no session and no draft is still the "choose a session" placeholder.
  expect(container.querySelector('section.agent-conversation')).toBeNull()
  expect(container.textContent).toContain('Choose a session')
  await act(async () => { sessions.startDraft?.() })
  expect(container.querySelector('section.agent-conversation')).not.toBeNull()
  expect(container.querySelector('textarea[aria-label=Message]')).not.toBeNull()
  expect(container.textContent).toContain('Nothing has been sent yet')
  expect(calls.newSession).toBe(0)
  expect(calls.create).toEqual([])
  // No project revalidated: the composer says why and points at Sessions, and a click reaches nothing.
  const block = container.querySelector('p[role=status].agent-compose-block')
  expect(block?.textContent).toContain('No project is selected')
  expect(block?.textContent).toContain('Sessions')
  await typeText('summarise the failing test')
  expect(container.querySelector<HTMLButtonElement>('.agent-compose button[type=submit]')!.disabled).toBe(true)
  await clickSend()
  expect(calls.create).toEqual([])
  expect(field()).toBe('summarise the failing test')
})

it('sends a draft once through createAndSend and clears only on snapshot confirmation (gate 6)', async () => {
  const { container, sessions, calls, typeText, clickSend, field } = await openDraft()
  await act(async () => { sessions.startDraft?.() })
  await act(async () => { await sessions.selectWorkspace?.('W1') })
  expect(container.querySelector('p.agent-compose-block')).toBeNull()
  await typeText('start the run')
  expect(container.querySelector<HTMLButtonElement>('.agent-compose button[type=submit]')!.disabled).toBe(false)
  await clickSend()
  expect(calls.create).toEqual([{ workspaceId: 'W1', text: 'start the run', requestId: expect.stringMatching(/^[0-9a-f-]{36}$/) }])
  expect(field()).toBe('')
  // The draft hands over to the confirmed real session instead of staying an unsent form.
  expect(container.querySelector('.agent-conversation-head h2')?.textContent).toBe('Draft run')
})

it('keeps the rejected text verbatim and resends only on an explicit second press (gate 7)', async () => {
  const { container, sessions, calls, typeText, clickSend, field } = await openDraft({}, async () => { throw Error('server refused') })
  await act(async () => { sessions.startDraft?.() })
  await act(async () => { await sessions.selectWorkspace?.('W1') })
  await typeText('refactor the parser\nsecond line')
  await clickSend()
  expect(container.querySelector('[role=alert].agent-error')?.textContent).toContain('server refused')
  expect(field()).toBe('refactor the parser\nsecond line')
  expect(calls.create).toHaveLength(1)
  // No auto-retry: the second attempt exists only because the user pressed Send again, and it reuses the id.
  await clickSend()
  expect(calls.create).toHaveLength(2)
  expect(calls.create[1].text).toBe('refactor the parser\nsecond line')
  expect(calls.create[1].requestId).toBe(calls.create[0].requestId)
})

it('continues an existing session under its own project while the draft gate is closed (gate 8)', async () => {
  const { sessions, calls, typeText, clickSend, container, field } = await openDraft({ selectedSessionId: 'S1' })
  await typeText('follow up on this run')
  await clickSend()
  expect(calls.send).toEqual(['follow up on this run'])
  expect(calls.create).toEqual([])
  // The thread is not remounted here, so this is the case where clearing the composer is real behaviour.
  expect(field()).toBe('')
  expect(container.querySelector('p.agent-compose-block')).toBeNull()
  expect(container.querySelector('.agent-conversation-head small')?.textContent).toBe('SESSION')
  // The draft gate stays closed underneath: the follow-up is not silently unlocking a first send.
  expect(sessions.getSnapshot().draft?.canSend).toBe(false)
})

it('keeps Enter as send and Shift+Enter as a line break (gate 9)', async () => {
  const { sessions, calls, typeText, container, field } = await openDraft({ selectedSessionId: 'S1' })
  const pressEnter = async (shiftKey: boolean) => {
    let prevented = true
    await act(async () => {
      prevented = container.querySelector('textarea[aria-label=Message]')!
        .dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', shiftKey, bubbles: true, cancelable: true })) === false
    })
    return prevented
  }
  await typeText('first')
  expect(await pressEnter(true)).toBe(false)
  expect(calls.send).toEqual([])
  // Positive control for the same event path: the plain press that follows really does reach the service.
  expect(await pressEnter(false)).toBe(true)
  expect(calls.send).toEqual(['first'])
  expect(field()).toBe('')
  await typeText('second line\r\nkept')
  await pressEnter(false)
  // The cleared field really is usable again; the textarea normalizes CRLF to the LF it reports.
  expect(calls.send).toEqual(['first', 'second line\nkept'])
})

it('keeps the composed text across a lost connection and a send attempted while disconnected (gate 10)', async () => {
  const { container, write, calls, typeText, clickSend, field } = await openDraft({ selectedSessionId: 'S1' })
  // The thread renders two independent alerts once a send fails while disconnected, so match on all of them.
  const alerts = () => [...container.querySelectorAll('[role=alert].agent-error')].map(node => node.textContent).join('|')
  await typeText('half-written\r\nmessage')
  await act(async () => { write({ connection: { id: 'A', title: 'A', status: 'error', error: 'socket closed', capabilities: { ...capabilities, workspaces: 'supported' } } }) })
  // The loss alert re-renders the thread; a re-render is not allowed to cost the user their text.
  expect(alerts()).toContain('The result of an active run is unknown.')
  expect(field()).toBe('half-written\nmessage')
  await clickSend()
  expect(calls.send).toEqual([])
  expect(field()).toBe('half-written\nmessage')
  expect(alerts()).toContain('connection lost before the message was accepted')
  // Positive control: the same composer really does work again once the connection returns.
  await act(async () => { write({ connection: { id: 'A', title: 'A', status: 'connected', capabilities: { ...capabilities, workspaces: 'supported' } } }) })
  await clickSend()
  expect(calls.send).toEqual(['half-written\nmessage'])
  expect(field()).toBe('')
})

/** Multi-pane harness: any number of connections carrying the SAME session ids, so a gate can show that
 *  retention is partitioned by connection and by pane rather than by whatever happens to be on screen. */
async function openPanes(connectionIds: string[]) {
  interface Pane { snapshot: AgentSnapshot; listeners: Set<() => void>
    calls: { send: string[]; create: { workspaceId: string; text: string; requestId: string }[]; newSession: number }
    reject?: Error }
  const panes = new Map<string, Pane>()
  for (const id of connectionIds) panes.set(id, {
    calls: { send: [], create: [], newSession: 0 }, listeners: new Set(),
    snapshot: {
      connection: { id, title: id, status: 'connected', capabilities: { ...capabilities, workspaces: 'supported' } },
      sessions: [{ id: 'S1', title: 'Session one' }, { id: 'S2', title: 'Session two' }, { id: 'draft', title: 'A session named like the draft marker' }],
      sessionList: 'ready', messages: {}, runs: {}, interactions: [], options: [],
      workspaces: { state: 'ready', items: [{ id: 'W1', normalizedPath: `/srv/${id}` }] },
    },
  })
  // A connector-side snapshot move, from outside the client: FC-0055's subject is the project becoming
  // invalid after the composer was opened, so the test drives what the Server reports, never gate state.
  const writePane = (id: string, patch: Partial<AgentSnapshot>) => {
    const pane = panes.get(id)!
    pane.snapshot = { ...pane.snapshot, ...patch }
    for (const listener of [...pane.listeners]) listener()
  }
  const registryScope = new OwnedResources(), sessionScope = new OwnedResources(), connectorScope = new OwnedResources()
  cleanup.push(async () => { sessionScope.dispose(); connectorScope.dispose(); registryScope.dispose() })
  const registry = createAgentConnections(registryScope, createConnections(registryScope))
  for (const id of connectionIds) registry.forScope(connectorScope).add({ id, title: id, connect: async () => {
    const pane = panes.get(id)!
    const client: AgentClient = {
      get isDisposed() { return false },
      dispose() { pane.listeners.clear() },
      getSnapshot: () => pane.snapshot,
      subscribe(listener) { pane.listeners.add(listener); return () => { pane.listeners.delete(listener) } },
      async refreshSessions() {},
      async newSession() { pane.calls.newSession++; throw Error('the draft surface must not create a backend session') },
      async openSession(opened) { writePane(id, { selectedSessionId: opened }) },
      async send(_sessionId, text) { pane.calls.send.push(text) },
      async stop() {}, async respond() {}, async setOption() {}, async refreshWorkspaces() {},
      async openWorkspace(workspaceId) {
        writePane(id, { workspaces: { ...pane.snapshot.workspaces!, selectedWorkspaceId: workspaceId } })
        return { id: workspaceId, normalizedPath: `/srv/${id}` }
      },
      createAndSend: async (workspaceId, text, requestId) => {
        pane.calls.create.push({ workspaceId, text, requestId })
        if (pane.reject) throw pane.reject
        writePane(id, { sessions: [...pane.snapshot.sessions, { id: 'S9', title: 'Draft run', workspaceId }], selectedSessionId: 'S9' })
        return { sessionId: 'S9' }
      },
    }
    return client
  } })
  const sessions = createAgentSessions(sessionScope, registry)
  await sessions.selectConnection(connectionIds[0])
  const container = await mount(<Conversation service={sessions} />)
  const field = () => container.querySelector<HTMLTextAreaElement>('textarea[aria-label=Message]')!.value
  const typeText = async (value: string) => {
    await act(async () => {
      const input = container.querySelector('textarea[aria-label=Message]')!
      const nativeValue = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value')!.set!
      nativeValue.call(input, value)
      input.dispatchEvent(new Event('input', { bubbles: true }))
    })
  }
  const clickSend = async () => { await act(async () => { container.querySelector<HTMLButtonElement>('.agent-compose button[type=submit]')!.click() }) }
  return {
    container, field, typeText, clickSend, calls: (id: string) => panes.get(id)!.calls,
    paneTitle: () => container.querySelector('.agent-conversation-head h2')?.textContent,
    paneLabel: () => container.querySelector('.agent-conversation-head small')?.textContent,
    threadText: () => container.querySelector('.agent-thread')?.textContent ?? '',
    openSession: async (target: string) => { await act(async () => { await sessions.openSession(target) }) },
    selectConnection: async (target: string) => { await act(async () => { await sessions.selectConnection(target) }) },
    startDraft: async () => { await act(async () => { sessions.startDraft?.() }) },
    discardDraft: async () => { await act(async () => { sessions.discardDraft?.() }) },
    selectWorkspace: async (target: string) => { await act(async () => { await sessions.selectWorkspace?.(target) }) },
    write: async (id: string, patch: Partial<AgentSnapshot>) => { await act(async () => { writePane(id, patch) }) },
    rejectNextCreate: (id: string, error: Error) => { panes.get(id)!.reject = error },
  }
}

it('gives every session its own unsent text across switching and sends nothing on a switch (gate 11)', async () => {
  const h = await openPanes(['A'])
  // A session whose id happens to be the draft marker must not inherit the draft's buffer: the two pane
  // identities are prefixed, not merely distinct strings (FC-0052).
  await h.startDraft()
  await h.typeText('draft text')
  await h.openSession('draft')
  expect(h.field()).toBe('')
  await h.openSession('S1')
  await h.typeText('half-typed in S1')
  await h.openSession('S2')
  // A pane the user never typed in stays empty: this is per-pane retention, not one shared buffer.
  expect(h.field()).toBe('')
  await h.typeText('half-typed in S2')
  await h.openSession('S1')
  expect(h.field()).toBe('half-typed in S1')
  await h.openSession('S2')
  expect(h.field()).toBe('half-typed in S2')
  expect(h.calls('A').send).toEqual([])
  // Positive control: the restored text is the live value, not a display echo — sending it ships exactly that.
  await h.openSession('S1')
  await h.clickSend()
  expect(h.calls('A').send).toEqual(['half-typed in S1'])
  expect(h.field()).toBe('')
  await h.openSession('S2')
  expect(h.field()).toBe('half-typed in S2')
})

it('keeps the same session id on two connections apart and sends nothing on a connection switch (gate 12)', async () => {
  const h = await openPanes(['A', 'B'])
  await h.openSession('S1')
  await h.typeText('written on A')
  await h.selectConnection('B')
  // B has no selection yet, so it shows the placeholder rather than A's half-written text.
  expect(h.container.textContent).toContain('Choose a session')
  await h.openSession('S1')
  expect(h.field()).toBe('')
  await h.typeText('written on B')
  await h.selectConnection('A')
  // A kept its own selection, and with it its own text: the two S1 panes never share a buffer.
  expect(h.paneTitle()).toBe('Session one')
  expect(h.field()).toBe('written on A')
  await h.selectConnection('B')
  expect(h.field()).toBe('written on B')
  expect(h.calls('A').send).toEqual([])
  expect(h.calls('B').send).toEqual([])
  expect(h.calls('A').create).toEqual([])
})

it('keeps a draft across a connection round trip, and empties it on discard and after a confirmed send (gate 13)', async () => {
  const h = await openPanes(['A', 'B'])
  await h.startDraft()
  await h.typeText('draft that waits while I look at B')
  await h.selectConnection('B')
  await h.startDraft()
  expect(h.field()).toBe('')
  await h.selectConnection('A')
  // A's draft was never discarded, only unselected: a connection switch must not cost the text.
  expect(h.paneTitle()).toBe('New session')
  expect(h.field()).toBe('draft that waits while I look at B')
  await h.discardDraft()
  expect(h.container.textContent).toContain('Choose a session')
  await h.startDraft()
  expect(h.field()).toBe('')
  // The first send the snapshot confirms clears the draft, and its text does not follow into the session.
  await h.selectWorkspace('W1')
  await h.typeText('opens the real session')
  await h.clickSend()
  expect(h.calls('A').create).toEqual([{ workspaceId: 'W1', text: 'opens the real session', requestId: expect.stringMatching(/^[0-9a-f-]{36}$/) }])
  expect(h.paneTitle()).toBe('Draft run')
  expect(h.field()).toBe('')
  await h.openSession('S1')
  expect(h.field()).toBe('')
  expect(h.calls('A').send).toEqual([])
})

/** FC-0055 asks whether the draft composer can still advertise a project that has deterministically
 *  gone away. This surface holds no project authority of its own — `draft.canSend` is a pure projection
 *  of what the connector reports — so the two shapes FC-0055 distinguishes are pinned separately. */
it('blocks a mid-draft invalidation whose stale selection the connector clears, without costing the text (gate 14)', async () => {
  const h = await openPanes(['A'])
  await h.startDraft()
  await h.selectWorkspace('W1')
  await h.typeText('fix the flaky parser spec')
  expect(h.container.querySelector('p.agent-compose-block')).toBeNull()
  // The FC-0055 fix shape: the connector drops the selection it can no longer honour.
  await h.write('A', { workspaces: { state: 'ready', items: [{ id: 'W1', normalizedPath: '/srv/A' }] } })
  expect(h.container.querySelector('p[role=status].agent-compose-block')?.textContent).toContain('No project is selected')
  // Blocking must never cost the composition (FC-0043 / FC-0052), and must reach no client.
  expect(h.field()).toBe('fix the flaky parser spec')
  expect(h.container.querySelector<HTMLButtonElement>('.agent-compose button[type=submit]')!.disabled).toBe(true)
  await h.clickSend()
  expect(h.calls('A').create).toEqual([])
  // Positive control: the same preserved text really does go out once a project is re-selected.
  await h.selectWorkspace('W1')
  expect(h.container.querySelector('p.agent-compose-block')).toBeNull()
  expect(h.field()).toBe('fix the flaky parser spec')
  await h.clickSend()
  expect(h.calls('A').create.map(call => call.text)).toEqual(['fix the flaky parser spec'])
  expect(h.field()).toBe('')
})

it('mirrors an invalidation the connector does not report: the send is offered and the typed refusal keeps the text (gate 15)', async () => {
  const h = await openPanes(['A'])
  h.rejectNextCreate('A', Error('LOCAL_PATH_MISSING: the project directory is gone'))
  await h.startDraft()
  await h.selectWorkspace('W1')
  await h.typeText('triage the build failure')
  // The project leaves the ready list while the connector still reports it selected, and revalidation
  // runs only on connect and reconnect (plugins/agent/sessions/src/model.ts:101, :102).
  await h.write('A', { workspaces: { state: 'ready', items: [], selectedWorkspaceId: 'W1' } })
  // Measured consequence, not an approval: this surface cannot detect that staleness without inventing a
  // second project authority, so it advertises sendable and the Server's typed refusal is what stops it.
  expect(h.container.querySelector('p.agent-compose-block')).toBeNull()
  expect(h.container.querySelector<HTMLButtonElement>('.agent-compose button[type=submit]')!.disabled).toBe(false)
  await h.clickSend()
  expect(h.calls('A').create).toHaveLength(1)
  expect(h.container.querySelector('[role=alert].agent-error')?.textContent).toContain('LOCAL_PATH_MISSING')
  expect(h.field()).toBe('triage the build failure')
  // One attempt per explicit press: nothing retried on its own between the two clicks.
  await h.clickSend()
  expect(h.calls('A').create).toHaveLength(2)
  expect(h.calls('A').create[1].requestId).toBe(h.calls('A').create[0].requestId)
})

it('gives the pane, the key and the session identity to a draft that overlaps a live selection (gate 16)', async () => {
  const h = await openPanes(['A'])
  // FC-0060's counterexample. The facade now keeps the previous selection live through a draft and leans
  // on draft-first routing (F2-0010), so "draft active while S1 is selected" is the ordinary case — the
  // exact shape a split patch leaked, where the draft composer opened with S1's text and then wrote its
  // own text back over S1's buffer.
  await h.write('A', {
    messages: { S1: [{ id: 'm1', role: 'user', text: 'history that belongs to S1 only', status: 'completed' }] },
    runs: { R1: { id: 'R1', sessionId: 'S1', status: 'running' } },
    interactions: [{ id: 'I1', sessionId: 'S1', kind: 'approval', title: 'Approval owed to S1 only', state: 'pending' }],
  })
  await h.openSession('S1')
  await h.typeText('half-written work belonging to S1')
  await h.startDraft()
  expect(h.paneLabel()).toBe('NEW SESSION')
  expect(h.field()).toBe('')
  // S1 keeps its own thread: no history, no run, no pending card follows the draft pane.
  expect(h.threadText()).not.toContain('history that belongs to S1 only')
  expect(h.container.querySelector('.agent-interaction')).toBeNull()
  expect(h.container.querySelector('.agent-run-state')?.textContent).toBe('idle')
  expect(h.calls('A')).toEqual({ send: [], create: [], newSession: 0 })
  await h.typeText('a sentence that belongs to the new session')
  expect(h.calls('A')).toEqual({ send: [], create: [], newSession: 0 })
  // Discard is final: S1 comes back with S1's text, and the draft sentence never crosses into it.
  await h.discardDraft()
  expect(h.paneLabel()).toBe('SESSION')
  expect(h.field()).toBe('half-written work belonging to S1')
  expect(h.threadText()).toContain('history that belongs to S1 only')
  expect(h.container.querySelector('.agent-interaction')?.textContent).toContain('Approval owed to S1 only')
  expect(h.container.querySelector('.agent-run-state')?.textContent).toBe('running')
  // A second New session starts empty, because 'discarded' cleared the draft buffer.
  await h.startDraft()
  expect(h.field()).toBe('')
  await h.discardDraft()
})

it('resumes a stepped-away draft and routes its first send to createAndSend, never the selected session (gate 17)', async () => {
  const h = await openPanes(['A'])
  await h.openSession('S1')
  await h.startDraft()
  await h.selectWorkspace('W1')
  await h.typeText('draft text stepped away from')
  // Ending a draft by opening another session is a step-away (endedBy: 'opened'), not a discard.
  await h.openSession('S2')
  expect(h.paneLabel()).toBe('SESSION')
  expect(h.field()).toBe('')
  await h.startDraft()
  expect(h.field()).toBe('draft text stepped away from')
  // Resumed from the original S2 selection, the first send still goes to createAndSend exactly once.
  await h.clickSend()
  expect(h.calls('A').create).toHaveLength(1)
  expect(h.calls('A').create[0]).toMatchObject({ workspaceId: 'W1', text: 'draft text stepped away from' })
  expect(h.calls('A').send).toEqual([])
  expect(h.paneTitle()).toBe('Draft run')
  expect(h.field()).toBe('')
})

it('keeps both unsent buffers when opening the same session that was selected before the draft (gate 18)', async () => {
  const h = await openPanes(['A'])
  await h.openSession('S1')
  await h.typeText('S1 unfinished text')
  await h.startDraft()
  expect(h.field()).toBe('')
  await h.typeText('draft unfinished text')
  // F2 reports opened even when the target is the original S1. Selection equality must not
  // turn this step-away into a discard, or overwrite S1's own unsent composer buffer.
  await h.openSession('S1')
  expect(h.paneLabel()).toBe('SESSION')
  expect(h.field()).toBe('S1 unfinished text')
  await h.startDraft()
  expect(h.paneLabel()).toBe('NEW SESSION')
  expect(h.field()).toBe('draft unfinished text')
  expect(h.calls('A')).toEqual({ send: [], create: [], newSession: 0 })
})
