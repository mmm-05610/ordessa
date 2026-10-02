// @vitest-environment jsdom
// N2.4 — unknown / refused outcomes keep what the user had, and a read-back
// failure never lets a historical receipt stand in for a current fact.
//
// Covered here (model route):
// - an unknown answer keeps the queued choice; the warning is STABLE across
//   ordinary composer reprojections (no flicker) and triggers no apply/submit;
// - a definite refusal leaves no phantom "next turn" choice, and an explicit
//   re-pick (a new user operation) succeeds normally;
// - a real completed turn still performs the required observation, and that
//   observation resolves the warning WITHOUT discarding the user's choice;
// - a failed read-back drops the displayed model instead of keeping a stale or
//   historical value on screen as present fact.
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, expect, it, vi } from 'vitest'
import { ChatModelSelector, type SelectorWiring } from '../src/chat-api-entry'
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
const APPLY_METHODS = ['modelProvider.beginTurnApplication', 'modelProvider.reconcileChoice']

function facade() {
  const listeners = new Set<() => void>()
  const idle: AgentWorkspaceSnapshot = { available: [], selectedConnectionId: 'conn',
    selectionRevision: 1, runtimeGeneration: 1,
    agent: { selectedSessionId: 'native', connection: { status: 'connected' } } }
  let current = idle
  return { sessions: { getSnapshot: () => current,
      subscribe: (fn: () => void) => { listeners.add(fn); return () => listeners.delete(fn) },
      prepareSubmission: vi.fn().mockResolvedValue(native) },
    setRunStatus: (status: string) => { current = { ...current, agent: { ...current.agent,
      runs: { 'run-1': { id: 'run-1', sessionId: 'native', status } } } } },
    emit: () => { for (const fn of [...listeners]) fn() } }
}
const wireError = (kind: 'Unknown' | 'Refused', code: string) =>
  Object.assign(new Error(code), { outcome: kind, details: { internalCode: code } })

async function mount(wiring: SelectorWiring) {
  const container = document.createElement('div'); document.body.append(container)
  const root = createRoot(container); roots.push(root)
  await act(async () => root.render(<ChatModelSelector wiring={wiring} location={location as never} />))
  return { container,
    render: async (next: object) => act(async () => root.render(
      <ChatModelSelector wiring={wiring} location={next as never} />)) }
}
const openMenu = async (container: HTMLElement) =>
  act(async () => { container.querySelector<HTMLElement>('[data-testid="model-selector-trigger"]')!.click() })
const pick = async () => act(async () => { document.body.querySelector<HTMLElement>('[role="option"]')!.click() })
const triggerOf = (container: HTMLElement) =>
  container.querySelector('[data-testid="model-selector-trigger"]') as HTMLElement
const errorOf = (container: HTMLElement) =>
  container.querySelector('[data-testid="model-queue-error"]') as HTMLElement | null

it('N2.4a an unknown pick keeps the queued choice and its warning is stable across ordinary composer reprojections', async () => {
  const ui = facade()
  const invoke = vi.fn(async (method: string) => {
    if (method === 'modelProvider.inspectChoice') return verdict
    if (method === 'modelProvider.queryChoice') return emptyObservation
    if (method === 'modelProvider.chooseForSession') throw wireError('Unknown', 'CHANNEL_DROPPED')
    return { outcome: 'no-intent' }
  })
  const wiring: SelectorWiring = { service: { list: async () => [config] } as never, invoke,
    sessions: ui.sessions as never }
  const { container, render } = await mount(wiring)
  await openMenu(container)
  await pick()
  await act(async () => undefined)

  const warning = errorOf(container)!
  expect(warning.textContent).toContain('结果未知')
  expect(warning.textContent).toContain('CHANNEL_DROPPED')
  // an unknown answer is NOT a queued choice: the composer never claims a
  // "next turn" model it could not confirm
  expect(triggerOf(container).textContent).not.toContain('下轮使用')
  const afterPick = invoke.mock.calls.length

  for (let revision = 1; revision <= 5; revision += 1) {
    await render({ ...location, contextRevision: revision })
  }
  await act(async () => undefined)

  // same DOM node, same text: the warning does not flicker, and editing the
  // composer neither retries the pick nor applies or submits anything
  expect(errorOf(container)).toBe(warning)
  expect(errorOf(container)!.textContent).toBe(warning.textContent)
  expect(invoke.mock.calls).toHaveLength(afterPick)
  expect(invoke.mock.calls.some(([method]) => APPLY_METHODS.includes(method))).toBe(false)
  expect(triggerOf(container).textContent).not.toContain('下轮使用')

  // and the user can still pick again — an explicit retry is a new operation
  await openMenu(container)
  await pick()
  await act(async () => undefined)
  expect(errorOf(container)!.textContent).toContain('CHANNEL_DROPPED')
  expect(invoke.mock.calls.filter(([method]) => method === 'modelProvider.chooseForSession')).toHaveLength(2)
})

