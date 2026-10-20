// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, expect, it, vi } from 'vitest'
import { CanonicalModelSelector } from '../src/canonical-selector'
import type { ModelProviderService } from '../../contracts/index'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
const roots: ReturnType<typeof createRoot>[] = []
afterEach(async () => { for (const root of roots.splice(0)) await act(async () => root.unmount()); document.body.replaceChildren() })

const location = { kind: 'session' as const, connectionId: 'conn', serverInstanceId: 'srv',
  sessionId: 'native', harnessId: 'pi', contextRevision: 0 }
const config = { id: 'p', version: 7, displayName: 'Fixture', harness: 'pi', archivedAt: null,
  models: [{ modelId: 'm', availability: 'available' }] }

async function mount(service: ModelProviderService) {
  const container = document.createElement('div'); document.body.append(container)
  const root = createRoot(container); roots.push(root)
  await act(async () => root.render(<CanonicalModelSelector wiring={{ service }} location={location} />))
  return container
}

it('reads Provider resources but keeps each model unsupported and emits no configuration call', async () => {
  const service = { list: vi.fn(async () => [config]) } as unknown as ModelProviderService
  const container = await mount(service)
  await act(async () => container.querySelector<HTMLElement>('[data-testid="model-selector-trigger"]')!.click())
  const option = await vi.waitFor(() => {
    const found = document.body.querySelector<HTMLElement>('[data-testid="model-option-p-m"]')
    expect(found).not.toBeNull()
    return found!
  })
  expect(service.list).toHaveBeenCalledOnce()
  expect(option.getAttribute('aria-disabled')).toBe('true')
  expect(option.textContent).toContain('真实 NodeRef')
  await act(async () => option.click())
  expect(container.textContent).not.toContain('下轮使用')
})

it('distinguishes an unreadable resource catalog from an empty catalog', async () => {
  const serviceStub = { list: vi.fn(async () => { throw new Error('provider catalog unavailable') }) }
  const service = serviceStub as unknown as ModelProviderService
  const container = await mount(service)
  await act(async () => container.querySelector<HTMLElement>('[data-testid="model-selector-trigger"]')!.click())
  await vi.waitFor(() => expect(document.body.textContent).toContain('provider catalog unavailable'))
  expect(document.body.querySelector('[data-testid="model-load-retry"]')).not.toBeNull()
})
