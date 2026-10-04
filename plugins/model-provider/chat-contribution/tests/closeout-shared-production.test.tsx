// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, expect, it, vi } from 'vitest'
import { OwnedResources } from '@ordessa/extension-api'
import { createChatContributions, type ChatLocation } from '@extensions/ordessa.chat-api/contract.js'
import { ComponentOutlet } from '@ordessa/ui-components/react'
import { type WirePort } from '@extensions/ordessa.contracts/contract.js'
import { type AgentSessions } from '@extensions/ordessa.agent-contracts/contract.js'
import { type ModelProviderService, type ProviderConfigView } from '@extensions/ordessa.model-provider/contract.js'
import type { ProfileServiceClient } from '@extensions/ordessa.profile-api/contract.js'
import { createUiComponentsService } from '../../../../packages/frontend/ui-components/src/index'
import createModelPlugin, { COMPONENT_PROVIDER_ID, MODEL_SELECTOR_ID, ModelSelectorKey } from '../src/entry'
import createProfilePlugin, { ProfilePickerKey } from '../../../profile/integrations/chat/src/entry'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
const disposers: Array<() => void | Promise<void>> = []
afterEach(async () => { for (const dispose of disposers.splice(0).reverse()) await dispose() })

const initialLocation: ChatLocation = {
  kind: 'draft', draftId: 'draft-1', connectionId: 'connection-1', serverInstanceId: 'server-1',
  projectId: 'project-1', harnessId: 'harness-1', contextRevision: 4, runtimeGeneration: 9,
}
const choices = {
  M1: { harnessId: 'harness-1', providerConfigId: 'provider-1', modelId: 'model-1', configVersion: 7 },
  M2: { harnessId: 'harness-1', providerConfigId: 'provider-1', modelId: 'model-2', configVersion: 7 },
}
const profiles = {
  A: { profileId: 'profile-A', harnessId: 'harness-1', displayName: 'Profile A', archived: false },
  B: { profileId: 'profile-B', harnessId: 'harness-1', displayName: 'Profile B', archived: false },
}
const groups = [{ harnessId: 'harness-1', harnessTitle: 'Harness 1', profiles: Object.values(profiles) }]

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>(done => { resolve = done })
  return { promise, resolve }
}

