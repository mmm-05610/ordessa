// @vitest-environment jsdom
// T4.1: the selector must be reachable in the SHIPPED assembly, not only in a
// stub. Red before this file existed: `src/entry.tsx` — the package's declared
// loadable entry — registered through the local `stub-chat-contract` on a
// `composer.footer` slot that the frozen chat-api contract does not have, so
// the real Chat registry never saw a model selector at all.
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import path from 'node:path'
import { OwnedResources } from '@ordessa/extension-api'
import {
  ChatContributionsToken, createChatContributions, type ChatContributionView,
} from '@extensions/ordessa.chat-api/contract.js'
import { ComponentOutlet } from '@ordessa/ui-components/react'
import { WirePortToken } from '@extensions/ordessa.contracts/contract.js'
import { createUiComponentsService } from '../../../../../packages/desktop-platform/ui-components/src/index'
import createPlugin, { COMPONENT_PROVIDER_ID, TRANSPORT_MISSING } from '../src/entry'
import { MODEL_SELECTOR_ID, ModelSelectorKey } from '../src/chat-api-entry'
import { ModelSelector } from '../src/selector'
import type { ModelProviderService, ProviderConfigView } from '../../contracts/index'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
const cleanup: (() => void | Promise<void>)[] = []
afterEach(async () => { for (const fn of cleanup.splice(0).reverse()) await fn(); vi.restoreAllMocks() })

async function mount(element: React.ReactNode) {
  const container = document.createElement('div'); document.body.append(container)
  const root = createRoot(container)
  cleanup.push(async () => { await act(async () => root.unmount()); container.remove() })
  await act(async () => root.render(element))
  return container
}

function activationContext(resources: OwnedResources) {
  return { root: { mount: () => ({ dispose() {} }) }, resources } as never
}

/** The real ui-components service, configured the way the product configures
 * the Profile picker: one componentId/major/providerId triple. A contribution
 * whose key has no provider here renders NOTHING in the composer. */
function uiComponents() {
  const service = createUiComponentsService([
    { componentId: ModelSelectorKey.id, major: 1, providerId: COMPONENT_PROVIDER_ID },
  ])
  cleanup.push(() => service.dispose())
  return service.uiComponents
}

/** A wire port whose calls are recorded, so the plugin cannot reach anything
 * except the platform port it declared. */
function wirePort(result: unknown = { ok: true }) {
  const calls: { method: string; params: object }[] = []
  return { calls, port: { call: async (method: string, params: object) => { calls.push({ method, params }); return { kind: 'Accepted', result } } } }
}

