import { afterEach, describe, expect, it, vi } from 'vitest'
import { OwnedResources } from '@ordessa/extension-api'
import type { f5 } from '@extensions/ordessa.contracts/contract.js'
import { createInteractionService as createWorkbenchInteractionService, type InteractionPresenter } from '@ordessa/workbench/interactions'
import { ModelProviderWireError, type WireInvoke } from '../../contracts/index'
import { createModelProviderService } from '../src/service'
import { createInteractionService } from '../src/task-integration'

interface Presented {
  readonly kind: 'notification' | 'progress'
  readonly view: Parameters<InteractionPresenter['show']>[1]
}

function setup(invoke: WireInvoke) {
  const resources = new OwnedResources()
  let scopeGeneration = 1
  const presented = new Map<string, Presented>()
  const show = vi.fn((kind: Presented['kind'], view: Presented['view']) => {
    presented.set(view.id, { kind, view })
  })
  const dismiss = vi.fn((id: string) => { presented.delete(id) })
  const presenter: InteractionPresenter = { show, dismiss }
  const interaction: f5.InteractionService = createWorkbenchInteractionService({
    presenter,
    scopeGeneration: () => scopeGeneration,
  })
  const domain = createModelProviderService(invoke)
  const wrapped = createInteractionService(domain, resources, interaction)
  return {
    resources, wrapped, domain, presented, show, dismiss,
    revokePresenter() { scopeGeneration += 1 },
  }
}

afterEach(() => { vi.restoreAllMocks() })

describe('Model Provider F5 task/interaction adapter', () => {
  it('returns domain results and invokes the production wire service once', async () => {
    const rows = [{ id: 'provider-a', version: 1 }] as never[]
    const invoke = vi.fn<WireInvoke>(async method => {
      if (method === 'providerModels.list') return { items: rows, nextCursor: null }
      throw new Error(`unexpected method: ${method}`)
    })
    const { wrapped, resources } = setup(invoke)

    await expect(wrapped.list()).resolves.toEqual(rows)
    expect(invoke).toHaveBeenCalledTimes(1)
    expect(invoke).toHaveBeenCalledWith('providerModels.list', { includeArchived: false })
    resources.dispose()
  })

  it('preserves the original Unknown error and never retries the domain call', async () => {
    const unknown = new ModelProviderWireError('Unknown', 'providerModels.list')
    const invoke = vi.fn<WireInvoke>(async () => { throw unknown })
    const { wrapped, resources } = setup(invoke)

    await expect(wrapped.list()).rejects.toBe(unknown)
    expect(invoke).toHaveBeenCalledTimes(1)
    resources.dispose()
  })

  it('does not notify from a late result after its ResourceScope is disposed', async () => {
    let resolveList!: (value: unknown) => void
    const invoke = vi.fn<WireInvoke>(() => new Promise(resolve => { resolveList = resolve }))
    const { wrapped, resources, presented, dismiss } = setup(invoke)
    const pending = wrapped.list()

    expect([...presented.values()].some(item => item.kind === 'progress')).toBe(true)
    resources.dispose()
    resolveList({ items: [], nextCursor: null })
    await expect(pending).resolves.toEqual([])

    expect([...presented.values()].some(item => item.kind === 'notification')).toBe(false)
    expect(dismiss).toHaveBeenCalled()
  })

  it('does not let an older same-operation completion dismiss the newer progress handle', async () => {
    const resolveCalls: Array<(value: unknown) => void> = []
    const invoke = vi.fn<WireInvoke>(() => new Promise(resolve => { resolveCalls.push(resolve) }))
    const { wrapped, resources, presented } = setup(invoke)
    const older = wrapped.list()
    const newer = wrapped.list()
    const progressId = 'model-provider:list:progress'

    expect(resolveCalls).toHaveLength(2)
    expect(presented.get(progressId)?.kind).toBe('progress')
    resolveCalls[0]({ items: [{ id: 'old', version: 1 }], nextCursor: null })
    await expect(older).resolves.toEqual([{ id: 'old', version: 1 }])
    await new Promise(resolve => setTimeout(resolve, 0))

    // Completing the replaced handle must not dismiss the newer same-ID row.
    expect(presented.get(progressId)?.kind).toBe('progress')
    resolveCalls[1]({ items: [{ id: 'new', version: 1 }], nextCursor: null })
    await expect(newer).resolves.toEqual([{ id: 'new', version: 1 }])
    await new Promise(resolve => setTimeout(resolve, 0))
    expect(presented.has(progressId)).toBe(false)
    resources.dispose()
  })

  it('keeps API key bytes out of every presented notification and progress view', async () => {
    const apiKey = 'test-secret-value-should-never-be-presented'
    const invoke = vi.fn<WireInvoke>(async method => {
      if (method === 'modelProvider.importApiKey') {
        return { operationId: 'key-import:req-1', state: 'imported', credentialId: 'cred-1', kind: 'api-key' }
      }
      throw new Error(`unexpected method: ${method}`)
    })
    const { wrapped, resources, presented, show } = setup(invoke)

    await expect(wrapped.importApiKey('req-1', 'harness-a', apiKey)).resolves.toMatchObject({ state: 'imported' })
    expect(invoke).toHaveBeenCalledWith('modelProvider.importApiKey', {
      requestId: 'req-1', harnessId: 'harness-a', apiKey,
    })
    expect(JSON.stringify([...presented.values()])).not.toContain(apiKey)
    expect(JSON.stringify(show.mock.calls)).not.toContain(apiKey)
    resources.dispose()
  })

  it('updates a stable notification identity instead of adding a new row', async () => {
    const invoke = vi.fn<WireInvoke>(async () => { throw new Error('safe test failure') })
    const { wrapped, resources, presented, show } = setup(invoke)

    await expect(wrapped.list()).rejects.toThrow('safe test failure')
    await expect(wrapped.list()).rejects.toThrow('safe test failure')
    await new Promise(resolve => setTimeout(resolve, 0))

    const notices = [...presented.entries()].filter(([, item]) => item.kind === 'notification')
    expect(notices).toHaveLength(1)
    expect(notices[0][0]).toBe('model-provider:list:outcome')
    expect(show.mock.calls.filter(([, view]) => view.id === notices[0][0])).toHaveLength(2)
    resources.dispose()
  })
})
