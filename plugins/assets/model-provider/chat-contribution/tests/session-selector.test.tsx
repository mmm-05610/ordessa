// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, expect, it, vi } from 'vitest'
import { ChatModelSelector } from '../src/chat-api-entry'
import type { AgentWorkspaceSnapshot } from '@extensions/ordessa.agent-contracts/contract.js'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
const roots: ReturnType<typeof createRoot>[] = []
afterEach(async () => { for (const root of roots.splice(0)) await act(async () => root.unmount()); document.body.replaceChildren() })
const owner = { serverInstanceId: 'srv', harnessId: 'pi', nativeSessionId: 'native', sessionId: 'ui', connectionId: 'channel', workspaceId: '/fixture' }
const location = { kind: 'session' as const, connectionId: 'conn', serverInstanceId: 'srv', sessionId: 'ui', contextRevision: 0 }
const config = { id: 'p', version: 7, displayName: 'Fixture', harness: 'pi', archivedAt: null,
  models: [{ modelId: 'm', availability: 'available' }] }
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(r => { resolve = r }); return { resolve, promise } }
function fixture() {
  let snapshot: AgentWorkspaceSnapshot = { available: [], selectedConnectionId: 'conn', selectionRevision: 1, runtimeGeneration: 1,
    agent: { selectedSessionId: 'ui', connection: { status: 'connected' } } }
  const listeners = new Set<() => void>()
  const sessions = { getSnapshot: () => snapshot, subscribe: (fn: () => void) => { listeners.add(fn); return () => listeners.delete(fn) },
    prepareSubmission: vi.fn().mockResolvedValue(owner) }
  return { sessions,
    switchSession() { snapshot = { ...snapshot, selectionRevision: 2, agent: { ...snapshot.agent!, selectedSessionId: 'other' } }; listeners.forEach(fn => fn()) },
    publishRun(status: 'running' | 'completed') { snapshot = { ...snapshot, agent: { ...snapshot.agent!, runs: { R: { id: 'R', sessionId: 'ui', status } } } }; listeners.forEach(fn => fn()) },
  }
}
async function mount(invoke: ReturnType<typeof vi.fn>, facade = fixture(), pane: object = location, rows = [config]) {
  const container = document.createElement('div'); document.body.append(container)
  const root = createRoot(container); roots.push(root)
  await act(async () => root.render(<ChatModelSelector wiring={{ service: { list: async () => rows } as never,
    invoke, sessions: facade.sessions as never }} location={pane as never} />))
  await act(async () => container.querySelector<HTMLElement>('[data-testid="model-selector-trigger"]')!.click())
  return { container, facade }
}
const verdict = (value: string) => ({ verdict: value, reason: 'fixture evidence', providerConfigId: 'p', configVersion: 7 })
const emptyObservation = { desired: null, lastConfirmed: null, revision: null }

it('enables only inspected supported evidence and queues the native owner as a next-turn override', async () => {
  const invoke = vi.fn(async (method: string) => method === 'modelProvider.inspectChoice'
    ? verdict('supported') : method === 'modelProvider.queryChoice' ? emptyObservation : { outcome: 'pending-next-turn', sequence: 2, intentRoute: 'independent' })
  const { container } = await mount(invoke)
  const option = document.body.querySelector<HTMLElement>('[role="option"]')!
  expect(option.getAttribute('aria-disabled')).toBe('false')
  expect(invoke).toHaveBeenCalledWith('modelProvider.inspectChoice', {
    target: { serverInstanceId: 'srv', harnessId: 'pi', acpSessionId: 'native' }, choice: { providerConfigId: 'p', modelId: 'm' },
  })
  await act(async () => option.click())
  expect(invoke).toHaveBeenCalledWith('modelProvider.chooseForSession', expect.objectContaining({
    target: { serverInstanceId: 'srv', harnessId: 'pi', acpSessionId: 'native' }, choice: { providerConfigId: 'p', modelId: 'm' },
  }))
  expect(container.querySelector('[data-testid="model-selector-trigger"]')!.textContent).toContain('下轮使用')
})

it.each(['unsupported', 'unknown', 'bogus'])('keeps %s inspection disabled without a queue call', async value => {
  const invoke = vi.fn(async (method: string) => method === 'modelProvider.queryChoice' ? emptyObservation : verdict(value))
  const { container } = await mount(invoke)
  expect(document.body.querySelector('[role="option"]')?.getAttribute('aria-disabled')).toBe('true')
  await act(async () => document.body.querySelector<HTMLElement>('[role="option"]')!.click())
  expect(invoke.mock.calls.some(([method]) => method === 'modelProvider.chooseForSession')).toBe(false)
})

