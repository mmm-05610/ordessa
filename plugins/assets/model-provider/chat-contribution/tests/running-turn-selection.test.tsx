// @vitest-environment jsdom
// N2.2 — selecting a model while a turn is RUNNING, and the inertness of
// ordinary composer activity.
//
// Contract under test (FR-04 / 021 §6b):
// - a pick made while output is running is QUEUED ONLY. It must not cancel the
//   run, interrupt it, restart it, or start a second prompt; the queued intent
//   is applied on the next EXPLICIT send;
// - ordinary typing / caret movement (Chat reprojects the composer location on
//   every keystroke) must not trigger any query, reconcile, apply or submit.
//
// The "no cancel / no interrupt" half is asserted as an ALLOWLIST over every
// wire method the whole interaction emits, plus the absence of any stop call —
// so a future interrupt path fails this test rather than passing unnoticed.
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, expect, it, vi } from 'vitest'
import { OwnedResources } from '@ordessa/extension-api'
import { createChatContributions, type ChatSubmissionSnapshot } from '@extensions/ordessa.chat-api/contract.js'
import { ChatModelSelector, registerModelSelector, type SelectorWiring } from '../src/chat-api-entry'
import type { AgentWorkspaceSnapshot } from '@extensions/ordessa.agent-contracts/contract.js'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
const roots: ReturnType<typeof createRoot>[] = []
afterEach(async () => { for (const root of roots.splice(0)) await act(async () => root.unmount()); document.body.replaceChildren() })

const location = { kind: 'session' as const, connectionId: 'conn', serverInstanceId: 'srv',
  sessionId: 'native', harnessId: 'pi', contextRevision: 0 }
const native = { sessionId: 'native', serverInstanceId: 'srv', harnessId: 'pi', nativeSessionId: 'native',
  connectionId: 'channel', workspaceId: '/fixture' }
const config = { id: 'p', version: 7, displayName: 'Fixture', harness: 'pi', archivedAt: null,
  models: [{ modelId: 'm', availability: 'available' }] }
const verdict = { verdict: 'supported', reason: 'fixture evidence', providerConfigId: 'p', configVersion: 7 }
const emptyObservation = { desired: null, lastConfirmed: null, revision: null, intentRoute: null }
const INTERRUPTIVE = /cancel|abort|interrupt|stop|kill|terminate/i
/** The complete set of read/queue methods a composer selection may use. */
const SELECTION_ALLOWLIST = ['modelProvider.inspectChoice', 'modelProvider.queryChoice',
  'modelProvider.chooseForSession']

function facade(run?: { id: string; status: string }) {
  const listeners = new Set<() => void>()
  // cached by identity: useSyncExternalStore requires a stable snapshot object
  const idle: AgentWorkspaceSnapshot = { available: [], selectedConnectionId: 'conn',
    selectionRevision: 1, runtimeGeneration: 1,
    agent: { selectedSessionId: 'native', connection: { status: 'connected' } } }
  let current: AgentWorkspaceSnapshot = run
    ? { ...idle, agent: { ...idle.agent, runs: { [run.id]: { id: run.id, sessionId: 'native', status: run.status } } } }
    : idle
  const stopped: string[] = []
  const sessions = {
    getSnapshot: () => current,
    subscribe: (fn: () => void) => { listeners.add(fn); return () => listeners.delete(fn) },
    prepareSubmission: vi.fn().mockResolvedValue(native),
    stop: vi.fn(async (runId: string) => { stopped.push(runId) }),
  }
  return { sessions, stopped, emit: () => { for (const fn of [...listeners]) fn() },
    setRunStatus: (status: string) => { current = { ...current, agent: { ...current.agent,
      runs: { [run!.id]: { id: run!.id, sessionId: 'native', status } } } } } }
}
const invokeOf = () => {
  let applied = 0
  return vi.fn(async (method: string) => {
    if (method === 'modelProvider.inspectChoice') return verdict
    if (method === 'modelProvider.queryChoice') return emptyObservation
    if (method === 'modelProvider.beginTurnApplication') {
      // the Server owns the truth: one queued intent applies, an empty queue
      // answers no-intent — the second send must not re-apply anything
      if (applied++ > 0) return { outcome: 'no-intent' }
      return { outcome: 'ready', sequence: 4,
        application: { operationId: 'op-1', nativeTarget: { owner: 'connection:native',
          canonicalUid: 'canonical', generation: 1 }, appliedRevision: 'applied-1', evidenceRef: 'ev-1' } }
    }
    return { outcome: 'pending-next-turn', sequence: 4, intentRoute: 'independent' }
  })
}
const methodsOf = (invoke: ReturnType<typeof vi.fn>) => invoke.mock.calls.map(([method]) => method)

async function mount(wiring: SelectorWiring, pane: object = location) {
  const container = document.createElement('div'); document.body.append(container)
  const root = createRoot(container); roots.push(root)
  await act(async () => root.render(<ChatModelSelector wiring={wiring} location={pane as never} />))
  return { container, root, render: async (next: object) => act(async () => root.render(
    <ChatModelSelector wiring={wiring} location={next as never} />)) }
}
const openMenu = async (container: HTMLElement) =>
  act(async () => { container.querySelector<HTMLElement>('[data-testid="model-selector-trigger"]')!.click() })
const pickFirst = async () => act(async () => { document.body.querySelector<HTMLElement>('[role="option"]')!.click() })

