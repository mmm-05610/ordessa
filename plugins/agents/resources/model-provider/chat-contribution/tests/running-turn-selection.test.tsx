// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, expect, it, vi } from 'vitest'
import { CanonicalModelSelector } from '../src/canonical-selector'
import type { ModelProviderService } from '../../contracts/index'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
const roots: ReturnType<typeof createRoot>[] = []
afterEach(async () => { for (const root of roots.splice(0)) await act(async () => root.unmount()); document.body.replaceChildren() })

it.each(['running', 'starting', 'stop-requested'])(
  'during a %s turn the visible resource list remains read-only and no interrupt or application route exists',
  async status => {
    const serviceStub = { list: vi.fn(async () => [{ id: 'p', version: 1, displayName: 'P', harness: 'pi',
      provider: 'fixture', credentialId: null,
      models: [{ modelId: 'm', displayName: 'M', availability: 'available', unavailableReason: null }],
      archivedAt: null, managedBy: 'harness', state: 'saved', provenance: null, createdAt: 't', updatedAt: 't' }]) }
    const service = serviceStub as unknown as ModelProviderService
    const container = document.createElement('div'); document.body.append(container)
    const root = createRoot(container); roots.push(root)
    await act(async () => root.render(<CanonicalModelSelector wiring={{ service }} location={{
      kind: 'session', sessionId: 'native', connectionId: 'c', serverInstanceId: 's', harnessId: 'pi', runStatus: status,
    } as never} />))
    await act(async () => container.querySelector<HTMLElement>('[data-testid="model-selector-trigger"]')!.click())
    await vi.waitFor(() => expect(document.body.querySelector('[data-testid="model-option-p-m"]')).not.toBeNull())
    const option = document.body.querySelector('[data-testid="model-option-p-m"]')!
    expect(option.getAttribute('aria-disabled')).toBe('true')
    expect(service.list).toHaveBeenCalledOnce()
    expect(container.textContent).not.toContain('下轮使用')
  },
)