it('keeps inspection network failure explicit and disabled', async () => {
  const { container } = await mount(vi.fn().mockRejectedValue(new Error('network offline')))
  expect(document.body.querySelector('[role="option"]')?.getAttribute('aria-disabled')).toBe('true')
  expect(document.body.textContent).toContain('network offline')
})

it('keeps the production ADAPTER_MISSING verdict disabled rather than inventing support', async () => {
  const invoke = vi.fn(async (method: string) => method === 'modelProvider.queryChoice' ? emptyObservation
    : { ...verdict('unknown'), reason: 'ADAPTER_MISSING' })
  const { container } = await mount(invoke)
  expect(document.body.querySelector('[role="option"]')?.getAttribute('aria-disabled')).toBe('true')
  expect(document.body.textContent).toContain('ADAPTER_MISSING')
  await act(async () => document.body.querySelector<HTMLElement>('[role="option"]')!.click())
  expect(invoke.mock.calls.some(([method]) => method === 'modelProvider.chooseForSession')).toBe(false)
})

it('does not prepare or inspect a draft', async () => {
  const facade = fixture(), invoke = vi.fn()
  const { container } = await mount(invoke, facade, { kind: 'draft', draftId: 'draft', connectionId: 'conn', contextRevision: 0 })
  expect(facade.sessions.prepareSubmission).not.toHaveBeenCalled()
  expect(invoke).not.toHaveBeenCalled()
  expect(document.body.textContent).toContain('原生会话')
  const note = container.querySelector<HTMLElement>('[data-testid="model-owner-note"]')!
  expect(note.tagName).toBe('SPAN')
  expect(note.textContent).toBe('需先建会话')
  expect(note.title).toContain('草稿不会创建会话')
  expect(document.body.querySelector('[data-testid="model-owner-note-details"]')!.textContent).toContain('草稿不会创建会话')
})

it('does not invent identity when native owner is unavailable', async () => {
  const facade = fixture(), invoke = vi.fn()
  facade.sessions.prepareSubmission.mockRejectedValue(new Error('owner unavailable'))
  const { container } = await mount(invoke, facade)
  expect(invoke).not.toHaveBeenCalled()
  expect(document.body.textContent).toContain('owner unavailable')
  const note = container.querySelector<HTMLElement>('[data-testid="model-owner-note"]')!
  expect(note.textContent).toBe('身份待确认')
  expect(note.getAttribute('aria-label')).toContain('owner unavailable')
  expect(container.querySelector('p[data-testid="model-owner-note"]')).toBeNull()
})

it('does not display internal identity notes when the selected native session is ready', async () => {
  const invoke = vi.fn(async (method: string) => method === 'modelProvider.queryChoice' ? emptyObservation : verdict('supported'))
  const { container } = await mount(invoke)
  expect(container.querySelector('[data-testid="model-owner-note"]')).toBeNull()
  expect(document.body.querySelector('[data-testid="model-owner-note-details"]')).toBeNull()
})

it('discards late inspect evidence after a session switch', async () => {
  const answer = deferred<unknown>(), invoke = vi.fn((method: string) => method === 'modelProvider.queryChoice' ? Promise.resolve(emptyObservation) : answer.promise)
  const { container, facade } = await mount(invoke)
  await act(async () => facade.switchSession())
  await act(async () => answer.resolve(verdict('supported')))
  expect(document.body.querySelector('[role="option"]')?.getAttribute('aria-disabled')).not.toBe('false')
  expect(invoke.mock.calls.some(([method]) => method === 'modelProvider.chooseForSession')).toBe(false)
})

it('keeps loading inspection disabled', async () => {
  const answer = deferred<unknown>(), invoke = vi.fn((method: string) => method === 'modelProvider.queryChoice' ? Promise.resolve(emptyObservation) : answer.promise)
  const { container } = await mount(invoke)
  expect(document.body.querySelector('[role="option"]')?.getAttribute('aria-disabled')).toBe('true')
  expect(document.body.textContent).toContain('正在核实')
  await act(async () => document.body.querySelector<HTMLElement>('[role="option"]')!.click())
  expect(invoke.mock.calls.some(([method]) => method === 'modelProvider.chooseForSession')).toBe(false)
  await act(async () => answer.resolve(verdict('supported')))
})

