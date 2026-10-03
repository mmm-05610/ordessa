// migrated from plugins/model-provider@9305563719d25e04076b9221a7284660bd8f8642 (tests/contributor.test.tsx, verbatim)
// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { OwnedResources, type ResourceScope } from '@ordessa/extension-api'
import { createChatContributions } from '@extensions/ordessa.chat-api/contract.js'
import { createUiComponentsService } from '../../../../packages/desktop-platform/ui-components/src/index'
import { ModelSelector, type SessionEligibilitySource } from '../src/selector'
import { createChatContributionsStub } from '../src/stub-chat-contract'
import createPlugin from '../src/entry'
import { MODEL_SELECTOR_ID, ModelSelectorKey } from '../src/chat-api-entry'
import type { ProviderConfigView } from '../../contracts/index'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
const cleanup: (() => void | Promise<void>)[] = []
afterEach(async () => { for (const fn of cleanup.splice(0).reverse()) await fn(); vi.restoreAllMocks(); vi.unstubAllGlobals() })

async function mount(element: React.ReactNode) {
  const container = document.createElement('div'); document.body.append(container)
  const root = createRoot(container)
  cleanup.push(async () => { await act(async () => root.unmount()); container.remove() })
  await act(async () => root.render(element))
  // The menu is deliberately portalled outside the composer clipping boundary.
  return document.body
}

const CONFIGS: ProviderConfigView[] = [
  {
    id: 'provider-1', version: 1, displayName: '已登录账号', harness: 'codex',
    provider: 'codex', credentialId: null,
    models: [
      { modelId: 'gpt-5.4', displayName: 'GPT', availability: 'available', unavailableReason: null },
      { modelId: 'o4-mini', displayName: 'Mini', availability: 'available', unavailableReason: null },
    ],
    archivedAt: null, managedBy: 'harness', state: 'saved', provenance: null,
    createdAt: 't', updatedAt: 't',
  },
  {
    id: 'provider-2', version: 1, displayName: '另一个 Harness 的配置', harness: 'claude',
    provider: 'claude', credentialId: null,
    models: [{ modelId: 'claude-x', displayName: 'X', availability: 'available', unavailableReason: null }],
    archivedAt: null, managedBy: 'ordessa', state: 'saved', provenance: null,
    createdAt: 't', updatedAt: 't',
  },
]

const SESSION_LOCATION = {
  kind: 'session' as const,
  session: { serverInstanceId: 'srv-1', harnessId: 'codex', acpSessionId: 'sess-A' },
}

function fakeService(): import('../../contracts/index').ModelProviderService {
  return {
    wire: {} as never,
    probeCalls: 0,
    list: () => Promise.resolve(CONFIGS),
    testConnection: () => Promise.resolve({ status: 'unreachable' }),
    fetchModels: () => Promise.resolve({ status: 'ok', models: [] }),
    save: () => Promise.reject(new Error('not used here')),
  }
}

async function openSelector(props: Partial<Parameters<typeof ModelSelector>[0]> = {}) {
  const queued: { value: Parameters<NonNullable<Parameters<typeof ModelSelector>[0]>['onQueue']>[0] | null } = { value: null }
  const container = await mount(<ModelSelector
    service={props.service ?? fakeService()}
    location={props.location ?? SESSION_LOCATION}
    eligibilitySource={props.eligibilitySource}
    queued={props.queued}
    onQueue={(choice) => { queued.value = choice }} />)
  await act(async () => {}) // list loads
  await act(async () => {
    container.querySelector<HTMLElement>('[data-testid="model-selector-trigger"]')!.click()
  })
  return { container, queued }
}

const READY_SOURCE: SessionEligibilitySource = { eligibility: () => 'ready' }

