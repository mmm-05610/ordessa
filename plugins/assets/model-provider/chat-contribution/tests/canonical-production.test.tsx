// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, expect, it, vi } from 'vitest'
import { OwnedResources } from '@ordessa/extension-api'
import { ChatContributionsToken, createChatContributions, type ChatLocation } from '@extensions/ordessa.chat-api/contract.js'
import { ComponentOutlet } from '@ordessa/ui-components/react'
import { UiComponentsToken, WirePortToken, type WirePort } from '@extensions/ordessa.contracts/contract.js'
import { AgentSessionsToken, type AgentSessions } from '@extensions/ordessa.agent-contracts/contract.js'
import { ModelProviderToken, type ModelProviderService, type ProviderConfigView } from '@extensions/ordessa.model-provider/contract.js'
import { createUiComponentsService } from '../../../../packages/frontend/ui-components/src/index'
import createPlugin from '../src/entry'
import { COMPONENT_PROVIDER_ID, MODEL_SELECTOR_ID, ModelSelectorKey } from '../src/entry'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
const resourcesToDispose: Array<() => void | Promise<void>> = []
afterEach(async () => { for (const dispose of resourcesToDispose.splice(0).reverse()) await dispose() })

const location: ChatLocation = {
  kind: 'draft', draftId: 'draft-1', connectionId: 'connection-1', serverInstanceId: 'server-1',
  projectId: 'project-1', harnessId: 'harness-1', contextRevision: 4, runtimeGeneration: 9,
}

it('the production Model selector writes an atomic model intent to the Agent owner', async () => {
  const resources = new OwnedResources()
  resourcesToDispose.push(() => resources.dispose())
  const chat = createChatContributions()
  const uiService = createUiComponentsService([
    { componentId: ModelSelectorKey.id, major: 1, providerId: COMPONENT_PROVIDER_ID },
  ])
  resourcesToDispose.push(() => uiService.dispose())
  const writes: Readonly<Record<string, unknown>>[] = []
  const records = new Map<string, { revision: number; resolved: Record<string, unknown> }>()
  const wire: WirePort = {
    ready: true,
    scope: 'origin:server-1',
    async call(method, params) {
      if (method === 'modelProvider.inspectChoice') {
        return { kind: 'Accepted', requestId: 'inspect', result: {
          verdict: 'supported', providerConfigId: 'provider-1', configVersion: 7,
        } }
      }
      if (method === 'agent.session.resolve') {
        return { kind: 'Accepted', requestId: 'resolve', result: { target: 'canonical-draft-1', generation: 9 } }
      }
      const target = String(params.target)
      let record = records.get(target)
      if (!record) { record = { revision: 0, resolved: {} }; records.set(target, record) }
      if (method === 'agent.config.read') {
        return { kind: 'Accepted', requestId: 'read', result: {
          ownerRef: `agent-config:${target}`, revision: record.revision, observedEvidence: 'unset',
          fields: Object.fromEntries(Object.keys(record.resolved).map(key => [key, 'known'])),
          resolved: { ...record.resolved },
        } }
      }
      if (method === 'agent.config.submitOperation') {
        const patch = params.patch as Record<string, unknown>
        writes.push(patch)
        Object.assign(record.resolved, patch)
        record.revision += 1
        return { kind: 'Accepted', requestId: `write-${record.revision}`, result: {
          operationId: `operation-${record.revision}`, patchKinds: Object.keys(patch).map(() => 'present'), state: 'pending',
        } }
      }
      return { kind: 'Refused', requestId: 'unexpected', reason: `unexpected method ${method}`, retryable: false }
    },
  }
  const prepareSubmission = vi.fn(async () => {
    throw new Error('model selection must not prepare a native session')
  })
  const sessions = {
    getSnapshot: () => ({
      available: [], selectedConnectionId: 'connection-1', runtimeGeneration: 9,
      draft: { active: true, workspaceId: 'project-1', canSend: true },
    }),
    subscribe: () => () => undefined,
    selectConnection: async () => undefined,
    reconnect: async () => undefined,
    refreshSessions: async () => undefined,
    newSession: async () => undefined,
    openSession: async () => undefined,
    send: async () => ({ status: 'accepted' }),
    prepareSubmission,
    stop: async () => undefined,
    respond: async () => undefined,
    setOption: async () => undefined,
    commandCatalog: () => ({ kind: 'absent' }),
  } as unknown as AgentSessions
  const providerConfig: ProviderConfigView = {
    id: 'provider-1', version: 7, displayName: 'Provider', harness: 'harness-1', provider: 'fixture',
    credentialId: null,
    models: [{ modelId: 'model-1', displayName: 'Model 1', availability: 'available', unavailableReason: null }],
    archivedAt: null, managedBy: 'harness', state: 'saved', provenance: null,
    createdAt: 'now', updatedAt: 'now',
  }
  const service = {
    wire: {} as never,
    probeCalls: 0,
    list: vi.fn(async () => [providerConfig]),
    testConnection: async () => ({ status: 'unreachable' }),
    fetchModels: async () => ({ status: 'ok', models: [] }),
    save: async () => { throw new Error('not used') },
  } as unknown as ModelProviderService
  const plugin = createPlugin()
  expect(plugin.requires).toEqual(expect.arrayContaining([
    ChatContributionsToken, UiComponentsToken, WirePortToken, ModelProviderToken, AgentSessionsToken,
  ]))
  const activate = plugin.activate as (...args: unknown[]) => unknown
  activate({ resources, root: { mount: () => { throw new Error('not used') } } },
    chat, uiService.uiComponents, wire, service, sessions)

  const [view] = chat.contributionsBySlot('composer.toolbar').getSnapshot()
  expect(view?.id).toBe(MODEL_SELECTOR_ID)
  expect(view?.key).toBe(ModelSelectorKey)
  const projection = view.project?.({ slot: 'composer.toolbar', location, connection: { status: 'connected' } } as never)
  expect(projection?.hidden).toBe(false)
  const consumer = new OwnedResources()
  resourcesToDispose.push(() => consumer.dispose())
  const binding = uiService.uiComponents.forScope(consumer).bind(view!.key!, { required: true })
  const container = document.createElement('div')
  document.body.append(container)
  const root = createRoot(container)
  resourcesToDispose.push(async () => { await act(async () => root.unmount()); container.remove() })
  await act(async () => root.render(<ComponentOutlet binding={binding} value={projection!.props} missing={null} />))
  await act(async () => { container.querySelector<HTMLElement>('[data-testid="model-selector-trigger"]')!.click() })
  await act(async () => { document.body.querySelector<HTMLElement>('[data-testid="model-option-provider-1-model-1"]')!.click() })
  await vi.waitFor(() => expect(writes).toHaveLength(1))

  expect(writes[0]).toEqual({ model: {
    harnessId: 'harness-1', providerConfigId: 'provider-1', modelId: 'model-1', configVersion: 7,
  } })
  expect(records.size).toBe(1)
  expect(prepareSubmission).not.toHaveBeenCalled()
})
