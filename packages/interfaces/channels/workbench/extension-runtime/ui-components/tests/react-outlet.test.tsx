// @vitest-environment jsdom
// T033 — React Outlet layer over the T032 core: revocation window, generation
// remounting and absence semantics (contract §4 last paragraph, §5; U09/U10).
// Fixtures are generic: `example.card`, `provider-a`.
import { act, useEffect, type ReactNode } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { OwnedResources } from '@ordessa/extension-api'
import {
  defineUiComponent,
  type UiActionResult,
  type UiBinding,
  type UiComponentKey,
} from '../api/ui-components'
import { createUiComponentsService, type UiComponentsService } from '../src/index'
import { ComponentOutlet, guardUiAction, guardUiCallback, useUiBinding } from '../react/index'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

interface CardProps { readonly id: string }
const CARD = 'example.card'

/** One key object per module is fine: identity checks are per-service, never global. */
const cardKey: UiComponentKey<CardProps> = defineUiComponent<CardProps>(CARD, 1)

const cleanups: Array<() => void | Promise<void>> = []
afterEach(async () => {
  for (const fn of cleanups.splice(0).reverse()) await fn()
  vi.restoreAllMocks()
})

async function mount(element: ReactNode): Promise<{ container: HTMLElement; rerender: (el: ReactNode) => Promise<void> }> {
  const container = document.createElement('div')
  document.body.append(container)
  const root = createRoot(container)
  cleanups.push(async () => { await act(async () => root.unmount()); container.remove() })
  await act(async () => root.render(element))
  return { container, rerender: async (el: ReactNode) => { await act(async () => root.render(el)) } }
}

function service(): UiComponentsService {
  const svc = createUiComponentsService([{ componentId: CARD, major: 1, providerId: 'provider-a' }])
  cleanups.push(() => svc.dispose())
  return svc
}

const OkCard = ({ id }: CardProps) => <p data-card="true">{id}</p>

describe('U09 revocation window and generation remount at the outlet', () => {
  it('U09 a guarded action captured before provider unload makes zero business calls while React has not yet committed the DOM removal, and same-id re-activation does not resurrect it', async () => {
    const svc = service()
    const ui = svc.uiComponents.forScope(new OwnedResources())
    const binding = ui.bind(cardKey, { required: true })
    let handle = ui.register({ key: cardKey, providerId: 'provider-a', component: OkCard })
    const business = vi.fn(async (_input: string): Promise<UiActionResult> => ({ status: 'accepted' }))
    const guarded = guardUiAction(binding, business)
    const { container } = await mount(<ComponentOutlet binding={binding} value={{ id: 'shown' }} />)
    expect(container.querySelector('[data-card]')?.textContent).toBe('shown')

    let result: UiActionResult | undefined
    await act(async () => {
      handle.dispose()
      // The registry revokes synchronously, but this assertion proves React
      // has NOT committed the DOM removal yet — the guarded call lands inside
      // exactly that window.
      expect(container.querySelector('[data-card]')).not.toBeNull()
      result = await guarded('payload')
    })
    expect(result).toEqual({ status: 'unavailable' })
    expect(business).not.toHaveBeenCalled()
    // After the commit the stale DOM is gone.
    expect(container.querySelector('[data-card]')).toBeNull()

    // Re-activation with the same provider id yields a new generation; the
    // old guarded action must not revive.
    await act(async () => { handle = ui.register({ key: cardKey, providerId: 'provider-a', component: OkCard }) })
    expect(container.querySelector('[data-card]')?.textContent).toBe('shown')
    await act(async () => { result = await guarded('payload') })
    expect(result).toEqual({ status: 'unavailable' })
    expect(business).not.toHaveBeenCalled()

    // A fresh action under the new generation works: the binding itself is
    // alive; only the old fixed generation is dead.
    const freshGuarded = guardUiAction(binding, business)
    await act(async () => { result = await freshGuarded('payload') })
    expect(result).toEqual({ status: 'accepted' })
    expect(business).toHaveBeenCalledTimes(1)
  })

  it('U09 guardUiCallback created while missing never runs, and an old-generation callback does not run after re-activation', async () => {
    const svc = service()
    const ui = svc.uiComponents.forScope(new OwnedResources())
    const binding = ui.bind(cardKey, { required: false })
    const callback = vi.fn()

    const createdMissing = guardUiCallback(binding, callback)
    let handle = ui.register({ key: cardKey, providerId: 'provider-a', component: OkCard })
    createdMissing()
    expect(callback).not.toHaveBeenCalled()

    const createdReady = guardUiCallback(binding, callback)
    createdReady()
    expect(callback).toHaveBeenCalledTimes(1)

    handle.dispose()
    handle = ui.register({ key: cardKey, providerId: 'provider-a', component: OkCard })
    createdReady()
    expect(callback).toHaveBeenCalledTimes(1) // new generation did not revive the old callback

    const newest = guardUiCallback(binding, callback)
    newest('a', 1)
    expect(callback).toHaveBeenCalledTimes(2)
    expect(callback).toHaveBeenLastCalledWith('a', 1)
    handle.dispose()
    newest('b', 2)
    expect(callback).toHaveBeenCalledTimes(2) // revoked again -> zero further calls
  })

  it('U09 the outlet remounts the implementation subtree when a new generation arrives and keeps instance identity within one generation', async () => {
    let mounts = 0
    let unmounts = 0
    const CountingCard = ({ id }: CardProps) => {
      useEffect(() => { mounts += 1; return () => { unmounts += 1 } }, [])
      return <p data-card="true">{id}</p>
    }
    const svc = service()
    const ui = svc.uiComponents.forScope(new OwnedResources())
    const binding = ui.bind(cardKey, { required: true })
    const handle = ui.register({ key: cardKey, providerId: 'provider-a', component: CountingCard })
    const { container, rerender } = await mount(<ComponentOutlet binding={binding} value={{ id: 'v1' }} />)
    expect(mounts).toBe(1)
    expect(binding.getSnapshot().status).toBe('ready')
    const generation1 = (binding.getSnapshot() as { generation: number }).generation

    // Same generation, new value: the instance keeps its identity (no remount).
    await rerender(<ComponentOutlet binding={binding} value={{ id: 'v2' }} />)
    expect(container.querySelector('[data-card]')?.textContent).toBe('v2')
    expect(mounts).toBe(1)
    expect(unmounts).toBe(0)

    // Replacement (revoke then re-register) is a new generation -> full remount.
    await act(async () => {
      handle.dispose()
      ui.register({ key: cardKey, providerId: 'provider-a', component: CountingCard })
    })
    const generation2 = (binding.getSnapshot() as { generation: number }).generation
    expect(generation2).toBeGreaterThan(generation1)
    expect(mounts).toBe(2)
    expect(unmounts).toBe(1)
  })
})

