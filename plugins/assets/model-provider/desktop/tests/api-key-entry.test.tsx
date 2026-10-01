// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, expect, it, vi } from 'vitest'
import { OwnedResources } from '@ordessa/extension-api'
import type { Workbench, WirePort } from '@extensions/ordessa.contracts/contract.js'
import { ModelProviderWireError, type ProviderConfigView } from '../../contracts/index'
import { createModelProviderService } from '../src/service'
import createProductPlugin from '../src/entry'
import { ModelProviderSettings } from '../src/settings'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
const cleanups: (() => void | Promise<void>)[] = []
afterEach(async () => { for (const clean of cleanups.splice(0).reverse()) await clean(); vi.restoreAllMocks() })
const KEY = 'synthetic-key-sentinel'
const row: ProviderConfigView = { id: 'provider', version: 4, displayName: 'Existing', harness: 'pi', provider: 'acme',
  credentialId: 'old-reference', models: [{ modelId: 'old-model', availability: 'available' }],
  archivedAt: null, managedBy: 'ordessa', state: 'saved', provenance: { baseUrl: 'https://api.example.test/v1' }, createdAt: 'now', updatedAt: 'now' }
function deferred<T>() { let resolve!: (value: T) => void, reject!: (cause: unknown) => void
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no }); return { promise, resolve, reject } }
type Call = { method: string; params: Record<string, unknown> }
async function fixture(handler?: (method: string, params: Record<string, unknown>) => Promise<unknown>, rows = [row]) {
  const calls: Call[] = []
  const service = createModelProviderService(async (method, raw) => {
    const params = raw as Record<string, unknown>; calls.push({ method, params })
    if (method === 'providerModels.list') return { items: rows, nextCursor: null }
    if (method === 'providerModels.create' || method === 'providerModels.update') {
      // The production wire validator admits exactly these four model fields,
      // and requires displayName. Do not accept a looser fixture-only payload.
      const models = params.models as Record<string, unknown>[]
      if (!Array.isArray(models) || !models.length || models.some(model =>
        Object.keys(model).sort().join(',') !== 'availability,displayName,modelId,unavailableReason'
        || typeof model.displayName !== 'string' || !model.displayName))
        throw new ModelProviderWireError('Refused', method)
    }
    if (handler) return handler(method, params)
    if (method === 'modelProvider.importApiKey' || method === 'modelProvider.queryApiKeyImport')
      return { operationId: `key-import:${params.requestId}`, state: 'imported', credentialId: 'credential-imported', kind: 'api-key' }
    if (method === 'providerModels.create' || method === 'providerModels.update') return { providerModel: { ...row, version: 5 } }
    throw new ModelProviderWireError('Refused', method)
  })
  const container = document.createElement('div'); document.body.append(container)
  const root = createRoot(container); let live = true
  const unmount = async () => { if (!live) return; live = false; await act(async () => root.unmount()); container.remove() }
  cleanups.push(unmount)
  await act(async () => root.render(<ModelProviderSettings service={service} />))
  const click = async (id: string, twice = false) => { await act(async () => {
    const button = container.querySelector<HTMLButtonElement>(`[data-testid="${id}"]`)!
    expect(button, id).toBeTruthy(); button.click(); if (twice) button.click()
  }) }
  const field = (label: string) => container.querySelector<HTMLInputElement | HTMLSelectElement>(`[aria-label="${label}"]`)!
  const fill = async (label: string, value: string) => { await act(async () => {
    const input = field(label), prototype = input.tagName === 'SELECT' ? HTMLSelectElement.prototype : HTMLInputElement.prototype
    Object.getOwnPropertyDescriptor(prototype, 'value')!.set!.call(input, value)
    input.dispatchEvent(new Event(input.tagName === 'SELECT' ? 'change' : 'input', { bubbles: true }))
  }) }
  const add = async () => { await click('add-config'); await fill('名称', 'Draft'); await fill('供应商', 'acme')
    await fill('模型 ID', 'manual-one, manual-two'); await fill('Base URL', 'https://api.example.test/v1'); await fill('协议', 'openai-chat') }
  return { container, calls, click, fill, field, add, service, unmount }
}