it.each(['running', 'starting', 'stop-requested'])(
  'N2.2a picking a model while the turn is %s only inspects and queues — no cancel, no interrupt, no second prompt',
  async status => {
    const ui = facade({ id: 'run-1', status })
    const invoke = invokeOf()
    const wiring: SelectorWiring = { service: { list: async () => [config] } as never, invoke,
      sessions: ui.sessions as never }
    const { container } = await mount(wiring)
    await openMenu(container)
    await pickFirst()
    await act(async () => undefined)

    // every wire method the whole interaction emitted is inside the allowlist
    expect(new Set(methodsOf(invoke))).toEqual(new Set(SELECTION_ALLOWLIST))
    expect(methodsOf(invoke).filter(method => INTERRUPTIVE.test(method))).toEqual([])
    // the run was never cancelled, interrupted or stopped
    expect(ui.sessions.stop).not.toHaveBeenCalled()
    expect(ui.stopped).toEqual([])
    // and the pick is a QUEUED intent for the next turn, not an applied change
    expect(container.querySelector('[data-testid="model-selector-trigger"]')!.textContent).toContain('下轮使用')
    expect(invoke.mock.calls.some(([method]) => method === 'modelProvider.beginTurnApplication')).toBe(false)
  })

it('N2.2b the pick made during the running turn applies only on the next explicit send, exactly once', async () => {
  const ui = facade({ id: 'run-1', status: 'running' })
  const invoke = invokeOf()
  const wiring: SelectorWiring = { service: { list: async () => [config] } as never, invoke,
    sessions: ui.sessions as never }
  const chat = createChatContributions(), scope = new OwnedResources()
  registerModelSelector(chat, scope, wiring)
  const { container } = await mount(wiring)
  await openMenu(container)
  await pickFirst()
  await act(async () => undefined)
  // nothing was applied while the turn ran
  expect(invoke.mock.calls.some(([method]) => method === 'modelProvider.beginTurnApplication')).toBe(false)

  const snapshot: ChatSubmissionSnapshot = { submissionId: 'sub-1', draftId: 'd-1', draftRevision: 1,
    text: 'hello', attachmentIds: [],
    target: { kind: 'session', connectionId: 'conn', serverInstanceId: 'srv', sessionId: 'native',
      harnessId: 'pi', contextRevision: 0 } }
  const gateway = { submit: vi.fn().mockResolvedValue({ status: 'accepted' }) }
  const submits = () => invoke.mock.calls.filter(([method]) => method === 'modelProvider.beginTurnApplication')
  // the first explicit send applies the queued intent (frozen at sequence 4)
  expect(await chat.submit(snapshot, gateway, () => true)).toEqual({ status: 'accepted' })
  expect(submits()).toHaveLength(1)
  expect(submits()[0][1]).toMatchObject({ expectedSequence: 4 })
  expect(gateway.submit).toHaveBeenCalledTimes(1)
  // a following send has nothing left to apply — the Server answers no-intent
  // and the client never re-applies the consumed one
  expect(await chat.submit({ ...snapshot, submissionId: 'sub-2' }, gateway, () => true))
    .toEqual({ status: 'accepted' })
  expect(submits()).toHaveLength(2)
  expect(gateway.submit).toHaveBeenCalledTimes(2) // two explicit sends, two prompts
  scope.dispose()
})

it('N2.2c typing during a running turn issues no query, reconcile, apply or submit', async () => {
  const ui = facade({ id: 'run-1', status: 'running' })
  const invoke = invokeOf()
  const wiring: SelectorWiring = { service: { list: async () => [config] } as never, invoke,
    sessions: ui.sessions as never }
  const { container, render } = await mount(wiring)
  await openMenu(container)
  await pickFirst()
  await act(async () => undefined)
  const before = invoke.mock.calls.length

  for (let revision = 1; revision <= 6; revision += 1) {
    // Chat re-projects the composer location on every keystroke with a FRESH
    // object identity — that is not a turn or application event.
    await render({ ...location, contextRevision: revision })
    ui.emit()
  }
  await act(async () => undefined)

  expect(invoke.mock.calls).toHaveLength(before)
  expect(invoke.mock.calls.some(([method]) => INTERRUPTIVE.test(method))).toBe(false)
  expect(container.querySelector('[data-testid="model-selector-trigger"]')!.textContent).toContain('下轮使用')
  expect(container.querySelector('[data-testid="model-queue-error"]')).toBeNull()
  expect(ui.sessions.stop).not.toHaveBeenCalled()
})

it('N2.2d a real turn completion still performs the required observation after a running-time pick', async () => {
  const ui = facade({ id: 'run-1', status: 'running' })
  const invoke = invokeOf()
  const wiring: SelectorWiring = { service: { list: async () => [config] } as never, invoke,
    sessions: ui.sessions as never }
  const { container } = await mount(wiring)
  await openMenu(container)
  await pickFirst()
  await act(async () => undefined)
  const before = invoke.mock.calls.filter(([method]) => method === 'modelProvider.queryChoice').length

  // the turn ending is an observation event, unlike typing
  await act(async () => { ui.setRunStatus('completed'); ui.emit() })
  await act(async () => undefined)
  expect(invoke.mock.calls.filter(([method]) => method === 'modelProvider.queryChoice').length)
    .toBeGreaterThan(before)
  expect(invoke.mock.calls.some(([method]) => INTERRUPTIVE.test(method))).toBe(false)
  expect(ui.sessions.stop).not.toHaveBeenCalled()
})