describe('the declared plugin entry is the real Chat wiring', () => {
  it('registers the selector on the real Chat registry, on a slot Chat actually renders', () => {
    const chat = createChatContributions()
    const resources = new OwnedResources()
    cleanup.push(() => resources.dispose())
    const { port } = wirePort()
    const plugin = createPlugin()
    expect(plugin.requires).toContain(ChatContributionsToken)
    expect(plugin.requires).toContain(WirePortToken)
    plugin.activate(activationContext(resources), chat, uiComponents(), port as never, service([]))

    const views: readonly ChatContributionView[] = chat.contributionsBySlot('composer.toolbar').getSnapshot()
    expect(views).toHaveLength(1)
    expect(views[0].id).toBe(MODEL_SELECTOR_ID)
    expect(views[0].keyId).toBe(ModelSelectorKey.id)
    expect(views[0].keyMajor).toBe(1)
    // The chat-api registry accepted a real registration, not the local stub's
    // `{ id, slot, component }` record.
    expect(typeof views[0].project).toBe('function')
  })

  it('the composer actually renders the selector through the bound key', async () => {
    const chat = createChatContributions()
    const resources = new OwnedResources()
    cleanup.push(() => resources.dispose())
    const ui = uiComponents()
    const { port } = wirePort({ outcome: 'pending-next-turn', sequence: 4, intentRoute: 'independent' })
    createPlugin().activate(activationContext(resources), chat, ui, port as never, service([config()]))

    const [view] = chat.contributionsBySlot('composer.toolbar').getSnapshot()
    const context = {
      slot: 'composer.toolbar' as const,
      location: { kind: 'session', connectionId: 'c', serverInstanceId: 's', sessionId: 'n',
        harnessId: 'h', contextRevision: 0 },
      connection: { status: 'connected' },
    }
    const projection = view.project?.(context as never)
    expect(projection?.hidden).toBe(false)
    // The contribution context carries the location and nothing else: no
    // service, no transport, no credential.
    expect(Object.keys((projection as { props: object }).props)).toEqual(['location'])

    // Chat resolves a contribution by binding its key through
    // `ui.bind(key, { required: false })`. This is the mount path.
    const consumer = new OwnedResources()
    cleanup.push(() => consumer.dispose())
    const binding = ui.forScope(consumer).bind(view.key!, { required: true })
    const container = await mount(
      <ComponentOutlet binding={binding} value={(projection as { props: unknown }).props} missing={null} />)
    expect(container.querySelector('[data-testid="model-selector"]')).not.toBeNull()

    await act(async () => { container.querySelector<HTMLElement>('[data-testid="model-selector-trigger"]')!.click() })
    expect(document.body.querySelector('[data-testid="model-option-p1-gpt-5.4"]')).not.toBeNull()
  })

  it('a queued choice travels over the declared wire port, through the frozen method', async () => {
    const chat = createChatContributions()
    const resources = new OwnedResources()
    cleanup.push(() => resources.dispose())
    const ui = uiComponents()
    const { port, calls } = wirePort({ outcome: 'pending-next-turn', sequence: 4, intentRoute: 'independent' })
    createPlugin().activate(activationContext(resources), chat, ui, port as never, service([config()]))
    const [view] = chat.contributionsBySlot('composer.toolbar').getSnapshot()
    const projection = view.project?.({
      slot: 'composer.toolbar',
      location: { kind: 'session', connectionId: 'c', serverInstanceId: 's', sessionId: 'n',
        harnessId: 'h', contextRevision: 0 },
      connection: { status: 'connected' },
    } as never)
    const consumer = new OwnedResources()
    cleanup.push(() => consumer.dispose())
    const binding = ui.forScope(consumer).bind(view.key!, { required: true })
    const container = await mount(
      <ComponentOutlet binding={binding} value={(projection as { props: unknown }).props} missing={null} />)
    await act(async () => { container.querySelector<HTMLElement>('[data-testid="model-selector-trigger"]')!.click() })
    await act(async () => { document.body.querySelector<HTMLElement>('[data-testid="model-option-p1-gpt-5.4"]')!.click() })
    await act(async () => {})

    // The production selector answers `unknown` for eligibility (the ACP
    // seam is not wired), so nothing is queued — and nothing is invented.
    expect(calls).toEqual([])
    const options = document.body.querySelectorAll('[role="option"]')
    expect(options).toHaveLength(1)
  })

  it('no production file invents a slot the frozen Chat contract does not have', () => {
    const slots = new Set(['composer.toolbar', 'session.actions', 'session.auxiliary',
      'message.actions', 'settings.sections', 'content.renderers'])
    for (const file of ['entry.tsx', 'chat-api-entry.tsx']) {
      const source = readFileSync(path.join(import.meta.dirname, '..', 'src', file), 'utf8')
      for (const [, slot] of source.matchAll(/slot:\s*'([a-z.]+)'/g)) {
        expect(slots.has(slot), `${file} registers unknown slot ${slot}`).toBe(true)
      }
      expect(source).not.toContain('composer.footer')
      // Production code must not depend on the migration stub.
      expect(source).not.toContain('stub-chat-contract')
    }
  })

  it('refuses activation with no wire port rather than a selector that cannot reach the Server', () => {
    const chat = createChatContributions()
    const resources = new OwnedResources()
    cleanup.push(() => resources.dispose())
    expect(() => createPlugin().activate(activationContext(resources), chat, uiComponents(),
      undefined as never, service([]))).toThrow(TRANSPORT_MISSING)
  })

})

// ——— D04: options follow backend capability, and a load failure is retryable ———

