// @vitest-environment jsdom
// T033 — per-position error boundary (contract §5; U11): a render failure
// stays at its position, recovery is explicit-retry or new-generation only,
// and there is no automatic retry loop. Fixtures: `example.zone`, provider-a.
import { act, type ReactNode } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { OwnedResources } from '@ordessa/extension-api'
import { defineUiComponent, type UiBinding } from '../api/ui-components'
import { createUiComponentsService, type UiComponentsService } from '../src/index'
import { ComponentOutlet } from '../react/index'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

interface ZoneProps { readonly zone: string }
const ZONE = 'example.zone'
const zoneKey = defineUiComponent<ZoneProps>(ZONE, 1)

/** Positions in this set throw during render; the test flips membership. */
const throwing = new Set<string>()
const renderCounts: Record<string, number> = {}

const ZoneCard = ({ zone }: ZoneProps) => {
  renderCounts[zone] = (renderCounts[zone] ?? 0) + 1
  if (throwing.has(zone)) throw new Error('boom-render')
  return <p data-zone={zone}>{zone} content</p>
}

const cleanups: Array<() => void | Promise<void>> = []
afterEach(async () => {
  throwing.clear()
  for (const key of Object.keys(renderCounts)) delete renderCounts[key]
  for (const fn of cleanups.splice(0).reverse()) await fn()
  vi.restoreAllMocks()
})

async function mount(element: ReactNode): Promise<HTMLElement> {
  const container = document.createElement('div')
  document.body.append(container)
  const root = createRoot(container)
  cleanups.push(async () => { await act(async () => root.unmount()); container.remove() })
  await act(async () => root.render(element))
  return container
}

/** One service with the shared ZoneCard provider and one required binding. */
function fixture(): { svc: UiComponentsService; binding: UiBinding<ZoneProps>; registerAgain: () => void; revoke: () => void } {
  const svc = createUiComponentsService([{ componentId: ZONE, major: 1, providerId: 'provider-a' }])
  cleanups.push(() => svc.dispose())
  const ui = svc.uiComponents.forScope(new OwnedResources())
  const binding = ui.bind(zoneKey, { required: true })
  let handle = ui.register({ key: zoneKey, providerId: 'provider-a', component: ZoneCard })
  return {
    svc,
    binding,
    revoke: () => { handle.dispose() },
    registerAgain: () => { handle = ui.register({ key: zoneKey, providerId: 'provider-a', component: ZoneCard }) },
  }
}

function twoPositions(binding: UiBinding<ZoneProps>) {
  return (
    <div>
      <ComponentOutlet binding={binding} value={{ zone: 'zone-a' }} />
      <ComponentOutlet binding={binding} value={{ zone: 'zone-b' }} />
    </div>
  )
}

async function clickRetry(container: HTMLElement, position: 'first' | 'last' = 'first'): Promise<void> {
  const buttons = container.querySelectorAll<HTMLButtonElement>('[data-ui-outlet-retry]')
  const button = position === 'first' ? buttons[0] : buttons[buttons.length - 1]
  expect(button, 'retry affordance present').toBeTruthy()
  await act(async () => { button.click() })
}

describe('U11 per-position error containment and recovery', () => {
  it('U11 a render error in position A shows only at position A while the same provider keeps rendering fine at position B', async () => {
    throwing.add('zone-a')
    const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    const { binding } = fixture()
    const container = await mount(twoPositions(binding))
    expect(container.querySelectorAll('[data-ui-outlet-error]')).toHaveLength(1)
    expect(container.querySelector('[data-ui-outlet-error]')?.getAttribute('role')).toBe('alert')
    expect(container.querySelector('[data-zone="zone-b"]')?.textContent).toBe('zone-b content')
    expect(container.querySelector('[data-zone="zone-a"]')).toBeNull()
    // The failure is reported once with the generic render code, props-free.
    const ours = consoleSpy.mock.calls.filter(call => call[0] === '[ordessa.ui-components]')
    expect(ours).toHaveLength(1)
    expect(JSON.stringify(ours[0][1])).not.toContain('zone-a') // the diagnostic carries ids only, never the props value
    expect(ours[0][1]).toMatchObject({ code: 'UI_RENDER_FAILED', componentId: ZONE, major: 1, providerId: 'provider-a' })
  })

  it('U11 no automatic retry loop: the failing implementation is called a bounded number of times and never re-invoked without user action', async () => {
    throwing.add('zone-a')
    vi.spyOn(console, 'error').mockImplementation(() => {})
    const { binding } = fixture()
    const container = await mount(twoPositions(binding))
    const initial = renderCounts['zone-a']
    expect(initial).toBeGreaterThanOrEqual(1)
    // A failing render is internally replayed once by React before the
    // boundary settles; what must NOT happen is any further growth over time.
    // Let any queued work run: without a click nothing re-renders the implementation.
    for (let round = 0; round < 3; round += 1) {
      await act(async () => { await new Promise(resolve => setTimeout(resolve, 10)) })
    }
    expect(renderCounts['zone-a']).toBe(initial)
    expect(container.querySelectorAll('[data-ui-outlet-error]')).toHaveLength(1)
  })

  it('U11 explicit retry is the only same-generation recovery: one click, one fresh attempt; recovery keeps the same generation', async () => {
    throwing.add('zone-a')
    vi.spyOn(console, 'error').mockImplementation(() => {})
    const { binding } = fixture()
    const container = await mount(twoPositions(binding))
    const generation = (binding.getSnapshot() as { generation: number }).generation

    // Retry while still failing: one bounded fresh attempt (React replays a
    // failing render once internally, so a single attempt costs up to 2 calls),
    // still showing the error.
    const before = renderCounts['zone-a']
    await clickRetry(container)
    const afterClick = renderCounts['zone-a']
    expect(afterClick).toBeGreaterThan(before)
    expect(afterClick - before).toBeLessThanOrEqual(4)
    expect(container.querySelectorAll('[data-ui-outlet-error]')).toHaveLength(1)
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 10)) })
    expect(renderCounts['zone-a']).toBe(afterClick) // no cascading auto attempts

    // Retry once the implementation works again: recovered, same generation.
    throwing.delete('zone-a')
    await clickRetry(container)
    expect(container.querySelector('[data-zone="zone-a"]')?.textContent).toBe('zone-a content')
    expect((binding.getSnapshot() as { generation: number }).generation).toBe(generation)
    expect(container.querySelectorAll('[data-ui-outlet-error]')).toHaveLength(0)
  })

  it('U11 a new generation clears the position error automatically without any click', async () => {
    throwing.add('zone-a')
    vi.spyOn(console, 'error').mockImplementation(() => {})
    const { binding, revoke, registerAgain } = fixture()
    const container = await mount(twoPositions(binding))
    expect(container.querySelectorAll('[data-ui-outlet-error]')).toHaveLength(1)
    const generationBefore = (binding.getSnapshot() as { generation: number }).generation

    // Replacement under the same provider id (fixed selection) after the fix.
    await act(async () => {
      throwing.delete('zone-a')
      revoke()
      registerAgain()
    })
    expect((binding.getSnapshot() as { generation: number }).generation).toBeGreaterThan(generationBefore)
    expect(container.querySelectorAll('[data-ui-outlet-error]')).toHaveLength(0)
    expect(container.querySelector('[data-zone="zone-a"]')?.textContent).toBe('zone-a content')
    expect(container.querySelector('[data-zone="zone-b"]')?.textContent).toBe('zone-b content')
  })
})