describe('composer.footer model selector (R2 gate)', () => {
  it('rechecks live eligibility when reopening the same session menu', async () => {
    let ready = false
    const inspectChoice = vi.fn(async () => ({
      eligibility: ready ? 'ready' as const : 'unknown' as const,
      reason: ready ? undefined : 'unknown',
    }))
    const onQueue = vi.fn()
    const container = await mount(<ModelSelector service={fakeService()}
      location={SESSION_LOCATION} inspectChoice={inspectChoice} onQueue={onQueue} />)
    const trigger = container.querySelector<HTMLElement>('[data-testid="model-selector-trigger"]')!
    await act(async () => trigger.click())
    expect(container.querySelector('[role="option"]')!.getAttribute('aria-disabled')).toBe('true')
    await act(async () => trigger.click())
    const calls = inspectChoice.mock.calls.length
    ready = true
    await act(async () => trigger.click())
    expect(inspectChoice.mock.calls.length).toBeGreaterThan(calls)
    const option = container.querySelector<HTMLElement>('[data-testid="model-option-provider-1-gpt-5.4"]')!
    expect(option.getAttribute('aria-disabled')).toBe('false')
    await act(async () => option.click())
    expect(onQueue).toHaveBeenCalledWith({ harnessId: 'codex', providerConfigId: 'provider-1', modelId: 'gpt-5.4', configVersion: 1 })
  })

  it('lists only this harness\'s configs, grouped Provider › Model, no harness switcher', async () => {
    const { container } = await openSelector({ eligibilitySource: READY_SOURCE })
    const list = container.querySelector('[data-testid="model-selector-list"]')!
    expect(list.textContent).toContain('已登录账号')
    expect(list.textContent).toContain('GPT')
    expect(list.textContent).not.toContain('claude-x')       // other harness never listed
    expect(list.textContent).not.toContain('Harness 选择')    // no switcher, only the two levels
    expect(container.querySelectorAll('[role="option"]')).toHaveLength(2)
  })

  it('queues an atomic choice only for ready items', async () => {
    const { container, queued } = await openSelector({ eligibilitySource: READY_SOURCE })
    await act(async () => {
      container.querySelector<HTMLElement>('[data-testid="model-option-provider-1-gpt-5.4"]')!.click()
    })
    expect(queued.value).toEqual({ harnessId: 'codex', providerConfigId: 'provider-1', modelId: 'gpt-5.4' })
  })

  it('non-ready items show the reason and refuse selection', async () => {
    const source: SessionEligibilitySource = {
      eligibility: (_h, configId, modelId) =>
        configId === 'provider-1' && modelId === 'o4-mini' ? 'unsupported' : 'ready',
      reason: (_h, configId, modelId) =>
        configId === 'provider-1' && modelId === 'o4-mini' ? '配置选项已消失' : undefined,
    }
    const { container, queued } = await openSelector({ eligibilitySource: source })
    const blocked = container.querySelector('[data-testid="model-option-provider-1-o4-mini"]')!
    expect(blocked.getAttribute('aria-disabled')).toBe('true')
    expect(blocked.textContent).toContain('此 Harness 不支持')
    expect(blocked.textContent).toContain('配置选项已消失')
    await act(async () => { blocked.click() })
    expect(queued.value).toBeNull()          // cannot be mis-selected
  })

  it('without session-config evidence the selector answers unknown, never fake-ready', async () => {
    const { container, queued } = await openSelector()  // no eligibilitySource wired
    const list = container.querySelector('[data-testid="model-selector-list"]')!
    expect(list.querySelector('[data-testid="no-selectable"]')!.textContent)
      .toContain('此会话暂不可选模型')
    await act(async () => {
      container.querySelector<HTMLElement>('[data-testid="model-option-provider-1-gpt-5.4"]')!.click()
    })
    expect(queued.value).toBeNull()
  })

  it('queues replace the shown choice atomically ("下轮使用")', async () => {
    const queuedChoice = { harnessId: 'codex', providerConfigId: 'provider-1', modelId: 'o4-mini' }
    const { container } = await openSelector({ eligibilitySource: READY_SOURCE, queued: queuedChoice })
    expect(container.querySelector('[data-testid="model-selector-trigger"]')!.textContent)
      .toContain('已登录账号 › Mini')
    expect(container.querySelector('[data-testid="model-selector-trigger"]')!.textContent)
      .toContain('下轮使用')
  })

  it('portals an anchored, viewport-bounded menu and restores focus on Escape', async () => {
    const { container } = await openSelector({ eligibilitySource: READY_SOURCE })
    const list = container.querySelector<HTMLElement>('[data-testid="model-selector-list"]')!
    expect(list.parentElement).toBe(document.body)
    expect(list.style.position).toBe('fixed')
    expect(Number.parseFloat(list.style.width)).toBeLessThanOrEqual(window.innerWidth - 16)
    const options = Array.from(list.querySelectorAll<HTMLElement>('[role="option"]'))
    expect(document.activeElement).toBe(options[0])
    await act(async () => options[0].dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true })))
    expect(document.activeElement).toBe(options[1])
    await act(async () => options[1].dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })))
    expect(container.querySelector('[data-testid="model-selector-list"]')).toBeNull()
    const trigger = container.querySelector('[data-testid="model-selector-trigger"]')!
    expect(document.activeElement).toBe(trigger)
    expect(trigger.getAttribute('aria-expanded')).toBe('false')
  })

  it('closes on outside interaction without selecting a model', async () => {
    const { container, queued } = await openSelector({ eligibilitySource: READY_SOURCE })
    await act(async () => document.body.dispatchEvent(new Event('pointerdown', { bubbles: true })))
    expect(container.querySelector('[data-testid="model-selector-list"]')).toBeNull()
    expect(queued.value).toBeNull()
  })

  it('remeasures wrapping changes locally without resetting keyboard focus', async () => {
    const observers: { callback: () => void; disconnect: ReturnType<typeof vi.fn> }[] = []
    vi.stubGlobal('ResizeObserver', class {
      disconnect = vi.fn()
      constructor(callback: () => void) { observers.push({ callback, disconnect: this.disconnect }) }
      observe() {}
    })
    const container = await mount(<ModelSelector service={fakeService()} location={SESSION_LOCATION} eligibilitySource={READY_SOURCE} />)
    const trigger = container.querySelector<HTMLButtonElement>('[data-testid="model-selector-trigger"]')!
    vi.spyOn(trigger, 'getBoundingClientRect').mockReturnValue({ top: 650, bottom: 678, left: 100, right: 240, width: 140, height: 28 } as DOMRect)
    await act(async () => trigger.click())
    const list = container.querySelector<HTMLElement>('[data-testid="model-selector-list"]')!
    const option = list.querySelector<HTMLElement>('[role="option"]')!
    let height = 160
    Object.defineProperty(list, 'scrollHeight', { configurable: true, get: () => height })
    await act(async () => observers[0].callback())
    expect(Number.parseFloat(list.style.top)).toBe(482)
    height = 280
    await act(async () => observers[0].callback())
    expect(Number.parseFloat(list.style.top)).toBe(362)
    expect(document.activeElement).toBe(option)
    await act(async () => option.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })))
    expect(observers[0].disconnect).toHaveBeenCalledOnce()
  })

  it('closes when a scrolling container moves the anchor outside the viewport', async () => {
    const { container, queued } = await openSelector({ eligibilitySource: READY_SOURCE })
    const trigger = container.querySelector<HTMLButtonElement>('[data-testid="model-selector-trigger"]')!
    vi.spyOn(trigger, 'getBoundingClientRect').mockReturnValue({ top: -40, bottom: -12, left: 20, right: 100, width: 80, height: 28 } as DOMRect)
    const focus = vi.spyOn(trigger, 'focus')
    await act(async () => window.dispatchEvent(new Event('scroll')))
    expect(container.querySelector('[data-testid="model-selector-list"]')).toBeNull()
    expect(focus).toHaveBeenCalledWith({ preventScroll: true })
    expect(queued.value).toBeNull()
  })

  it('shows a draft explanation instead of perpetual session checking', async () => {
    const container = await mount(<ModelSelector service={fakeService()} disabled inspectChoice={vi.fn()}
      location={{ kind: 'draft', target: { serverInstanceId: 'srv-1', harnessId: 'codex', projectId: 'p' } }} />)
    await act(async () => container.querySelector<HTMLElement>('[data-testid="model-selector-trigger"]')!.click())
    expect(container.querySelector('[data-testid="model-selector-list"]')!.textContent).toContain('创建会话后才能核实模型')
    expect(container.querySelector('[data-testid="model-selector-list"]')!.textContent).not.toContain('正在核实')
    expect(container.querySelector('[role="option"]')!.getAttribute('aria-disabled')).toBe('true')
  })
})

