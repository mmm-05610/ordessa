// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, expect, it } from 'vitest'
import { CanonicalModelSelector } from '../src/canonical-selector'
import type { ModelProviderService, ProviderConfigView } from '../../contracts/index'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
const roots: ReturnType<typeof createRoot>[] = []
afterEach(async () => { for (const root of roots.splice(0)) await act(async () => root.unmount()); document.body.replaceChildren() })

const configs: ProviderConfigView[] = [
  { id: 'p-pi', version: 1, displayName: 'Pi models', harness: 'pi', provider: 'fixture', credentialId: null,
    models: [{ modelId: 'm-pi', displayName: 'Pi model', availability: 'available', unavailableReason: null }],
    archivedAt: null, managedBy: 'harness', state: 'saved', provenance: null, createdAt: 't', updatedAt: 't' },
  { id: 'p-codex', version: 1, displayName: 'Codex models', harness: 'codex', provider: 'fixture', credentialId: null,
    models: [{ modelId: 'm-codex', displayName: 'Codex model', availability: 'available', unavailableReason: null }],
    archivedAt: null, managedBy: 'harness', state: 'saved', provenance: null, createdAt: 't', updatedAt: 't' },
]

it('filters each display by its Harness and never sends native session identity to an application route', async () => {
  const service = { list: async () => configs } as unknown as ModelProviderService
  const container = document.createElement('div'); document.body.append(container)
  const root = createRoot(container); roots.push(root)
  await act(async () => root.render(<>
    <CanonicalModelSelector wiring={{ service }} location={{ kind: 'session', sessionId: 'private-a',
      connectionId: 'c1', serverInstanceId: 's1', harnessId: 'pi' } as never} />
    <CanonicalModelSelector wiring={{ service }} location={{ kind: 'session', sessionId: 'private-b',
      connectionId: 'c2', serverInstanceId: 's2', harnessId: 'codex' } as never} />
  </>))
  const triggers = container.querySelectorAll('[data-testid="model-selector-trigger"]')
  expect(triggers).toHaveLength(2)
  await act(async () => { (triggers[0] as HTMLElement).click(); (triggers[1] as HTMLElement).click() })
  await act(async () => undefined)
  expect(document.body.textContent).toContain('Pi models')
  expect(document.body.textContent).toContain('Codex models')
  expect(document.body.querySelector('[data-testid="model-option-p-pi-m-pi"]')?.getAttribute('aria-disabled')).toBe('true')
  expect(document.body.querySelector('[data-testid="model-option-p-codex-m-codex"]')?.getAttribute('aria-disabled')).toBe('true')
  expect(container.textContent).not.toContain('private-a')
  expect(container.textContent).not.toContain('private-b')
})