it('discards a late queue acknowledgement after navigation', async () => {
  const answer = deferred<unknown>()
  const invoke = vi.fn((method: string) => method === 'modelProvider.inspectChoice' ? Promise.resolve(verdict('supported'))
    : method === 'modelProvider.queryChoice' ? Promise.resolve(emptyObservation) : answer.promise)
  const { container, facade } = await mount(invoke)
  await act(async () => document.body.querySelector<HTMLElement>('[role="option"]')!.click())
  expect(invoke.mock.calls.some(([method]) => method === 'modelProvider.chooseForSession')).toBe(true)
  await act(async () => facade.switchSession())
  await act(async () => answer.resolve({ outcome: 'pending-next-turn', sequence: 2, intentRoute: 'independent' }))
  expect(container.querySelector('[data-testid="model-selector-trigger"]')?.textContent).not.toContain('下轮使用')
})

it('retains the previous queued selection when a later queue fails', async () => {
  let queues = 0
  const invoke = vi.fn(async (method: string) => {
    if (method === 'modelProvider.inspectChoice') return verdict('supported')
    if (method === 'modelProvider.queryChoice') return queues === 0 ? emptyObservation
      : { desired: { providerConfigId: 'p', modelId: 'm' }, lastConfirmed: null, revision: 2 }
    if (++queues === 1) return { outcome: 'pending-next-turn', sequence: 2, intentRoute: 'independent' }
    throw new Error('network offline')
  })
  const { container } = await mount(invoke, fixture(), location, [{ ...config, models: [...config.models, { modelId: 'n', availability: 'available' }] }])
  await act(async () => document.body.querySelector<HTMLElement>('[data-testid="model-option-p-m"]')!.click())
  expect(container.querySelector('[data-testid="model-selector-trigger"]')!.textContent).toContain('Fixture › m')
  await act(async () => container.querySelector<HTMLElement>('[data-testid="model-selector-trigger"]')!.click())
  await act(async () => document.body.querySelector<HTMLElement>('[data-testid="model-option-p-n"]')!.click())
  expect(container.querySelector('[data-testid="model-selector-trigger"]')!.textContent).toContain('Fixture › m')
  expect(container.querySelector('[data-testid="model-queue-error"]')!.textContent).toContain('结果未知')
})

it('refuses an inspection for a changed provider config version', async () => {
  const invoke = vi.fn().mockResolvedValue({ ...verdict('supported'), configVersion: 8 })
  const { container } = await mount(invoke)
  expect(document.body.querySelector('[role="option"]')?.getAttribute('aria-disabled')).toBe('true')
  expect(document.body.textContent).toContain('版本不可核实')
})

it('reopening reads the pending state after a lost acknowledgement without retrying choose', async () => {
  let accepted = false
  const invoke = vi.fn(async (method: string) => {
    if (method === 'modelProvider.inspectChoice') return verdict('supported')
    if (method === 'modelProvider.queryChoice') return accepted
      ? { desired: { providerConfigId: 'p', modelId: 'm' }, lastConfirmed: null, revision: 2, intentRoute: 'profile-overlay' } : emptyObservation
    accepted = true; throw new Error('ack lost')
  })
  const { container } = await mount(invoke)
  await act(async () => document.body.querySelector<HTMLElement>('[role="option"]')!.click())
  expect(container.querySelector('[data-testid="model-queue-error"]')!.textContent).toContain('结果未知')
  await act(async () => container.querySelector<HTMLElement>('[data-testid="model-selector-trigger"]')!.click())
  expect(container.querySelector('[data-testid="model-selector-trigger"]')!.textContent).toContain('Fixture › m')
  expect(container.querySelector('[data-testid="model-selector-trigger"]')!.textContent).toContain('下轮使用')
  expect(invoke.mock.calls.filter(([method]) => method === 'modelProvider.chooseForSession')).toHaveLength(1)
})