it('imports only on click, clears password, and saves reference-only provider facts with nonempty manual models', async () => {
  const f = await fixture(); await f.add(); await f.fill('API Key', KEY)
  expect(f.field('API Key').type).toBe('password')
  expect(f.calls).toHaveLength(1)
  await f.click('import-api-key', true)
  expect(f.calls.filter(call => call.method === 'modelProvider.importApiKey')).toHaveLength(1)
  expect(f.field('API Key').value).toBe('')
  expect(f.field('凭据引用').value).toBe('credential-imported')
  expect(f.container.textContent).not.toContain(KEY)
  await f.click('save-config', true)
  const saves = f.calls.filter(call => call.method === 'providerModels.create')
  expect(saves).toHaveLength(1)
  expect(saves[0].params).toMatchObject({ requestId: expect.stringMatching(/^save_/), provider: 'acme', harness: 'pi',
    credentialId: 'credential-imported', protocols: ['openai-chat'], endpoints: { 'openai-chat': 'https://api.example.test/v1' },
    models: [{ modelId: 'manual-one', displayName: 'manual-one', availability: 'available', unavailableReason: null },
      { modelId: 'manual-two', displayName: 'manual-two', availability: 'available', unavailableReason: null }] })
  expect(JSON.stringify(saves[0])).not.toContain(KEY)
  expect(f.calls.filter(call => call.method.includes('probe'))).toHaveLength(0)
})

it('refuses a missing secure store without leaking exception text or dropping the provider draft', async () => {
  const f = await fixture(async method => { throw new ModelProviderWireError('Refused', `${method}:${KEY}`) })
  await f.add(); await f.fill('API Key', KEY); await f.click('import-api-key')
  expect(f.field('API Key').value).toBe('')
  expect(f.field('名称').value).toBe('Draft')
  expect(f.field('模型 ID').value).toBe('manual-one, manual-two')
  expect(f.field('凭据引用').value).toBe('')
  expect(f.container.textContent).toContain('密钥库')
  expect(f.container.textContent).not.toContain(KEY)
  expect(f.calls.filter(call => call.method.includes('create'))).toHaveLength(0)
})

it.each(['unprefixed', 'different-operation'])('rejects an imported credential whose operation identity is %s', async identity => {
  const f = await fixture(async (_method, params) => ({ operationId: identity === 'unprefixed'
    ? params.requestId : `key-import:other-${params.requestId}`, state: 'imported', credentialId: 'foreign', kind: 'api-key' }))
  await f.add(); await f.fill('API Key', KEY); await f.click('import-api-key')
  expect(f.field('凭据引用').value).toBe('')
  expect(f.container.querySelector('[data-testid="query-api-key-import"]')).toBeTruthy()
  expect(f.container.textContent).toContain('导入结果未知')
})

it('catalogue availability and a saved record do not prove same-session readiness', async () => {
  const f = await fixture(undefined, [{ ...row, models: [{ modelId: 'declared-model', availability: 'available', eligibility: 'ready' }] }])
  await f.click('config-provider')
  expect(f.container.textContent).toContain('已保存')
  expect(f.container.textContent).toContain('证据不足，未知')
  expect(f.container.textContent).not.toContain('可在此会话下轮使用')
  expect(f.calls.filter(call => call.method.includes('probe'))).toHaveLength(0)
})

it.each(['reply', 'transport'] as const)('unknown import retains its identity and uses explicit query only: %s', async mode => {
  let queryFails = true
  const f = await fixture(async (method, params) => {
    if (method === 'modelProvider.importApiKey') {
      if (mode === 'transport') throw new ModelProviderWireError('Unknown', `${method}:${KEY}`)
      return { operationId: `key-import:${params.requestId}`, state: 'unknown' }
    }
    if (queryFails) throw new ModelProviderWireError('Refused', method)
    return { operationId: `key-import:${params.requestId}`, state: 'imported', credentialId: 'credential-query', kind: 'api-key' }
  })
  await f.add(); await f.fill('API Key', KEY); await f.click('import-api-key')
  expect(f.field('API Key').value).toBe('')
  const imported = f.calls.find(call => call.method === 'modelProvider.importApiKey')!
  expect(f.container.textContent).toContain(String(imported.params.requestId))
  await f.click('import-api-key'); await f.click('save-config')
  expect(f.calls.filter(call => call.method === 'modelProvider.importApiKey')).toHaveLength(1)
  await f.click('query-api-key-import', true)
  expect(f.calls.filter(call => call.method === 'modelProvider.queryApiKeyImport')).toHaveLength(1)
  expect(f.container.querySelector('[data-testid="query-api-key-import"]')).toBeTruthy()
  queryFails = false; await f.click('query-api-key-import')
  expect(f.field('凭据引用').value).toBe('credential-query')
  for (const call of f.calls.filter(call => call.method === 'modelProvider.queryApiKeyImport')) {
    expect(call.params).toEqual({ requestId: imported.params.requestId, harnessId: 'pi' })
    expect(JSON.stringify(call)).not.toContain(KEY)
  }
  expect(f.container.textContent).not.toContain(KEY)
})

