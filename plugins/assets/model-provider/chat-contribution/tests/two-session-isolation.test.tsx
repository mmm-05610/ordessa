// @vitest-environment jsdom
// N2.3 — two sessions alternating their picks, and answers that arrive late.
//
// Counterexample under test: switching panes and re-picking must never let one
// session's selection, queue or late answer land on the other. Every assertion
// names the exact native target (`acpSessionId`) the wire call carried, so a
// crossed identity is a failure, not a plausible-looking pass.
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

const config = { id: 'p', version: 7, displayName: 'Fixture', harness: 'pi', archivedAt: null,
  models: [{ modelId: 'm', availability: 'available' }, { modelId: 'n', availability: 'available' }] }
const verdict = { verdict: 'supported', reason: 'fixture evidence', providerConfigId: 'p', configVersion: 7 }
const emptyObservation = { desired: null, lastConfirmed: null, revision: null, intentRoute: null }
const paneOf = (sessionId: string) => ({ kind: 'session' as const, connectionId: 'conn',
  serverInstanceId: 'srv', sessionId, harnessId: 'pi', contextRevision: 0 })
const nativeOf = (sessionId: string) => ({ sessionId, serverInstanceId: 'srv', harnessId: 'pi',
  nativeSessionId: sessionId, connectionId: 'channel', workspaceId: '/fixture' })
const targetOf = (invoke: ReturnType<typeof vi.fn>) => invoke.mock.calls
  .map(([, params]) => (params as { target?: { acpSessionId?: string } })?.target?.acpSessionId)

/** A facade that genuinely switches the selected native session. */
function facade() {
  const listeners = new Set<() => void>()
  const idle: AgentWorkspaceSnapshot = { available: [], selectedConnectionId: 'conn',
    selectionRevision: 1, runtimeGeneration: 1,
    agent: { selectedSessionId: 'a', connection: { status: 'connected' } } }
  let current = idle
  const sessions = {
    getSnapshot: () => current,
    subscribe: (fn: () => void) => { listeners.add(fn); return () => listeners.delete(fn) },
    prepareSubmission: vi.fn(async () => nativeOf(current.agent!.selectedSessionId!)),
  }
  return { sessions,
    async select(sessionId: string) { await act(async () => {
      current = { ...current, selectionRevision: (current.selectionRevision ?? 0) + 1,
        agent: { ...current.agent, selectedSessionId: sessionId } }
      for (const fn of [...listeners]) fn()
    }) } }
}

/** A per-session model queue: the answer always describes the target it names. */
function modelServer() {
  const queued = new Map<string, { modelId: string; sequence: number }>()
  const applied: string[] = []
  const hold = new Map<string, Promise<void>>()
  let releaseHold: (() => void) | undefined
  const invoke = vi.fn(async (method: string, params?: { target?: { acpSessionId?: string };
                                                        choice?: { modelId: string } }) => {
    const acpSessionId = params?.target?.acpSessionId ?? ''
    if (method === 'modelProvider.inspectChoice') return verdict
    if (method === 'modelProvider.queryChoice') {
      const entry = queued.get(acpSessionId)
      return entry ? { desired: { providerConfigId: 'p', modelId: entry.modelId }, lastConfirmed: null,
        revision: entry.sequence, intentRoute: 'independent' } : emptyObservation
    }
    if (method === 'modelProvider.chooseForSession') {
      const gate = hold.get(acpSessionId)
      if (gate) await gate
      queued.set(acpSessionId, { modelId: params!.choice!.modelId, sequence: 3 })
      return { outcome: 'pending-next-turn', sequence: 3, intentRoute: 'independent' }
    }
    if (method === 'modelProvider.beginTurnApplication') {
      const entry = queued.get(acpSessionId)
      if (!entry) return { outcome: 'no-intent' }
      queued.delete(acpSessionId); applied.push(acpSessionId)
      return { outcome: 'ready', sequence: entry.sequence,
        application: { operationId: `op-${acpSessionId}`, nativeTarget: { owner: `connection:${acpSessionId}`,
          canonicalUid: `uid-${acpSessionId}`, generation: 1 }, appliedRevision: 'applied-1', evidenceRef: `ev-${acpSessionId}` } }
    }
    return { outcome: 'unknown', reason: 'NOT_SCRIPTED' }
  })
  return { invoke, queued, applied,
    defer(sessionId: string) { hold.set(sessionId, new Promise<void>(resolve => { releaseHold = resolve })) },
    release() { hold.delete('b'); releaseHold?.() } }
}