it('shares the production Profile and Model controls projection, preserves omitted fields, and retires one scope independently', async () => {
  const profileScope = new OwnedResources()
  const modelScope = new OwnedResources()
  disposers.push(() => profileScope.dispose(), () => modelScope.dispose())
  const chat = createChatContributions()
  const ui = createUiComponentsService([
    { componentId: 'ordessa.profile.picker', major: 1, providerId: 'ordessa.profile-chat' },
    { componentId: ModelSelectorKey.id, major: 1, providerId: COMPONENT_PROVIDER_ID },
  ])
  disposers.push(() => ui.dispose())
  const records = new Map<string, { revision: number; resolved: Record<string, unknown> }>()
  const writes: Array<{ target: string; patch: Record<string, unknown>; revision: number }> = []
  const wireCalls: Array<{ method: string; params: Readonly<Record<string, unknown>> }> = []
  let runtimeGeneration = 9
  const lateOldResolve = deferred<Awaited<ReturnType<WirePort['call']>>>()
  const wire: WirePort = {
    ready: true, scope: 'origin:server-1',
    async call(method, params) {
      wireCalls.push({ method, params })
      if (method === 'modelProvider.inspectChoice') return { kind: 'Accepted', requestId: 'inspect', result: { verdict: 'supported' } }
      if (method === 'agent.session.resolve') {
        const location = params.location as ChatLocation
        if (location.runtimeGeneration === 8) return await lateOldResolve.promise as never
        const target = location.draftId === 'draft-2' ? 'canonical-draft-2' : 'canonical-draft-1'
        return { kind: 'Accepted', requestId: 'resolve', result: { target, generation: runtimeGeneration } }
      }
      const target = String(params.target)
      let record = records.get(target)
      if (!record) { record = { revision: 0, resolved: {} }; records.set(target, record) }
      if (method === 'agent.config.read') return { kind: 'Accepted', requestId: 'read', result: {
        ownerRef: `agent-config:${target}`, revision: record.revision, observedEvidence: 'unset',
        fields: Object.fromEntries(Object.keys(record.resolved).map(key => [key, 'known'])), resolved: { ...record.resolved },
      } }
      if (method === 'agent.config.submitOperation') {
        const patch = params.patch as Record<string, unknown>
        Object.assign(record.resolved, patch)
        record.revision += 1
        writes.push({ target, patch: { ...patch }, revision: record.revision })
        return { kind: 'Accepted', requestId: `write-${record.revision}`, result: {
          operationId: `operation-${record.revision}`, patchKinds: Object.keys(patch).map(() => 'present'), state: 'pending',
        } }
      }
      return { kind: 'Refused', requestId: 'unexpected', reason: `unexpected method ${method}`, retryable: false }
    },
  }
  const sessions = {
    getSnapshot: () => ({ available: [], selectedConnectionId: 'connection-1', runtimeGeneration,
      draft: { active: true, workspaceId: 'project-1', canSend: true } }),
    subscribe: () => () => undefined,
    selectConnection: async () => undefined, reconnect: async () => undefined, refreshSessions: async () => undefined,
    newSession: async () => undefined, openSession: async () => undefined, send: async () => ({ status: 'accepted' }),
    prepareSubmission: vi.fn(async () => { throw new Error('Configuration selection must not create a session') }),
    stop: async () => undefined, respond: async () => undefined, setOption: async () => undefined,
    commandCatalog: () => ({ kind: 'absent' }),
  } as unknown as AgentSessions
  const provider: ProviderConfigView = {
    id: 'provider-1', version: 7, displayName: 'Provider', harness: 'harness-1', provider: 'fixture',
    credentialId: null,
    models: [
      { modelId: 'model-1', displayName: 'Model 1', availability: 'available', unavailableReason: null },
      { modelId: 'model-2', displayName: 'Model 2', availability: 'available', unavailableReason: null },
    ], archivedAt: null, managedBy: 'harness', state: 'saved', provenance: null, createdAt: 'now', updatedAt: 'now',
  }
  const modelService = {
    wire: {} as never, probeCalls: 0, list: vi.fn(async () => [provider]),
    testConnection: async () => ({ status: 'unreachable' }), fetchModels: async () => ({ status: 'ok', models: [] }),
    save: async () => { throw new Error('not used') },
  } as unknown as ModelProviderService
  const profileService = {
    profileCatalog: vi.fn(async () => groups),
    resolvePreview: vi.fn(async (profileId: string) => ({
      profileId, harnessId: 'harness-1', revision: profileId === 'profile-A' ? 3 : 4,
      digest: `digest:${profileId}`, unavailable: [], conflicts: [],
      items: profileId === 'profile-A' ? [
        { facetId: 'general', itemId: 'prompt', value: 'A prompt', state: 'explicit', source: { kind: 'profile', revision: 3 } },
        { facetId: 'assets.model-provider', itemId: 'choice', value: choices.M1, state: 'explicit', source: { kind: 'profile', revision: 3 } },
      ] : [{ facetId: 'general', itemId: 'prompt', value: 'B prompt', state: 'explicit', source: { kind: 'profile', revision: 4 } }],
    })),
  } as unknown as ProfileServiceClient
  const profileCatalog = profileService.profileCatalog as ReturnType<typeof vi.fn>

  const profilePlugin = createProfilePlugin()
  const profileActivate = profilePlugin.activate as (...args: unknown[]) => unknown
  profileActivate({ resources: profileScope, root: { mount: () => { throw new Error('not used') } } },
    profileService, chat, ui.uiComponents, wire, sessions)
  const modelPlugin = createModelPlugin()
  const modelActivate = modelPlugin.activate as (...args: unknown[]) => unknown
  modelActivate({ resources: modelScope, root: { mount: () => { throw new Error('not used') } } },
    chat, ui.uiComponents, wire, modelService, sessions)

  const views = chat.contributionsBySlot('composer.toolbar').getSnapshot()
  const profileView = views.find(view => view.key === ProfilePickerKey)!
  const modelView = views.find(view => view.id === MODEL_SELECTOR_ID)!
  const profileConsumer = new OwnedResources()
  const modelConsumer = new OwnedResources()
  disposers.push(() => profileConsumer.dispose(), () => modelConsumer.dispose())
  const profileBinding = ui.uiComponents.forScope(profileConsumer).bind(profileView.key!, { required: true })
  const modelBinding = ui.uiComponents.forScope(modelConsumer).bind(modelView.key!, { required: true })
  const container = document.createElement('div')
  document.body.append(container)
  const root = createRoot(container)
  disposers.push(async () => { await act(async () => root.unmount()); container.remove() })
  const render = async (location: ChatLocation) => {
    const context = { slot: 'composer.toolbar', location, connection: { status: 'connected' } } as never
    const profile = profileView.project!(context)
    const model = modelView.project!(context)
    await act(async () => root.render(<>
      <ComponentOutlet binding={profileBinding} value={profile.props} missing={null} />
      <ComponentOutlet binding={modelBinding} value={model.props} missing={null} />
    </>))
    await vi.waitFor(() => expect(records.has(location.draftId === 'draft-2' ? 'canonical-draft-2' : 'canonical-draft-1')).toBe(true))
  }
  const selectProfile = async (name: 'A' | 'B') => {
    await act(async () => container.querySelector<HTMLElement>('[data-profile-trigger]')!
      .dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true })))
    const selector = `[data-profile-value="harness-1::profile-${name}"]`
    await vi.waitFor(() => expect(document.body.querySelector(selector),
      `Profile menu option missing. selector=${selector}; catalogCalls=${profileCatalog.mock.calls.length}; `
      + `body=${document.body.innerHTML}; wire=${JSON.stringify(wireCalls)}`).not.toBeNull())
    await act(async () => document.body.querySelector<HTMLElement>(`[data-profile-value="harness-1::profile-${name}"]`)!.click())
  }
  const selectModel = async (modelId: 'model-1' | 'model-2') => {
    await act(async () => container.querySelector<HTMLElement>('[data-testid="model-selector-trigger"]')!.click())
    await vi.waitFor(() => expect(document.body.querySelector(`[data-testid="model-option-provider-1-${modelId}"]`)).not.toBeNull())
    await act(async () => document.body.querySelector<HTMLElement>(`[data-testid="model-option-provider-1-${modelId}"]`)!.click())
  }

  await render(initialLocation)
  await selectProfile('A')
  await vi.waitFor(() => expect(writes).toHaveLength(1))
  expect(writes[0]).toMatchObject({ target: 'canonical-draft-1', patch: { 'general.prompt': 'A prompt', model: choices.M1 } })
  expect(container.querySelector('[data-testid="model-selector-trigger"]')?.textContent).toContain('Model 1')

  await selectModel('model-2')
  await vi.waitFor(() => expect(writes).toHaveLength(2))
  expect(writes[1]).toMatchObject({ target: 'canonical-draft-1', patch: { model: choices.M2 } })
  await vi.waitFor(() => expect(container.querySelector('[data-testid="model-selector-trigger"]')?.textContent).toContain('Model 2'))

  await selectProfile('B')
  await vi.waitFor(() => expect(writes).toHaveLength(3))
  expect(writes[2]).toMatchObject({ target: 'canonical-draft-1', patch: { 'general.prompt': 'B prompt' } })
  expect(records.get('canonical-draft-1')?.resolved).toMatchObject({ 'general.prompt': 'B prompt', model: choices.M2 })
  await selectProfile('A')
  await vi.waitFor(() => expect(writes).toHaveLength(4))
  expect(records.get('canonical-draft-1')?.resolved).toMatchObject({ 'general.prompt': 'A prompt', model: choices.M1 })
  await vi.waitFor(() => expect(container.querySelector('[data-testid="model-selector-trigger"]')?.textContent).toContain('Model 1'))
  expect(new Set(writes.map(write => write.target))).toEqual(new Set(['canonical-draft-1']))
  expect(writes.map(write => write.revision)).toEqual([1, 2, 3, 4])

  await act(async () => profileScope.dispose())
  await selectModel('model-2')
  await vi.waitFor(() => expect(writes).toHaveLength(5))
  expect(writes[4]).toMatchObject({ target: 'canonical-draft-1', patch: { model: choices.M2 } })
  expect(sessions.prepareSubmission).not.toHaveBeenCalled()

  // A previously rendered route with generation 8 resolves only after the live
  // route has moved to generation 10. The late backend identity is never bound.
  runtimeGeneration = 10
  const staleLocation = { ...initialLocation, runtimeGeneration: 8 }
  const staleContext = { slot: 'composer.toolbar', location: staleLocation, connection: { status: 'connected' } } as never
  const staleModel = modelView.project!(staleContext)
  await act(async () => root.render(<ComponentOutlet binding={modelBinding} value={staleModel.props} missing={null} />))
  await act(async () => root.render(<ComponentOutlet binding={modelBinding} value={modelView.project!({
    slot: 'composer.toolbar', location: { ...initialLocation, draftId: 'draft-2', runtimeGeneration: 10 },
    connection: { status: 'connected' },
  } as never).props} missing={null} />))
  await vi.waitFor(() => expect(records.has('canonical-draft-2')).toBe(true))
  lateOldResolve.resolve({ kind: 'Accepted', requestId: 'late-old', result: { target: 'canonical-draft-old', generation: 8 } } as never)
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 0)) })
  expect(records.has('canonical-draft-old')).toBe(false)
  expect(records.get('canonical-draft-2')?.resolved).toEqual({})
})
