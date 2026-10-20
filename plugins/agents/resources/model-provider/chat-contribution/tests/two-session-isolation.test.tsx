// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, expect, it, vi } from 'vitest'
import { CanonicalModelSelector } from '../src/canonical-selector'
import type { ModelProviderService } from '../../contracts/index'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
const roots: ReturnType<typeof createRoot>[] = []
afterEach(async () => { for (const root of roots.splice(0)) await act(async () => root.unmount()); document.body.replaceChildren() })

const configs = [
  { id: 'pi-provider', version: 1, displayName: 'Pi provider', harness: 'pi', provider: 'fixture', credentialId: null,
    models: [{ modelId: 'pi-model', availability: 'available', unavailableReason: null }], archivedAt: null,
    managedBy: 'harness', state: 'saved', provenance: null, createdAt: 't', updatedAt: 't' },
  { id: 'codex-provider', version: 1, displayName: 'Codex provider', harness: 'codex', provider: 'fixture', credentialId: null,
    models: [{ modelId: 'codex-model', availability: 'available', unavailableReason: null }], archivedAt: null,
    managedBy: 'harness', state: 'saved', provenance: null, createdAt: 't', updatedAt: 't' },
]

it('keeps independent Harness resource views while neither session can dispatch a saved choice', async () => {
  const service = { list: async () => configs } as unknown as ModelProviderService
  const container = document.createElement('div'); document.body.append(container)
  const root = createRoot(container); roots.push(root)
  const view = (sessionId: string, harnessId: string) => <CanonicalModelSelector wiring={{ service }} location={{
    kind: 'session', sessionId, harnessId, connectionId: `c-${sessionId}`, serverInstanceId: `s-${sessionId}`,
  } as never} />
  await act(async () => root.render(view('session-a', 'pi')))
  await act(async () => container.querySelector<HTMLElement>('[data-testid="model-selector-trigger"]')!.click())
  const pi = await vi.waitFor(() => {
    const found = document.body.querySelector<HTMLElement>('[data-testid="model-option-pi-provider-pi-model"]')
    expect(found).not.toBeNull()
    return found!
  })
  expect(pi.getAttribute('aria-disabled')).toBe('true')
  expect(document.body.querySelector('[data-testid="model-option-codex-provider-codex-model"]')).toBeNull()

  await act(async () => root.render(view('session-b', 'codex')))
  const codex = await vi.waitFor(() => {
    const found = document.body.querySelector<HTMLElement>('[data-testid="model-option-codex-provider-codex-model"]')
    expect(found).not.toBeNull()
    return found!
  })
  expect(codex.getAttribute('aria-disabled')).toBe('true')
  expect(document.body.querySelector('[data-testid="model-option-pi-provider-pi-model"]')).toBeNull()
  expect(container.textContent).not.toContain('session-a')
  expect(container.textContent).not.toContain('session-b')
  await act(async () => codex.click())
  expect(container.textContent).not.toContain('下轮使用')
})