async function mount(wiring: SelectorWiring, sessionId: string) {
  const container = document.createElement('div'); document.body.append(container)
  const root = createRoot(container); roots.push(root)
  await act(async () => root.render(<ChatModelSelector wiring={wiring} location={paneOf(sessionId) as never} />))
  await act(async () => container.querySelector<HTMLElement>('[data-testid="model-selector-trigger"]')!.click())
  return container
}
const pick = async (modelId: string) => act(async () => {
  document.body.querySelector<HTMLElement>(`[data-testid="model-option-p-${modelId}"]`)!.click()
})
const reopen = async (container: HTMLElement) => act(async () => {
  container.querySelector<HTMLElement>('[data-testid="model-selector-trigger"]')!.click()
})
const label = (container: HTMLElement) => container.querySelector('[data-testid="model-selector-trigger"]')!.textContent!

it('N2.3a alternating picks in two sessions reach their own native target and each shows only its own choice', async () => {
  const ui = facade(), server = modelServer()
  const wiring: SelectorWiring = { service: { list: async () => [config] } as never,
    invoke: server.invoke, sessions: ui.sessions as never }

  const paneA = await mount(wiring, 'a')
  await pick('m')
  expect(label(paneA)).toContain('Fixture › m')

  await ui.select('b')
  const paneB = await mount(wiring, 'b')
  await pick('n')
  expect(label(paneB)).toContain('Fixture › n')

  // back to A: its own choice is still its own
  await ui.select('a')
  const paneA2 = await mount(wiring, 'a')
  expect(label(paneA2)).toContain('Fixture › m')
  expect(label(paneA2)).not.toContain('Fixture › n')
  expect(label(paneA2)).toContain('下轮使用')
  expect(paneA2.querySelector('[data-testid="model-queue-error"]')).toBeNull()

  // every registration named its own session, and each session held exactly one
  expect(server.invoke.mock.calls.filter(([method]) => method === 'modelProvider.chooseForSession')
    .map(([, params]) => (params as { target: { acpSessionId: string } }).target.acpSessionId))
    .toEqual(['a', 'b'])
  expect([...server.queued.keys()].sort()).toEqual(['a', 'b'])
  expect(server.queued.get('a')).toEqual({ modelId: 'm', sequence: 3 })
  expect(server.queued.get('b')).toEqual({ modelId: 'n', sequence: 3 })
})

it('N2.3b an answer that arrives after the pane switch never lands on the session now shown', async () => {
  const ui = facade(), server = modelServer()
  const wiring: SelectorWiring = { service: { list: async () => [config] } as never,
    invoke: server.invoke, sessions: ui.sessions as never }

  const paneA = await mount(wiring, 'a')
  await pick('m')
  const before = server.invoke.mock.calls.length

  // B's registration is still in flight when the user leaves B for A
  await ui.select('b')
  const paneB = await mount(wiring, 'b')
  server.defer('b')
  await act(async () => { document.body.querySelector<HTMLElement>('[data-testid="model-option-p-n"]')!.click() })
  await ui.select('a')
  await act(async () => { server.release() })

  const paneA2 = await mount(wiring, 'a')
  // A is untouched by B's late answer: no error, its own choice, no apply
  expect(label(paneA2)).toContain('Fixture › m')
  expect(label(paneA2)).toContain('下轮使用')
  expect(paneA2.querySelector('[data-testid="model-queue-error"]')).toBeNull()
  expect(server.applied).toEqual([])
  expect(server.invoke.mock.calls.slice(before)
    .filter(([method]) => method === 'modelProvider.beginTurnApplication')).toEqual([])
  // each late answer landed on its OWN target: A keeps A's pick, B the late one
  expect(server.queued.get('a')).toEqual({ modelId: 'm', sequence: 3 })
  expect(server.queued.get('b')).toEqual({ modelId: 'n', sequence: 3 })
})

