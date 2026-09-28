// @vitest-environment jsdom
// T033 — action guard reporting and unmount safety (contract §4/§5; U12/U13):
// swallowed throws/rejections become generic refused results with sanitized
// diagnostics that never carry props, `accepted` is never reinterpreted, and
// accepted work survives the outlet going away without any state write-back
// or lifecycle call into caller-provided handles. Fixtures: `example.card`.
import { act, useState, type ReactNode } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { OwnedResources } from '@ordessa/extension-api'
import {
  defineUiComponent,
  type UiAction,
  type UiActionResult,
  type UiBinding,
} from '../api/ui-components'
import { createUiComponentsService } from '../src/index'
import { ComponentOutlet, guardUiAction, UI_ACTION_FAILURE_MESSAGE, type UiPlatformDiagnostic } from '../react/index'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const SECRET = 'ZEXTRA-SECRET-7c11'
const CARD = 'example.card'

interface CardProps { readonly note: string }
const cardKey = defineUiComponent<CardProps>(CARD, 1)
const OkCard = ({ note }: CardProps) => <p data-card="true">{note}</p>

const cleanups: Array<() => void | Promise<void>> = []
afterEach(async () => {
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

function readyBinding(): UiBinding<CardProps> {
  const svc = createUiComponentsService([{ componentId: CARD, major: 1, providerId: 'provider-a' }])
  cleanups.push(() => svc.dispose())
  const ui = svc.uiComponents.forScope(new OwnedResources())
  ui.register({ key: cardKey, providerId: 'provider-a', component: OkCard })
  return ui.bind(cardKey, { required: true })
}

function flattenConsole(consoleSpy: ReturnType<typeof vi.spyOn>): string {
  return consoleSpy.mock.calls
    .map((call: readonly unknown[]) => call.map((part: unknown) => (typeof part === 'string' ? part : JSON.stringify(part))).join(' '))
    .join('\n')
}

describe('U12 action failure reporting', () => {
  it('U12 a synchronously throwing business action is refused with a generic display message and sanitized diagnostics that carry no input values', async () => {
    const binding = readyBinding()
    const seen: UiPlatformDiagnostic[] = []
    const business = vi.fn((input: Record<string, unknown>) => {
      void input
      throw new Error('sync-boom')
    }) as unknown as UiAction<Record<string, unknown>> & ReturnType<typeof vi.fn>
    const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    const guarded = guardUiAction(binding, business, { onDiagnostics: d => seen.push(d) })
    const result = await guarded({ payload: SECRET })
    expect(result).toEqual({ status: 'refused', message: UI_ACTION_FAILURE_MESSAGE })
    expect(business).toHaveBeenCalledTimes(1)
    expect(seen).toHaveLength(1)
    expect(seen[0]).toMatchObject({
      kind: 'ui-action-failed', code: 'UI_ACTION_FAILED',
      componentId: CARD, major: 1, providerId: 'provider-a', generation: 1, message: 'sync-boom',
    })
    expect(JSON.stringify(seen[0])).not.toContain(SECRET)
    expect(flattenConsole(consoleSpy)).not.toContain(SECRET)
  })

  it('U12 a rejecting business promise is refused the same way, and a business self-reported refusal passes through unchanged', async () => {
    const binding = readyBinding()
    const seen: UiPlatformDiagnostic[] = []
    const rejecting: UiAction<string> = (input: string) => Promise.reject(new Error(`async-boom ${input.length}`))
    const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    const guarded = guardUiAction(binding, rejecting, { onDiagnostics: d => seen.push(d) })
    const result = await guarded(SECRET)
    expect(result).toEqual({ status: 'refused', message: UI_ACTION_FAILURE_MESSAGE })
    expect(seen).toHaveLength(1)
    // The rejection message was built from the input length, not the input:
    // even a leak-shaped cause stays a short sanitised summary.
    expect(seen[0].message).toBe('async-boom 18')
    expect(JSON.stringify(seen[0])).not.toContain(SECRET)
    expect(flattenConsole(consoleSpy)).not.toContain(SECRET)

    // Business-originated refusals are display-safe by contract and must not
    // be rewritten by this layer.
    const own: UiAction<string> = async () => ({ status: 'refused', message: '业务拒绝了该输入' })
    const ownGuarded = guardUiAction(binding, own, { onDiagnostics: d => seen.push(d) })
    expect(await ownGuarded('x')).toEqual({ status: 'refused', message: '业务拒绝了该输入' })
    expect(seen).toHaveLength(1) // no diagnostic for a clean business refusal
  })

  it('U12 an accepted result is passed through with no extra fields, no logs and no completion wording from this layer', async () => {
    const binding = readyBinding()
    const seen: UiPlatformDiagnostic[] = []
    const business: UiAction<string> = async () => ({ status: 'accepted' })
    const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    const guarded = guardUiAction(binding, business, { onDiagnostics: d => seen.push(d) })
    const result = await guarded('anything')
    expect(result).toEqual({ status: 'accepted' })
    expect(Object.keys(result)).toEqual(['status'])
    expect(seen).toHaveLength(0)
    expect(flattenConsole(consoleSpy)).toBe('')
  })
})

describe('U13 unmount safety of accepted work', () => {
  it('U13 accepted async work survives outlet unmount, writes no state into unmounted UI, keeps the consumer draft, and never calls close/stop/release', async () => {
    const store: { completed: string } = { completed: '' }
    const business: UiAction<string> = (input: string) => {
      // The operation was accepted; the real work continues on its own clock.
      setTimeout(() => { store.completed = `done:${input}` }, 20)
      return Promise.resolve({ status: 'accepted' })
    }
    const binding = readyBinding()
    const guarded = guardUiAction(binding, business)

    const close = vi.fn()
    const stop = vi.fn()
    const release = vi.fn()

    function Host(props: { watched: UiBinding<CardProps>; lifecycle: { close: () => void; stop: () => void; release: () => void } }): ReactNode {
      const [show, setShow] = useState(true)
      const [draft] = useState('draft-keep-me')
      const value: CardProps & typeof props.lifecycle = { note: draft, ...props.lifecycle }
      return (
        <div>
          <span data-draft="true">{draft}</span>
          <button type="button" data-toggle="true" onClick={() => setShow(current => !current)}>toggle</button>
          {show
            ? <ComponentOutlet binding={props.watched} value={value} />
            : null}
        </div>
      )
    }

    const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    const container = await mount(<Host watched={binding} lifecycle={{ close, stop, release }} />)
    expect(container.querySelector('[data-card]')?.textContent).toBe('draft-keep-me')

    let result: UiActionResult | undefined
    await act(async () => { result = await guarded('work-order-1') })
    expect(result).toEqual({ status: 'accepted' })
    expect(store.completed).toBe('') // accepted is not completion

    // The view goes away while the accepted work is still running.
    await act(async () => { container.querySelector<HTMLButtonElement>('[data-toggle]')!.click() })
    expect(container.querySelector('[data-card]')).toBeNull()
    expect(container.querySelector('[data-draft]')?.textContent).toBe('draft-keep-me')

    // Accepted work is not cancelled by the unmount.
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 40)) })
    expect(store.completed).toBe('done:work-order-1')

    // No lifecycle call into the handles the consumer passed via props.
    expect(close).not.toHaveBeenCalled()
    expect(stop).not.toHaveBeenCalled()
    expect(release).not.toHaveBeenCalled()
    // The binding itself is consumer/scope-owned: unmounting UI never revokes it.
    expect(binding.getSnapshot().status).toBe('ready')

    // Nothing wrote state into the unmounted tree: React would have logged a
    // warning mentioning "unmounted" had this layer attempted it.
    expect(flattenConsole(consoleSpy).toLowerCase()).not.toContain('unmounted')
  })
})