it('N2.4b a definite refusal leaves no phantom next-turn choice, and an explicit re-pick succeeds', async () => {
  let attempts = 0
  const invoke = vi.fn(async (method: string) => {
    if (method === 'modelProvider.inspectChoice') return verdict
    if (method === 'modelProvider.queryChoice') return emptyObservation
    if (method === 'modelProvider.chooseForSession') {
      if (attempts++ === 0) throw wireError('Refused', 'CATALOGUE_STALE')
      return { outcome: 'pending-next-turn', sequence: 5, intentRoute: 'independent' }
    }
    return { outcome: 'no-intent' }
  })
  const wiring: SelectorWiring = { service: { list: async () => [config] } as never, invoke,
    sessions: facade().sessions as never }
  const { container } = await mount(wiring)
  await openMenu(container)
  await pick()
  await act(async () => undefined)
  expect(errorOf(container)!.textContent).toContain('模型选择被拒绝')
  expect(errorOf(container)!.textContent).toContain('CATALOGUE_STALE')
  // a refused pick is NOT a queued next-turn choice
  expect(triggerOf(container).textContent).not.toContain('下轮使用')
  expect(invoke.mock.calls.some(([method]) => APPLY_METHODS.includes(method))).toBe(false)

  // an explicit re-pick (a new user operation, a new operation key) works
  await openMenu(container)
  await pick()
  await act(async () => undefined)
  expect(errorOf(container)).toBeNull()
  expect(triggerOf(container).textContent).toContain('Fixture › m')
  expect(triggerOf(container).textContent).toContain('下轮使用')
  expect(invoke.mock.calls.filter(([method]) => method === 'modelProvider.chooseForSession')).toHaveLength(2)
})

it('N2.4c a real completed turn still performs the required observation and resolves the warning without losing the pick', async () => {
  const ui = facade()
  let observationFails = true
  let desired: { providerConfigId: string; modelId: string } | null = null
  const invoke = vi.fn(async (method: string) => {
    if (method === 'modelProvider.inspectChoice') return verdict
    if (method === 'modelProvider.queryChoice') {
      if (observationFails) throw wireError('Unknown', 'READ_BACK_LOST')
      return { desired, lastConfirmed: null, revision: desired ? 5 : null, intentRoute: 'independent' }
    }
    if (method === 'modelProvider.chooseForSession') {
      desired = { providerConfigId: 'p', modelId: 'm' }
      return { outcome: 'pending-next-turn', sequence: 5, intentRoute: 'independent' }
    }
    return { outcome: 'no-intent' }
  })
  const wiring: SelectorWiring = { service: { list: async () => [config] } as never, invoke,
    sessions: ui.sessions as never }
  const { container } = await mount(wiring)
  await act(async () => undefined)
  expect(errorOf(container)!.textContent).toContain('READ_BACK_LOST')
  await openMenu(container)
  await pick()
  await act(async () => undefined)
  expect(triggerOf(container).textContent).toContain('下轮使用')

  // a genuine turn completion is an observation event even while the previous
  // observation failed — the required check must still run
  const before = invoke.mock.calls.filter(([method]) => method === 'modelProvider.queryChoice').length
  await act(async () => { ui.setRunStatus('running'); ui.emit() })
  await act(async () => { ui.setRunStatus('completed'); ui.emit() })
  await act(async () => undefined)
  expect(invoke.mock.calls.filter(([method]) => method === 'modelProvider.queryChoice').length)
    .toBeGreaterThan(before)

  // once the read-back succeeds the warning resolves, and the user's choice is
  // still the pending next-turn intent — nothing was discarded along the way
  observationFails = false
  await openMenu(container)
  await act(async () => undefined)
  expect(errorOf(container)).toBeNull()
  expect(triggerOf(container).textContent).toContain('Fixture › m')
  expect(triggerOf(container).textContent).toContain('下轮使用')
  expect(invoke.mock.calls.some(([method]) => APPLY_METHODS.includes(method))).toBe(false)
})

it('N2.4d a failed read-back never leaves a stale or historical model on screen as present fact', async () => {
  const ui = facade()
  let observationFails = false
  const invoke = vi.fn(async (method: string) => {
    if (method === 'modelProvider.inspectChoice') return verdict
    if (method === 'modelProvider.queryChoice') {
      if (observationFails) throw wireError('Unknown', 'READ_BACK_LOST')
      return { ...emptyObservation, current: { provider: 'native-provider', modelId: 'model-x' } }
    }
    return { outcome: 'no-intent' }
  })
  const wiring: SelectorWiring = { service: { list: async () => [config] } as never, invoke,
    sessions: ui.sessions as never }
  const { container } = await mount(wiring)
  await act(async () => undefined)
  await openMenu(container)
  expect(triggerOf(container).textContent).toContain('native-provider › model-x')

  // the read-back now fails: the previously observed model is NOT presented as
  // a current fact, and no receipt is invented in its place
  observationFails = true
  await act(async () => { ui.setRunStatus('running'); ui.emit() })
  await act(async () => { ui.setRunStatus('completed'); ui.emit() })
  await act(async () => undefined)
  expect(triggerOf(container).textContent).not.toContain('model-x')
  expect(triggerOf(container).textContent).not.toContain('上次确认')
  expect(errorOf(container)!.textContent).toContain('READ_BACK_LOST')
  expect(triggerOf(container).textContent).not.toContain('下轮使用')
})
