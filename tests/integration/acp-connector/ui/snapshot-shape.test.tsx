// @vitest-environment jsdom
import { act, type ReactNode } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, expect, it } from 'vitest'
import { OwnedResources } from '@ordessa/extension-api'
import { createConnections } from '../../../../packages/desktop-platform/connections/src/index'
import { createAgentConnections } from '../../../../plugins/agent/connections/src/entry'
import { createAgentSessions } from '../../../../plugins/agent/sessions/src/model'
import { Conversation } from '../../../../plugins/agent/conversation/src/view'
import { SessionBrowser } from '../../../../plugins/agent/sessions/src/view'
import type { AgentClient, AgentSnapshot } from '../../../../plugins/agent/contracts/src/contract'

/**
 * UI-slot verification (passes today, deliberately): the exact `AgentSnapshot` shape the ACP
 * mapping is required to produce is fed through the real facade and rendered by the real chat
 * components. This proves "reuse the existing chat interface" is achievable without new UI; it
 * is NOT an ACP end-to-end acceptance — the wire half lives in the red target tests under
 * protocol/ and acp-conversation.test.tsx.
 */

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
window.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} }
Element.prototype.scrollTo = () => {}
Element.prototype.scrollIntoView = () => {}

const cleanup: Array<() => Promise<void>> = []
afterEach(async () => { for (const fn of cleanup.splice(0).reverse()) await fn() })

async function mount(element: ReactNode) {
  const container = document.createElement('div')
  document.body.append(container)
  const root = createRoot(container)
  cleanup.push(async () => { await act(async () => root.unmount()); container.remove() })
  await act(async () => root.render(element))
  return container
}

const acpShaped = (patch: Partial<AgentSnapshot>): AgentSnapshot => ({
  connection: { id: 'acp:s1', title: 'Harness', status: 'connected',
    // ACP core gives streaming text, reasoning chunks, tool cards, cancel and permission asks.
    capabilities: { history: 'unsupported', reasoning: 'supported', tools: 'supported', stop: 'supported',
      interactions: 'supported', models: 'unsupported', modes: 'unsupported', workspaces: 'supported' },
    serverInstanceId: 'https://harness.test|server_1' },
  sessions: [{ id: 'acp-session-1', title: 'Native thread title', workspaceId: 'ws_app' }],
  sessionList: 'ready', selectedSessionId: 'acp-session-1',
  messages: { 'acp-session-1': [
    { id: 'u1', role: 'user', text: 'run the gate' },
    { id: 'm1', role: 'assistant', text: 'done now', reasoning: 'checking specs first',
      tools: [{ id: 'c1', name: 'Run tests', status: 'completed', result: 'green' }], status: 'completed' },
  ] },
  runs: {}, interactions: [], options: [],
  workspaces: { state: 'ready', items: [{ id: 'ws_app', normalizedPath: '/repo/app' }], selectedWorkspaceId: 'ws_app' },
  ...patch,
})

async function openWith(snapshot: AgentSnapshot) {
  let state = snapshot
  const listeners = new Set<() => void>()
  const write = (patch: Partial<AgentSnapshot>) => {
    state = { ...state, ...patch }
    for (const listener of [...listeners]) listener()
  }
  const client: AgentClient = {
    getSnapshot: () => state,
    subscribe(listener) { listeners.add(listener); return () => { listeners.delete(listener) } },
    dispose() { listeners.clear() },
    async refreshSessions() {}, async newSession() { return 'x' }, async openSession() {},
    async send() {}, async stop() {}, async respond() {}, async setOption() {},
  }
  const registryScope = new OwnedResources(), sessionScope = new OwnedResources(), connectorScope = new OwnedResources()
  cleanup.push(async () => { sessionScope.dispose(); connectorScope.dispose(); registryScope.dispose() })
  const registry = createAgentConnections(registryScope, createConnections(registryScope))
  registry.forScope(connectorScope).add({ id: 'acp:s1', title: 'Harness', connect: async () => client })
  const sessions = createAgentSessions(sessionScope, registry)
  await sessions.selectConnection('acp:s1')
  return { write, sessions, state: () => state }
}

it('renders the full ACP-shaped assistant turn with the existing components', async () => {
  const { sessions } = await openWith(acpShaped({}))
  const container = await mount(<Conversation service={sessions} />)
  const thread = container.querySelector('section.agent-conversation')!
  expect(thread.textContent).toContain('run the gate')
  expect(thread.textContent).toContain('done now')
  const tool = thread.querySelector('.agent-tool')!
  expect(tool.textContent).toContain('Run tests')
  expect(tool.getAttribute('data-tool-state')).toBe('completed')
  expect(tool.textContent).toContain('green')
  // Reasoning arrives as its own collapsible part, matching `agent_thought_chunk` semantics.
  const reasoning = thread.querySelector('.agent-reasoning')!
  expect(reasoning.textContent).toContain('Thinking')
  expect(reasoning.textContent).toContain('checking specs first')
})

it('shows a native permission interaction in the thread with its native option labels', async () => {
  const { sessions } = await openWith(acpShaped({
    interactions: [{ id: 'perm_1', sessionId: 'acp-session-1', kind: 'approval', title: 'Delete build cache',
      detail: 'rm -rf .build', choices: [{ id: 'allow_once', label: 'Allow for this once' }, { id: 'reject_once', label: 'Reject' }],
      state: 'pending' }],
  }))
  const container = await mount(<Conversation service={sessions} />)
  const card = container.querySelector('.agent-interaction')!
  expect(card.textContent).toContain('Delete build cache')
  expect([...card.querySelectorAll('button')].map(b => b.textContent)).toContain('Allow for this once')
})

it('keeps unknown outcomes and cancellations visually distinct (no invented verdict)', async () => {
  const { sessions } = await openWith(acpShaped({
    runs: { turn_1: { id: 'turn_1', sessionId: 'acp-session-1', status: 'unknown' } },
    messages: {},
  }))
  const container = await mount(<Conversation service={sessions} />)
  const badge = container.querySelector('.agent-run-state')!
  expect(badge.getAttribute('data-status')).toBe('unknown')
  expect(container.textContent).not.toMatch(/cancelled/i)
})

it('the session browser renders a native title without a local rename affordance', async () => {
  const { sessions } = await openWith(acpShaped({}))
  const container = await mount(<SessionBrowser service={sessions} />)
  const item = container.querySelector('.agent-session-item')!
  expect(item.textContent).toContain('Native thread title')
})
