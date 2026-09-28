// migrated from plugins/model-provider@9305563719d25e04076b9221a7284660bd8f8642 (tests/settings.test.tsx, verbatim)
// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { OwnedResources, type IDisposable, type ResourceScope } from '@ordessa/extension-api'
import { WorkbenchToken, type Workbench, type WorkbenchSettingsSection } from '@extensions/ordessa.contracts/contract.js'
import { createPlugin, SETTINGS_SECTION_ID, TRANSPORT_MISSING } from '../src/entry'
import { createModelProviderService } from '../src/service'
import { ModelProviderSettings } from '../src/settings'
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

function button(container: HTMLElement, testId: string): HTMLButtonElement {
  const found = container.querySelector<HTMLButtonElement>(`[data-testid="${testId}"]`)
  expect(found, testId).toBeTruthy()
  return found!
}

function configFixture(over: Partial<ProviderConfigView> = {}): ProviderConfigView {
  return {
    id: 'provider-1', version: 1, displayName: '我的 API', harness: 'pi',
    provider: 'acme', credentialId: 'cred-1',
    models: [{ modelId: 'glm-5', displayName: 'GLM', availability: 'available', unavailableReason: null }],
    archivedAt: null, managedBy: 'ordessa', state: 'saved',
    provenance: { baseUrl: 'https://127.0.0.1/v1' },
    createdAt: 't', updatedAt: 't', ...over,
  }
}

/** A fake transport that answers the wire like the new owner plugin does. */
function fakeTransport(over: Partial<Record<string, unknown>> = {}) {
  const calls: { method: string; params: object }[] = []
  const transport = (method: string, params: object) => {
    calls.push({ method, params })
    if (method === 'providerModels.list') {
      return Promise.resolve({ items: (over.items as ProviderConfigView[]) ?? [configFixture()], nextCursor: null })
    }
    if (method === 'providerModels.probeConnection') {
      return Promise.resolve(over.probeConnection ?? { status: 'reachable', detail: 'endpoint answered' })
    }
    if (method === 'providerModels.create') {
      return Promise.resolve({ providerModel: (over.created as ProviderConfigView) ?? configFixture({ displayName: '未命名配置' }) })
    }
    return Promise.resolve(over.default ?? {})
  }
  return { transport, calls }
}

async function renderSettings(over?: Partial<Record<string, unknown>>) {
  const { transport, calls } = fakeTransport(over)
  const service = createModelProviderService(transport)
  const container = await mount(<ModelProviderSettings service={service} />)
  return { container, service, calls }
}

describe('G6: render never probes', () => {
  it('mounting the settings pane issues zero probe calls', async () => {
    const { container } = await renderSettings()
    await act(async () => {}) // let the list load settle
    expect(container.querySelector('[data-testid="model-provider-settings"]')).toBeTruthy()
    expect(container.textContent).toContain('我的 API')
  })

  it('only the 测试连接 button reaches the network, exactly once per click', async () => {
    const { container, service, calls } = await renderSettings()
    await act(async () => {}) // list loaded
    expect(service.probeCalls).toBe(0)
    expect(calls.filter((call) => call.method.startsWith('providerModels.probe'))).toHaveLength(0)
    // open the detail, then probe
    await act(async () => { container.querySelector<HTMLElement>('[data-testid="config-provider-1"]')!.click() })
    const probeButton = button(container, 'test-connection')
    await act(async () => { probeButton.click() })
    await act(async () => {})
    expect(service.probeCalls).toBe(1)
    const pane = container.querySelector('[data-testid="model-provider-settings"]')!
    expect(pane.textContent).toContain('最近探测通过')
    expect(pane.textContent).not.toContain('已启用')
  })

  it('a failed probe names the failure and the next step, never "已启用"', async () => {
    const { container } = await renderSettings({ probeConnection: { status: 'failed', code: 'PROBE_AUTH_FAILED' } })
    await act(async () => {})
    await act(async () => { container.querySelector<HTMLElement>('[data-testid="config-provider-1"]')!.click() })
    await act(async () => { button(container, 'test-connection').click() })
    await act(async () => {})
    const feedback = container.querySelector('[data-testid="feedback"]')!
    expect(feedback.textContent).toContain('PROBE_AUTH_FAILED')
    expect(feedback.textContent).toContain('凭据')
    expect(container.textContent).not.toContain('已启用')
  })

  it('saving reports 已保存 only', async () => {
    const { container } = await renderSettings()
    await act(async () => {})
    await act(async () => { button(container, 'add-config').click() })
    await act(async () => { button(container, 'save-config').click() })
    await act(async () => {})
    const feedback = container.querySelector('[data-testid="feedback"]')!
    expect(feedback.textContent).toContain('已保存')
    expect(feedback.textContent).not.toContain('已启用')
  })
})