it('refreshes once at turn end and displays native current state instead of a historical receipt', async () => {
  let stage: 'idle' | 'pending' | 'completed' = 'idle'
  const invoke = vi.fn(async (method: string) => {
    if (method === 'modelProvider.inspectChoice') return verdict('supported')
    if (method === 'modelProvider.chooseForSession') { stage = 'pending'; return { outcome: 'pending-next-turn', sequence: 2, intentRoute: 'independent' } }
    if (stage === 'idle') return emptyObservation
    return { desired: stage === 'pending' ? { providerConfigId: 'p', modelId: 'm' } : null,
      current: stage === 'completed' ? { provider: 'native-provider', modelId: 'profile-model' } : null,
      lastConfirmed: stage === 'completed' ? { harnessId: 'pi', providerConfigId: 'p', modelId: 'm',
        providerConfigVersion: 7, evidence: { applied: 'read-back-verified' } } : null, revision: 2 }
  })
  const { container, facade } = await mount(invoke)
  await act(async () => document.body.querySelector<HTMLElement>('[role="option"]')!.click())
  expect(container.querySelector('[data-testid="model-selector-trigger"]')!.textContent).toContain('下轮使用')
  const count = invoke.mock.calls.filter(([method]) => method === 'modelProvider.queryChoice').length
  await act(async () => facade.publishRun('running'))
  expect(invoke.mock.calls.filter(([method]) => method === 'modelProvider.queryChoice')).toHaveLength(count)
  stage = 'completed'
  await act(async () => facade.publishRun('completed'))
  expect(invoke.mock.calls.filter(([method]) => method === 'modelProvider.queryChoice')).toHaveLength(count + 1)
  expect(container.querySelector('[data-testid="model-selector-trigger"]')!.textContent).toContain('native-provider › profile-model')
  expect(container.querySelector('[data-testid="model-selector-trigger"]')!.textContent).not.toContain('上次确认')
  expect(container.querySelector('[data-testid="model-selector-trigger"]')!.textContent).not.toContain('下轮使用')
})

it('shows the Profile-applied native model even when no model choice has ever been queued', async () => {
  const invoke = vi.fn(async (method: string) => method === 'modelProvider.inspectChoice' ? verdict('supported')
    : {...emptyObservation,current:{provider:'deepseek',modelId:'deepseek-flash'}})
  const {container} = await mount(invoke)
  expect(container.querySelector('[data-testid="model-selector-trigger"]')!.textContent).toContain('deepseek › deepseek-flash')
  expect(invoke.mock.calls.some(([method])=>method==='modelProvider.chooseForSession')).toBe(false)
})

it('does not reconcile an unsent model choice when typing reprojects the same bound location', async () => {
  let pending = false
  const invoke = vi.fn(async (method: string) => {
    if (method === 'modelProvider.inspectChoice') return verdict('supported')
    if (method === 'modelProvider.chooseForSession') {
      pending = true
      return { outcome: 'pending-next-turn', sequence: 2, intentRoute: 'profile-overlay' }
    }
    if (method === 'modelProvider.reconcileChoice') return { outcome: 'unknown', reason: 'NOT_SENT' }
    return { ...emptyObservation, desired: pending ? { providerConfigId: 'p', modelId: 'm' } : null,
      revision: pending ? 2 : null, intentRoute: pending ? 'profile-overlay' : null }
  })
  const facade = fixture()
  const wiring = { service: { list: async () => [config] } as never, invoke,
    sessions: facade.sessions as never, boundProbe: () => true }
  const container = document.createElement('div'); document.body.append(container)
  const root = createRoot(container); roots.push(root)
  await act(async () => root.render(<ChatModelSelector wiring={wiring} location={location} />))
  await act(async () => container.querySelector<HTMLElement>('[data-testid=model-selector-trigger]')!.click())
  await act(async () => document.body.querySelector<HTMLElement>('[role=option]')!.click())
  const reads = invoke.mock.calls.filter(([method]) => method === 'modelProvider.queryChoice').length
  for (let index = 0; index < 4; index++) {
    // Chat supplies a fresh projection object on each composer render.
    await act(async () => root.render(<ChatModelSelector wiring={wiring} location={{ ...location, contextRevision: index + 1 }} />))
  }
  expect(invoke.mock.calls.filter(([method]) => method === 'modelProvider.reconcileChoice')).toHaveLength(0)
  expect(invoke.mock.calls.filter(([method]) => method === 'modelProvider.queryChoice')).toHaveLength(reads)
  expect(container.querySelector('[data-testid=model-queue-error]')).toBeNull()
  expect(container.querySelector('[data-testid=model-selector-trigger]')!.textContent).toContain('下轮使用')
  // Real turn completion still triggers the required observation.
  await act(async () => facade.publishRun('running'))
  expect(invoke.mock.calls.filter(([method]) => method === 'modelProvider.reconcileChoice')).toHaveLength(0)
  await act(async () => facade.publishRun('completed'))
  expect(invoke.mock.calls.filter(([method]) => method === 'modelProvider.reconcileChoice')).toHaveLength(1)
})