describe('contribution registration semantics (contract stub)', () => {
  it('registers one composer.footer contribution; duplicate id fails; dispose removes it', () => {
    const registry = createChatContributionsStub()
    const scope: ResourceScope = new OwnedResources()
    cleanup.push(() => scope.dispose())
    const chat = registry.stub
    const first = chat.forScope(scope).add({
      id: 'model-provider.composer.footer', slot: 'composer.footer', component: ModelSelector,
    })
    expect(registry.contributions(scope)).toHaveLength(1)
    expect(() => chat.forScope(scope).add({
      id: 'model-provider.composer.footer', slot: 'composer.footer', component: ModelSelector,
    })).toThrow(/duplicate/)
    first.dispose()
    expect(registry.contributions(scope)).toHaveLength(0)  // uninstall removes the selector only
  })

  it('adding into a closed scope fails (contract runtime semantics)', () => {
    const registry = createChatContributionsStub()
    const scope: ResourceScope = new OwnedResources()
    registry.close(scope)
    expect(() => registry.stub.forScope(scope).add({
      id: 'x', slot: 'chat.settings', component: () => null,
    })).toThrow(/closed/)
  })

  it('the plugin wires the selector through Chat\'s public contract only', () => {
    // T4.1 (2026-10-01): this assertion used to run against the LOCAL stub and
    // passed because `src/entry.tsx` registered into it. The declared entry now
    // consumes the real chat-api contract (see tests/production-entry.test.tsx
    // for the full proof), so the same intent is re-asserted there: the plugin
    // reaches Chat only through `ChatContributionsToken` + `addContribution`.
    const resources = new OwnedResources()
    cleanup.push(() => resources.dispose())
    const chat = createChatContributions()
    const { port } = { port: { ready: true, scope: 's', call: async () =>
      ({ kind: 'Accepted', requestId: 'r', result: {} }) } }
    const ui = createUiComponentsService([
      { componentId: ModelSelectorKey.id, major: 1, providerId: 'ordessa.model-provider-chat' },
    ])
    cleanup.push(() => ui.dispose())
    createPlugin().activate(
      { root: { mount: () => ({ dispose() {} }) }, resources } as never,
      chat, ui.uiComponents, port as never, fakeService())
    const [view] = chat.contributionsBySlot('composer.toolbar').getSnapshot()
    expect(view).toBeDefined()
    expect(view.id).toBe(MODEL_SELECTOR_ID)
    expect(view.keyId).toBe(ModelSelectorKey.id)
  })
})