it.each(['generation', 'harness', 'cancel'] as const)('late import never attaches after %s changes', async change => {
  const gate = deferred<unknown>()
  const f = await fixture(async () => gate.promise)
  await f.add(); await f.fill('API Key', KEY); await f.click('import-api-key')
  const call = f.calls.find(call => call.method === 'modelProvider.importApiKey')!
  if (change === 'cancel') { await f.click('cancel-config'); await f.add() }
  else await f.fill(change === 'harness' ? 'Harness' : '名称', change === 'harness' ? 'codex' : 'Changed')
  await act(async () => { gate.resolve({ operationId: `key-import:${call.params.requestId}`, state: 'imported', credentialId: 'old-late-reference', kind: 'api-key' }) })
  expect(f.field('凭据引用').value).toBe('')
  expect(f.field('API Key').value).toBe('')
  expect(f.calls.filter(item => item.method === 'modelProvider.importApiKey')).toHaveLength(1)
})

it('unmount clears a detached password input and ignores an in-flight import result', async () => {
  const gate = deferred<unknown>(), f = await fixture(async () => gate.promise)
  await f.add(); await f.fill('API Key', KEY)
  const input = f.field('API Key')
  await f.unmount(); expect(input.value).toBe('')
  const g = await fixture(async () => gate.promise); await g.add(); await g.fill('API Key', KEY); await g.click('import-api-key')
  const call = g.calls.find(item => item.method === 'modelProvider.importApiKey')!
  await g.unmount()
  await act(async () => gate.resolve({ operationId: `key-import:${call.params.requestId}`, state: 'imported', credentialId: 'late', kind: 'api-key' }))
  expect(g.calls).toHaveLength(2)
})

it.each([{ state: 'imported', credentialId: 'x' }, { state: 'imported', credentialId: 'x', kind: 'api-key', extra: KEY },
  { state: 'unknown', credentialId: 'x' }, { state: 'imported', credentialId: 'x', kind: 'api-key', operationId: 'wrong' }])(
  'malformed import blocks binding and preserves query recovery: %j', async over => {
    const f = await fixture(async (_method, params) => ({ operationId: `key-import:${params.requestId}`, ...over }))
    await f.add(); await f.fill('API Key', KEY); await f.click('import-api-key')
    expect(f.field('凭据引用').value).toBe('')
    expect(f.container.querySelector('[data-testid="query-api-key-import"]')).toBeTruthy()
    expect(f.container.textContent).not.toContain(KEY)
  })

it('requires explicit provider, nonempty models and protocol before creating and never probes implicitly', async () => {
  const f = await fixture(); await f.click('add-config'); await f.click('save-config')
  await f.fill('供应商', 'acme'); await f.click('save-config')
  await f.fill('模型 ID', 'm1'); await f.click('save-config')
  expect(f.calls).toHaveLength(1)
  await f.fill('协议', 'openai-chat'); await f.click('save-config')
  expect(f.calls).toHaveLength(1)
  await f.fill('Base URL', 'https://api.example.test/v1'); await f.click('save-config')
  expect(f.calls.filter(call => call.method === 'providerModels.create')).toHaveLength(1)
  expect(f.calls.filter(call => call.method.includes('probe'))).toHaveLength(0)
})

it('edits with CAS and no immutable create fields, preserving omitted protocol facts', async () => {
  const f = await fixture(); await f.click('config-provider'); await f.click('edit-config'); await f.fill('名称', 'Edited')
  expect(f.field('Harness').disabled).toBe(true); expect(f.field('供应商').disabled).toBe(true)
  await f.click('save-config')
  const update = f.calls.find(call => call.method === 'providerModels.update')!.params
  expect(update).toMatchObject({ providerModelId: 'provider', expectedVersion: 4, displayName: 'Edited', requestId: expect.stringMatching(/^save_/) })
  expect(update).not.toHaveProperty('harness'); expect(update).not.toHaveProperty('provider')
  expect(update).not.toHaveProperty('protocols'); expect(update).not.toHaveProperty('endpoints')
})

