// migrated from plugins/model-provider@9305563719d25e04076b9221a7284660bd8f8642 (tests/contributor.test.tsx, verbatim)
// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { OwnedResources, type ResourceScope } from '@ordessa/extension-api'
import { ModelSelector, type SessionEligibilitySource } from '../src/selector'
import { createChatContributionsStub } from '../src/stub-chat-contract'
import createPlugin from '../src/entry'
import type { ProviderConfigView } from '../../contracts/index'

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
  it('lists only this harness\'s configs, grouped Provider › Model, no harness switcher', async () => {
    const { container } = await openSelector({ eligibilitySource: READY_SOURCE })
    const list = container.querySelector('[data-testid="model-selector-list"]')!
    expect(list.textContent).toContain('已登录账号')
    expect(list.textContent).toContain('gpt-5.4')
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
      .toContain('provider-1 › o4-mini')
    expect(container.querySelector('[data-testid="model-selector-trigger"]')!.textContent)
      .toContain('下轮使用')
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
    const registry = createChatContributionsStub()
    const resources = new OwnedResources()
    cleanup.push(() => resources.dispose())
    const context = { root: { mount: () => ({ dispose() {} }) }, resources }
    const plugin = createPlugin()
    plugin.activate(context as never, registry.stub, fakeService())
    const contributions = registry.contributions(resources)
    expect(contributions).toHaveLength(1)
    expect(contributions[0].slot).toBe('composer.footer')
    expect(contributions[0].id).toBe('model-provider.composer.footer')
  })
})