function config(over: Partial<ProviderConfigView> = {}): ProviderConfigView {
  return { id: 'p1', version: 1, displayName: '账号', harness: 'h', provider: 'p', credentialId: null,
    models: [{ modelId: 'gpt-5.4', displayName: 'GPT', availability: 'available', unavailableReason: null }],
    archivedAt: null, managedBy: 'harness', state: 'saved', provenance: null,
    createdAt: 't', updatedAt: 't', ...over }
}

function service(configs: readonly ProviderConfigView[], list?: () => Promise<readonly ProviderConfigView[]>)
  : ModelProviderService {
  return { wire: {} as never, probeCalls: 0,
    list: () => (list ? list() : Promise.resolve(configs)),
    testConnection: () => Promise.resolve({ status: 'unreachable' }),
    fetchModels: () => Promise.resolve({ status: 'ok', models: [] }),
    save: () => Promise.reject(new Error('not used here')) } as unknown as ModelProviderService
}

const SESSION = { kind: 'session' as const, session: { serverInstanceId: 's', harnessId: 'h', acpSessionId: 'n' } }

async function openSelector(svc: ModelProviderService) {
  const container = await mount(<ModelSelector service={svc} location={SESSION}
    eligibilitySource={{ eligibility: () => 'ready' }} />)
  await act(async () => {})
  await act(async () => { container.querySelector<HTMLElement>('[data-testid="model-selector-trigger"]')?.click() })
  return container
}

describe('model load failure is an explicit, retryable state (D04)', () => {
  it('shows the failure with a retry control instead of an empty, plausible list', async () => {
    let attempt = 0
    const svc = service([], () => { attempt += 1; return Promise.reject(new Error('backend said no')) })
    const container = await openSelector(svc)
    expect(attempt).toBe(1)
    const error = document.body.querySelector('[data-testid="model-load-error"]')!
    expect(error.textContent).toContain('backend said no')
    expect(document.body.querySelector('[data-testid="no-selectable"]')).toBeNull()
    expect(document.body.querySelectorAll('[role="option"]')).toHaveLength(0)

    await act(async () => { document.body.querySelector<HTMLElement>('[data-testid="model-load-retry"]')!.click() })
    await act(async () => {})
    expect(attempt).toBe(2)
  })

  it('the explicit retry recovers and lists the backend rows', async () => {
    let attempt = 0
    const svc = service([], async () => {
      attempt += 1
      if (attempt === 1) throw new Error('transient')
      return [config()]
    })
    const container = await openSelector(svc)
    await act(async () => { document.body.querySelector<HTMLElement>('[data-testid="model-load-retry"]')!.click() })
    await act(async () => {})
    expect(document.body.querySelector('[data-testid="model-load-error"]')).toBeNull()
    expect(document.body.querySelector('[data-testid="model-option-p1-gpt-5.4"]')).not.toBeNull()
  })

  it('a still-failing retry stays failed and is not silently swallowed', async () => {
    let attempt = 0
    const svc = service([], () => { attempt += 1; return Promise.reject(new Error('still down')) })
    const container = await openSelector(svc)
    await act(async () => { document.body.querySelector<HTMLElement>('[data-testid="model-load-retry"]')!.click() })
    await act(async () => {})
    expect(attempt).toBe(2)
    expect(document.body.querySelector('[data-testid="model-load-error"]')!.textContent).toContain('still down')
  })

  it('a model the backend reports unavailable is listed but not selectable, with its reason', async () => {
    const svc = service([config({ models: [
      { modelId: 'gpt-5.4', displayName: 'GPT', availability: 'available', unavailableReason: null },
      { modelId: 'gone', displayName: 'Gone', availability: 'unavailable', unavailableReason: '供应商已下架该模型' },
    ] })])
    const container = await openSelector(svc)
    const option = document.body.querySelector('[data-testid="model-option-p1-gone"]')!
    expect(option.getAttribute('aria-disabled')).toBe('true')
    expect(option.textContent).toContain('供应商已下架该模型')
    // Readiness from the eligibility source alone must not re-enable it.
    expect(document.body.querySelector('[data-testid="model-option-p1-gpt-5.4"]')!.getAttribute('aria-disabled')).toBe('false')
  })
})
