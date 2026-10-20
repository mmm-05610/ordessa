// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, expect, it, vi } from 'vitest'
import { OwnedResources } from '@ordessa/extension-api'
import { ChatContributionsToken, createChatContributions, type ChatLocation } from '@extensions/ordessa.chat-api/contract.js'
import { ComponentOutlet } from '@ordessa/ui-components/react'
import { UiComponentsToken } from '@extensions/ordessa.contracts/contract.js'
import { ModelProviderToken, type ModelProviderService, type ProviderConfigView } from '@extensions/ordessa.model-provider/contract.js'
import { createUiComponentsService } from '../../../../../../packages/interfaces/channels/workbench/extension-runtime/ui-components/src/index'
import createPlugin, { COMPONENT_PROVIDER_ID, MODEL_SELECTOR_ID, ModelSelectorKey } from '../src/entry'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
const disposers: Array<() => void | Promise<void>> = []
afterEach(async () => { for (const dispose of disposers.splice(0).reverse()) await dispose() })

const location: ChatLocation = {
  kind: 'session', sessionId: 'chat-session-uid', connectionId: 'connection-1',
  serverInstanceId: 'server-1', projectId: 'project-1', harnessId: 'harness-1',
  contextRevision: 4, runtimeGeneration: 9,
}

it('keeps Provider resources readable while refusing model application without a NodeRef configuration capability', async () => {
  const resources = new OwnedResources()
  disposers.push(() => resources.dispose())
  const chat = createChatContributions()
  const ui = createUiComponentsService([
    { componentId: ModelSelectorKey.id, major: 1, providerId: COMPONENT_PROVIDER_ID },
  ])
  disposers.push(() => ui.dispose())
  const provider: ProviderConfigView = {
    id: 'provider-1', version: 7, displayName: 'Provider', harness: 'harness-1', provider: 'fixture',
    credentialId: null,
    models: [{ modelId: 'model-1', displayName: 'Model 1', availability: 'available', unavailableReason: null }],
    archivedAt: null, managedBy: 'harness', state: 'saved', provenance: null,
    createdAt: 'now', updatedAt: 'now',
  }
  const service = {
    list: vi.fn(async () => [provider]),
    testConnection: vi.fn(), fetchModels: vi.fn(), save: vi.fn(),
  } as unknown as ModelProviderService
  const plugin = createPlugin()
  expect(plugin.requires).toEqual([ChatContributionsToken, UiComponentsToken, ModelProviderToken])
  const activate = plugin.activate as (...args: unknown[]) => unknown
  activate({ resources, root: { mount: () => { throw new Error('not used') } } }, chat, ui.uiComponents, service)

  const [view] = chat.contributionsBySlot('composer.toolbar').getSnapshot()
  expect(view?.id).toBe(MODEL_SELECTOR_ID)
  expect(view?.key).toBe(ModelSelectorKey)
  const projection = view.project?.({ slot: 'composer.toolbar', location, connection: { status: 'connected' } } as never)
  const consumer = new OwnedResources()
  disposers.push(() => consumer.dispose())
  const binding = ui.uiComponents.forScope(consumer).bind(view!.key!, { required: true })
  const container = document.createElement('div')
  document.body.append(container)
  const root = createRoot(container)
  disposers.push(async () => { await act(async () => root.unmount()); container.remove() })
  await act(async () => root.render(<ComponentOutlet binding={binding} value={projection!.props} missing={null} />))
  await act(async () => container.querySelector<HTMLElement>('[data-testid="model-selector-trigger"]')!.click())
  const option = await vi.waitFor(() => {
    const found = document.body.querySelector<HTMLElement>('[data-testid="model-option-provider-1-model-1"]')
    expect(found).not.toBeNull()
    return found!
  })
  expect(option.getAttribute('aria-disabled')).toBe('true')
  expect(option.textContent).toContain('Agent Core 尚未提供')
  expect(service.list).toHaveBeenCalledOnce()
  expect(container.textContent).not.toContain('下轮使用')
})