describe('U10 absence semantics at the outlet', () => {
  it('U10 optional missing hides the position entirely: no placeholder node is left in the DOM', async () => {
    const svc = service()
    const ui = svc.uiComponents.forScope(new OwnedResources())
    const binding = ui.bind(cardKey, { required: false })
    const { container } = await mount(
      <span data-anchor="true"><ComponentOutlet binding={binding} value={{ id: 'opt' }} /></span>,
    )
    expect(container.innerHTML).toBe('<span data-anchor="true"></span>')
    // Optional absence is a state, not a requirement violation.
    expect(svc.inspectRequirements()).toEqual([])
    // It is not permanently hidden: publishing the provider renders it.
    await act(async () => { ui.register({ key: cardKey, providerId: 'provider-a', component: OkCard }) })
    expect(container.querySelector('[data-card]')?.textContent).toBe('opt')
  })

  it('U10 required missing shows an understandable generic prompt, is listed by inspectRequirements, and an explicit missing node overrides it', async () => {
    const svc = service()
    const ui = svc.uiComponents.forScope(new OwnedResources())
    const binding = ui.bind(cardKey, { required: true })
    const { container, rerender } = await mount(<ComponentOutlet binding={binding} value={{ id: 'req' }} />)
    const prompt = container.querySelector('[data-ui-outlet-missing]')
    expect(prompt).not.toBeNull()
    expect(prompt!.getAttribute('role')).toBe('alert')
    expect(prompt!.textContent!.length).toBeGreaterThan(0)
    expect(svc.inspectRequirements()).toEqual([
      { componentId: CARD, major: 1, selectedProviderId: 'provider-a', reason: 'provider-unavailable' },
    ])
    await rerender(<ComponentOutlet binding={binding} value={{ id: 'req' }} missing={<b data-ov="true">custom-absence</b>} />)
    expect(container.querySelector('[data-ui-outlet-missing]')).toBeNull()
    expect(container.querySelector('[data-ov]')?.textContent).toBe('custom-absence')
  })

  it('U10 an implementation that exists but throws is shown as an error at its position, never as absence', async () => {
    const Boom = (_props: CardProps): never => { throw new Error('boom-render') }
    const svc = service()
    const ui = svc.uiComponents.forScope(new OwnedResources())
    const binding = ui.bind(cardKey, { required: true })
    await act(async () => { ui.register({ key: cardKey, providerId: 'provider-a', component: Boom }) })
    const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    const { container } = await mount(<ComponentOutlet binding={binding} value={{ id: 'boom' }} />)
    // The state itself stayed 'ready' — a throwing implementation is not absence.
    expect(binding.getSnapshot()).toEqual({ status: 'ready', providerId: 'provider-a', generation: 1 })
    expect(container.querySelector('[data-ui-outlet-missing]')).toBeNull()
    expect(container.querySelector('[data-ui-outlet-error]')).not.toBeNull()
    expect(container.querySelector('[data-ui-outlet-error]')?.getAttribute('role')).toBe('alert')
    expect(container.querySelector('[data-ui-outlet-retry]')).not.toBeNull()
    // Still not a requirement violation for the product diagnostics either.
    expect(svc.inspectRequirements()).toEqual([])
    const ours = consoleSpy.mock.calls.filter(call => call[0] === '[ordessa.ui-components]')
    expect(ours).toHaveLength(1)
    expect(ours[0][1]).toMatchObject({
      kind: 'ui-render-failed', code: 'UI_RENDER_FAILED',
      componentId: CARD, major: 1, providerId: 'provider-a', generation: 1, message: 'boom-render',
    })
  })
})

describe('useUiBinding outside the outlet', () => {
  it('U10 useUiBinding exposes the live availability snapshot to consumers that render no outlet', async () => {
    const svc = service()
    const ui = svc.uiComponents.forScope(new OwnedResources())
    const binding = ui.bind(cardKey, { required: false })
    function Watcher({ watched }: { watched: UiBinding<CardProps> }) {
      const availability = useUiBinding(watched)
      return <span data-availability="true">{availability.status === 'ready' ? `ready:${availability.generation}` : availability.status}</span>
    }
    const { container } = await mount(<Watcher watched={binding} />)
    expect(container.querySelector('[data-availability]')?.textContent).toBe('missing')
    await act(async () => { ui.register({ key: cardKey, providerId: 'provider-a', component: OkCard }) })
    expect(container.querySelector('[data-availability]')?.textContent).toBe('ready:1')
    await act(async () => { binding.dispose() })
    expect(container.querySelector('[data-availability]')?.textContent).toBe('disposed')
  })
})