it('editing an unrelated field omits already-declared protocols/endpoints and uses the actual endpoint over provenance', async () => {
  const configured = { ...row, protocols: ['openai-chat'], endpoints: { 'openai-chat': 'https://actual.example.test/v1' } }
  const f = await fixture(undefined, [configured]); await f.click('config-provider'); await f.click('edit-config')
  expect(f.field('Base URL').value).toBe('https://actual.example.test/v1')
  await f.fill('名称', 'Preserve protocol'); await f.click('save-config')
  const update = f.calls.find(call => call.method === 'providerModels.update')!.params
  expect(update).not.toHaveProperty('protocols'); expect(update).not.toHaveProperty('endpoints')
})

it('an explicit edited protocol and endpoint reach the save wire as separate capability fields', async () => {
  const f = await fixture(); await f.click('config-provider'); await f.click('edit-config')
  await f.fill('协议', 'openai-responses'); await f.fill('Base URL', 'https://edited.example.test/v1'); await f.click('save-config')
  const update = f.calls.find(call => call.method === 'providerModels.update')!.params
  expect(update).toMatchObject({ protocols: ['openai-responses'], endpoints: { 'openai-responses': 'https://edited.example.test/v1' },
    providerModelId: 'provider', expectedVersion: 4 })
  expect(update).not.toHaveProperty('provider'); expect(update).not.toHaveProperty('harness')
})

it('the production-shaped model mock rejects a model missing the required displayName', async () => {
  const f = await fixture()
  await expect(f.service.save({ requestId: 'production-shape-request', displayName: 'Malformed', harness: 'pi', provider: 'acme',
    credentialId: null, configuration: [], models: [{ modelId: 'm', availability: 'available', unavailableReason: null }] }))
    .rejects.toBeInstanceOf(ModelProviderWireError)
})

it('keeps the same explicit-save identity for a refused unchanged draft retry', async () => {
  let count = 0
  const f = await fixture(async method => { if (++count === 1) throw new ModelProviderWireError('Refused', method)
    return { providerModel: row } })
  await f.add(); await f.click('save-config'); expect(f.field('名称').value).toBe('Draft'); await f.click('save-config')
  const saves = f.calls.filter(call => call.method === 'providerModels.create')
  expect(saves).toHaveLength(2); expect(saves[0].params).toEqual(saves[1].params)
})

it('unknown save retains its frozen identity and never issues another save after edits or a new draft', async () => {
  const f = await fixture(async method => { throw new ModelProviderWireError('Unknown', `${method}:${KEY}`) })
  await f.add(); await f.click('save-config', true); await f.fill('名称', 'Edited'); await f.click('save-config')
  await f.click('cancel-config'); await f.add(); await f.click('save-config')
  expect(f.calls.filter(call => call.method === 'providerModels.create')).toHaveLength(1)
  expect(f.container.textContent).toContain('保存结果未知'); expect(f.container.textContent).not.toContain(KEY)
})

it('a pending save joins same-event double clicks and cannot replace a newly opened draft on completion', async () => {
  const gate = deferred<unknown>(), f = await fixture(async () => gate.promise)
  await f.add(); await f.click('save-config', true); await f.click('cancel-config'); await f.add(); await f.fill('名称', 'New draft')
  await act(async () => gate.resolve({ providerModel: row }))
  expect(f.field('名称').value).toBe('New draft')
  expect(f.calls.filter(call => call.method === 'providerModels.create')).toHaveLength(1)
})

it.each(['Unknown', 'Refused'] as const)('the product adapter preserves %s classification without backend reason text', async outcome => {
  const resources = new OwnedResources(); cleanups.push(() => resources.dispose())
  const wire = { call: async () => ({ kind: outcome, reason: KEY }) } as unknown as WirePort
  const workbench = { composition: { forScope: () => ({ addSettingsSection: () => ({ isDisposed: false, dispose() {} }) }) } } as unknown as Workbench
  const service = createProductPlugin().activate({ resources, root: { mount: () => ({ isDisposed: false, dispose() {} }) } }, workbench, wire)
  const error = await service.importApiKey('request-1', 'pi', KEY).catch(error => error)
  expect(error).toBeInstanceOf(ModelProviderWireError); expect(error.outcome).toBe(outcome); expect(error.message).not.toContain(KEY)
})
