// @vitest-environment jsdom
import { act, type ReactNode } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, expect, it } from 'vitest'
import { OwnedResources } from '@ordessa/extension-api'
import { createConnections } from '../../../../packages/desktop-platform/connections/src/index'
import { createAgentConnections } from '../../../../plugins/agent/connections/src/entry'
import { createAgentSessions } from '../../../../plugins/agent/sessions/src/model'
import { Conversation } from '../../../../plugins/agent/conversation/src/view'
import { HarnessPeer } from '../fixtures/acp-peer'
import { loadAcpTarget } from '../fixtures/target-seam'

/**
 * UI consumption layer targets U1–U6. These mount the real chat UI (Conversation view over the
 * real AgentSessions facade and AgentConnections workspace) with the real ACP connector behind it
 * and one controllable Harness peer on the wire — no hand-written AgentClient stand-in, so a pass
 * here proves the ACP semantics survive into the existing interface unchanged. Red today: the
 * connector seam is missing (TARGET_MISSING); that is the honest state, not an accepted one.
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

async function openAcpChat(options: { capabilities?: any; extraConnector?: (registry: any, scope: any) => Promise<{ id: string; peer: HarnessPeer }> } = {}) {
  const target = await loadAcpTarget()
  const peer = new HarnessPeer(options)
  const released: string[] = []
  const scopes = { connector: new OwnedResources(), session: new OwnedResources() }
  cleanup.push(async () => { scopes.session.dispose(); scopes.connector.dispose() })
  const connector = target.createConnector({
    serverInstanceId: 'https://harness.test|server_1',
    harness: { id: 'pi', title: 'PI Harness' },
    listProjects: async () => [{ id: 'ws_app', normalizedPath: '/repo/app' }],
    openProject: async (id: string) => {
      if (id !== 'ws_app') throw new Error(`project-invalid: ${id}`)
      return { id: 'ws_app', normalizedPath: '/repo/app' }
    },
    // The channel is acquired for the bound project only — selecting this connector opens none.
    // The handle carries the authoritative binding and an explicit release; a view switch or a
    // transport close is never a backend release.
    acquireChannel: async (id: string) => {
      if (id !== 'ws_app') throw new Error(`project-invalid: ${id}`)
      return {
        connectionId: 'chan_ui_a',
        binding: { id: 'ws_app', normalizedPath: '/repo/app' },
        stream: peer.stream,
        release: async () => { released.push('ws_app'); peer.close() },
      }
    },
  })
  const registry = createAgentConnections(scopes.connector, createConnections(scopes.connector))
  registry.forScope(scopes.connector).add(connector)
  const extra = options.extraConnector ? await options.extraConnector(registry, scopes.connector) : undefined
  const sessions = createAgentSessions(scopes.session, registry)
  await act(async () => { await sessions.selectConnection(connector.id) })
  const container = await mount(<Conversation service={sessions} />)
  return { container, peer, sessions, connector, target, registry, scopes, extra, released }
}

const textOf = (container: HTMLElement) => container.querySelector('section.agent-conversation')?.textContent ?? ''
const sendButton = (container: HTMLElement) =>
  [...container.querySelectorAll('button')].find(b => /^(Send|Start session)$/.test(b.textContent ?? ''))

it('U1 first send from a draft is blocked until a project is bound', async () => {
  const { peer, sessions, container } = await openAcpChat()
  act(() => { sessions.startDraft!() })
  // The existing composer already carries the draft/project gate — no new UI slot needed.
  expect(sendButton(container)?.textContent).toBe('Start session')
  expect(sendButton(container)?.disabled).toBe(true)
  const blocked = await sessions.send('hello').then(() => undefined, error => error)
  expect(String(blocked ?? '')).toMatch(/project gate|no-project/)
  // A draft with no bound project must not have opened a project-less channel: no initialize,
  // no native session. The gate stops it before the connector is ever reached.
  expect(peer.recorded('initialize')).toHaveLength(0)
  expect(peer.recorded('session/new')).toHaveLength(0)
  peer.close()
})

it('U2 the first send into a bound project creates the native session and renders both sides', async () => {
  const { container, peer, sessions } = await openAcpChat()
  await act(async () => { await sessions.selectWorkspace!('ws_app') })
  act(() => { sessions.startDraft!() })
  peer.queueTurn(async api => {
    await api.update({ sessionUpdate: 'agent_message_chunk', messageId: 'm1', content: { type: 'text', text: 'Hi from the Harness' } })
    return 'end_turn'
  })
  await act(async () => { await sessions.send('summarize the gate') })
  expect(textOf(container)).toContain('Hi from the Harness')
  expect(textOf(container)).toContain('summarize the gate')
  // One real session; the draft is gone.
  expect(peer.recorded('session/new')).toHaveLength(1)
  peer.close()
})

it('U3 a tool card is updated in place by toolCallId, never duplicated', async () => {
  const { container, peer, sessions } = await openAcpChat()
  await act(async () => { await sessions.selectWorkspace!('ws_app') })
  act(() => { sessions.startDraft!() })
  peer.queueTurn(async api => {
    await api.update({ sessionUpdate: 'tool_call', toolCallId: 'c1', title: 'Run tests', status: 'pending' })
    return 'end_turn'
  })
  await act(async () => { await sessions.send('run the gate') })
  expect([...container.querySelectorAll('.agent-tool')]).toHaveLength(1)
  expect(container.querySelector('.agent-tool')?.textContent).toContain('Run tests')
  const sessionId = peer.recorded('session/prompt')[0].params.sessionId
  peer.queueTurn(async api => {
    await api.update({ sessionUpdate: 'tool_call_update', toolCallId: 'c1', status: 'completed',
      content: [{ type: 'content', content: { type: 'text', text: 'green' } }] })
    return 'end_turn'
  })
  await act(async () => { await sessions.send('and now?') })
  // Same id, still one card — now carrying the terminal state.
  expect([...container.querySelectorAll('.agent-tool')]).toHaveLength(1)
  expect(container.querySelector('.agent-tool')?.getAttribute('data-tool-state')).toBe('completed')
  void sessionId
  peer.close()
})

it('U4 a permission request renders an in-thread card whose buttons are the native options', async () => {
  const { container, peer, sessions } = await openAcpChat()
  await act(async () => { await sessions.selectWorkspace!('ws_app') })
  act(() => { sessions.startDraft!() })
  let answer: any
  peer.queueTurn(async api => {
    // The native optionId deliberately differs from its kind, so the wire answer must carry
    // 'proceed_once' — a connector substituting the kind would be caught here.
    answer = await api.permission({ toolCallId: 'c1', title: 'Delete build cache', status: 'pending' },
      [{ optionId: 'proceed_once', name: 'Allow for this once', kind: 'allow_once' },
        { optionId: 'refuse_once', name: 'Reject', kind: 'reject_once' }])
    await api.update({ sessionUpdate: 'agent_message_chunk', messageId: 'm1', content: { type: 'text', text: 'cleaned' } })
    return 'end_turn'
  })
  const sending = act(async () => { await sessions.send('clean the cache') })
  await peer.waitFor('the interaction card', () => !!container.querySelector('.agent-interaction'))
  const card = container.querySelector('.agent-interaction')!
  expect(card.textContent).toContain('Delete build cache')
  const buttons = [...card.querySelectorAll('button')].map(b => b.textContent)
  expect(buttons).toContain('Allow for this once')
  expect(buttons).toContain('Reject')
  const allow = [...card.querySelectorAll('button')].find(b => b.textContent === 'Allow for this once')!
  await act(async () => { allow.click() })
  await sending
  expect(answer).toMatchObject({ outcome: { outcome: 'selected', optionId: 'proceed_once' } })
  expect(textOf(container)).toContain('cleaned')
  peer.close()
})

it('U5 a dropped channel shows the run outcome as unknown, distinct from cancelled', async () => {
  const { container, peer, sessions } = await openAcpChat()
  await act(async () => { await sessions.selectWorkspace!('ws_app') })
  act(() => { sessions.startDraft!() })
  // The drop arrives AFTER the first inbound, else the pinned R7 rule (no inbound before a drop ⇒
  // createAndSend rejects, the draft stays, the pane shows 'idle') makes the 'unknown' badge here
  // unsatisfiable. One chunk first is what a real link reset mid-run looks like: traffic flowed,
  // then it stopped. The zero-output link death is kept as its own honest case below (U5b).
  peer.queueTurn(async api => {
    await api.update({ sessionUpdate: 'agent_message_chunk', messageId: 'm1', content: { type: 'text', text: 'working on it' } })
    await api.cancelled(); return 'cancelled'
  })
  const sending = act(async () => { await sessions.send('long task').catch(() => undefined) })
  await peer.waitFor('the running turn', () => peer.recorded('session/prompt').length === 1)
  peer.drop(new Error('link reset'))
  await sending
  const badge = container.querySelector('.agent-run-state')
  expect(badge?.getAttribute('data-status')).toBe('unknown')
  expect(container.textContent).toContain('unknown')
  expect(container.textContent).not.toMatch(/cancelled/i)
  peer.close()
})

it('U5b a link that dies before any output stays an unaccepted draft: the send failed, nothing was ever cancelled', async () => {
  // The reviewed no-output scenario, kept as its own case (round-2 directive): the drop replaces
  // no script and is not swapped for a leading chunk. R7's pinned rule applies here instead:
  // zero inbound before the death ⇒ createAndSend rejects, the draft is never ended by it, and
  // the honest run verdict is unknown — the UI must claim neither a cancelled run nor an
  // accepted session it never got.
  const { container, peer, sessions } = await openAcpChat()
  await act(async () => { await sessions.selectWorkspace!('ws_app') })
  act(() => { sessions.startDraft!() })
  peer.queueTurn(async api => { await api.cancelled(); return 'cancelled' })
  let failure: unknown
  const sending = act(async () => { await sessions.send('long task').catch(error => { failure = error }) })
  await peer.waitFor('the first prompt to leave', () => peer.recorded('session/prompt').length === 1)
  peer.drop(new Error('link reset before any output'))
  await sending
  expect(failure).toBeInstanceOf(Error)
  // The draft survived the failed send: input and request id are held for an idempotent retry,
  // and no session was accepted (session list still empty of real native ids).
  expect(sessions.getSnapshot().draft?.active).toBe(true)
  // The authoritative run verdict is unknown — never a fake cancelled — and the draft pane
  // honestly shows no live run rather than inventing one.
  const agent = sessions.getSnapshot().agent
  expect(agent && Object.values(agent.runs).some(r => r.status === 'unknown')).toBe(true)
  expect(agent && Object.values(agent.runs).every(r => r.status !== 'cancelled')).toBe(true)
  expect(container.querySelector('.agent-run-state')?.getAttribute('data-status')).toBe('idle')
  expect(container.textContent).not.toMatch(/cancelled/i)
  peer.close()
})

it('U6 switching the selection removes the old pending interaction from view without ever answering or releasing it', async () => {
  const { container, peer, sessions, target, registry, scopes, released } = await openAcpChat()
  const peerB = new HarnessPeer()
  cleanup.push(async () => peerB.close())
  const connectorB = target.createConnector({
    serverInstanceId: 'https://harness.test|server_2',
    harness: { id: 'pi2', title: 'Other Harness' },
    listProjects: async () => [{ id: 'ws_b', normalizedPath: '/repo/b' }],
    openProject: async (id: string) => ({ id, normalizedPath: '/repo/b' }),
    acquireChannel: async (id: string) => ({
      connectionId: 'chan_ui_b',
      binding: { id, normalizedPath: '/repo/b' },
      stream: peerB.stream,
      release: async () => peerB.close(),
    }),
  })
  registry.forScope(scopes.connector).add(connectorB)
  await act(async () => { await sessions.selectWorkspace!('ws_app') })
  act(() => { sessions.startDraft!() })
  let answered = false
  peer.queueTurn(async api => {
    const answer = await api.permission({ toolCallId: 'c1', title: 'Delete build cache', status: 'pending' },
      [{ optionId: 'proceed_once', name: 'Allow', kind: 'allow_once' }])
    answered = answer.outcome.outcome === 'selected'
    return 'end_turn'
  })
  const sending = act(async () => { await sessions.send('clean it').catch(() => undefined) })
  await peer.waitFor('the interaction card', () => !!container.querySelector('.agent-interaction'))
  // Switching to the other Harness is a view/selection move, not a dispose: the thread may not keep
  // offering an answer for a request that belongs to the other connection, and switching may not
  // implicitly cancel or answer it — A's request simply remains A's, un-answered.
  await act(async () => { await sessions.selectConnection(connectorB.id) })
  expect(container.querySelector('.agent-interaction button')).toBeNull()
  expect(textOf(container)).not.toContain('Delete build cache')
  expect(peerB.recorded('session/prompt')).toHaveLength(0)
  // And the move is view-only: A's backend channel was NOT released by switching away from it.
  // (Release-on-explicit-dispose is the protocol layer's R24; no dispose happens in this test.)
  expect(released).toEqual([])
  await sending
  expect(answered).toBe(false)
  peer.close()
})