it('N2.3c a refused pick in one session neither clears nor errors the other session', async () => {
  const ui = facade()
  const invoke = vi.fn(async (method: string, params?: { target?: { acpSessionId?: string } }) => {
    const acpSessionId = params?.target?.acpSessionId ?? ''
    if (method === 'modelProvider.inspectChoice') return verdict
    if (method === 'modelProvider.queryChoice') return acpSessionId === 'a'
      ? { desired: { providerConfigId: 'p', modelId: 'm' }, lastConfirmed: null, revision: 3, intentRoute: 'independent' }
      : emptyObservation
    if (method === 'modelProvider.chooseForSession') {
      // a definitive refusal arrives as a typed wire rejection, not an answer
      if (acpSessionId === 'b')
        throw Object.assign(new Error('refused'), { outcome: 'Refused', details: { internalCode: 'TARGET_BUSY' } })
      return { outcome: 'pending-next-turn', sequence: 3, intentRoute: 'independent' }
    }
    return { outcome: 'no-intent' }
  })
  const wiring: SelectorWiring = { service: { list: async () => [config] } as never,
    invoke, sessions: ui.sessions as never }

  const paneA = await mount(wiring, 'a')
  await ui.select('b')
  const paneB = await mount(wiring, 'b')
  await pick('n')
  expect(paneB.querySelector('[data-testid="model-queue-error"]')!.textContent).toContain('TARGET_BUSY')
  // B shows an honest refusal and no phantom "next turn" choice
  expect(label(paneB)).not.toContain('下轮使用')

  await ui.select('a')
  const paneA2 = await mount(wiring, 'a')
  expect(label(paneA2)).toContain('Fixture › m')
  expect(label(paneA2)).toContain('下轮使用')
  expect(paneA2.querySelector('[data-testid="model-queue-error"]')).toBeNull()
  void paneA
})

it('N2.3d a send for one session applies only that session\'s intent; the other session\'s queue is untouched', async () => {
  const ui = facade(), server = modelServer()
  const wiring: SelectorWiring = { service: { list: async () => [config] } as never,
    invoke: server.invoke, sessions: ui.sessions as never }
  const chat = createChatContributions(), scope = new OwnedResources()
  registerModelSelector(chat, scope, wiring)

  await mount(wiring, 'a')
  await pick('m')
  await ui.select('b')
  await mount(wiring, 'b')
  await pick('n')
  expect([...server.queued.keys()].sort()).toEqual(['a', 'b'])

  const gateway = { submit: vi.fn().mockResolvedValue({ status: 'accepted' }) }
  const submitOf = (sessionId: string, submissionId: string): ChatSubmissionSnapshot =>
    ({ submissionId, draftId: 'd-1', draftRevision: 1, text: 'hello', attachmentIds: [],
      target: paneOf(sessionId) })

  expect(await chat.submit(submitOf('a', 'send-a'), gateway, () => true)).toEqual({ status: 'accepted' })
  expect(server.applied).toEqual(['a'])  // B's queued intent is exactly as it was — untouched by A's send
  expect(server.queued.get('b')).toEqual({ modelId: 'n', sequence: 3 })
  expect(server.invoke.mock.calls.filter(([method]) => method === 'modelProvider.beginTurnApplication')
    .every(([, params]) => (params as { target: { acpSessionId: string } }).target.acpSessionId === 'a')).toBe(true)

  expect(await chat.submit(submitOf('b', 'send-b'), gateway, () => true)).toEqual({ status: 'accepted' })
  expect(server.applied).toEqual(['a', 'b'])
  expect(gateway.submit).toHaveBeenCalledTimes(2)
  scope.dispose()
})