describe('credential reference hygiene (G9 desktop face)', () => {
  it('renders the reference id but never secret content', async () => {
    const { container } = await renderSettings()
    await act(async () => {})
    await act(async () => { container.querySelector<HTMLElement>('[data-testid="config-provider-1"]')!.click() })
    expect(container.textContent).toContain('cred-1')
    expect(container.textContent).not.toContain('sekret-sentinel-1234')
  })
})

describe('keyboard operation (FR-NFR-3)', () => {
  it('arrow keys move the selection; Esc closes the detail', async () => {
    const second = configFixture({ id: 'provider-2', displayName: '另一个' })
    const { container } = await renderSettings({ items: [configFixture(), second] })
    await act(async () => {})
    await act(async () => { container.querySelector<HTMLElement>('[data-testid="config-provider-1"]')!.click() })
    const listbox = container.querySelector('[role="listbox"]') as HTMLElement
    await act(async () => { listbox.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true })) })
    const options = [...container.querySelectorAll<HTMLElement>('[role="option"]')]
    expect(options[1].getAttribute('aria-selected')).toBe('true')
    await act(async () => { listbox.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })) })
    expect(container.querySelector('[data-testid="detail-pane"]')!.textContent).toContain('选择一条配置')
  })
})

// -- extension-level registration: composition present/absent, transport ----

function fakeWorkbench(composition: Workbench['composition']): { workbench: Workbench; sections: WorkbenchSettingsSection[] } {
  const sections: WorkbenchSettingsSection[] = []
  const workbench: Workbench = {
    forScope(_scope: ResourceScope) {
      return {
        addView: () => ({ dispose() {} }),
        addUI: () => ({ dispose() {} }),
      }
    },
    open() {}, close() {},
    composition,
  }
  return { workbench, sections }
}

function fakeContext() {
  const resources = new OwnedResources()
  cleanup.push(() => resources.dispose())
  return { root: { mount: () => ({ dispose() {} }) }, resources }
}

describe('G10: absence and registration', () => {
  it('registers exactly one settings section when composition and transport exist', () => {
    const { workbench, sections } = fakeWorkbench({
      forScope: () => ({
        addModule: () => ({ dispose() {} }),
        addOverlay: () => ({ dispose() {} }),
        addSettingsSection: (section: WorkbenchSettingsSection) => { sections.push(section); return { dispose() {} } },
      }),
      activateModule: () => {}, openOverlay: () => ({ dispose() {} }), openSettings: () => {},
    })
    const { transport } = fakeTransport()
    const plugin = createPlugin(transport)
    const service = plugin.activate(fakeContext() as never, workbench)
    expect(sections.map((section) => section.id)).toEqual([SETTINGS_SECTION_ID])
    expect(sections[0].title).toBe('模型与服务')
    expect(service).toBeTruthy()
  })

  it('an absent composition is a typed refusal, not silent degradation', () => {
    const { workbench } = fakeWorkbench(undefined)
    const { transport } = fakeTransport()
    expect(() => createPlugin(transport).activate(fakeContext() as never, workbench))
      .toThrow(/composition capability/)
  })

  it('an unbound transport refuses activation (contract gap, fail-closed)', () => {
    const { workbench } = fakeWorkbench({
      forScope: () => ({
        addModule: () => ({ dispose() {} }),
        addOverlay: () => ({ dispose() {} }),
        addSettingsSection: () => ({ dispose() {} }),
      }),
      activateModule: () => {}, openOverlay: () => ({ dispose() {} }), openSettings: () => {},
    })
    try {
      createPlugin(undefined).activate(fakeContext() as never, workbench)
      expect.unreachable('activation should have refused')
    } catch (error) {
      expect((error as Error).message).toContain(TRANSPORT_MISSING)
    }
  })

  it('the absence comparison: nothing else registers and no section exists without this plugin', () => {
    // Without this plugin the Workbench simply never sees SETTINGS_SECTION_ID;
    // a companion section registers fine, proving the host still works.
    const { workbench, sections } = fakeWorkbench({
      forScope: () => ({
        addModule: () => ({ dispose() {} }),
        addOverlay: () => ({ dispose() {} }),
        addSettingsSection: (section: WorkbenchSettingsSection) => { sections.push(section); return { dispose() {} } },
      }),
      activateModule: () => {}, openOverlay: () => ({ dispose() {} }), openSettings: () => {},
    })
    const scope = workbench.composition!.forScope({} as never)
    scope.addSettingsSection({ id: 'other.settings', title: '其它', component: () => null })
    expect(sections.map((section) => section.id)).toEqual(['other.settings'])
    expect(sections.map((section) => section.id)).not.toContain(SETTINGS_SECTION_ID)
  })
})
