// Composer IME and panel boundary checks remain. The retired input-ticket send
// path is unsupported until Chat receives a managed-input owner.
// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'

vi.mock('streamdown', () => ({ Streamdown: (props: { children?: string }) => <div>{props.children}</div> }))
vi.mock('shiki', () => ({ createHighlighter: () => { throw new Error('shiki must not load in unit tests') } }))

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
window.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} }
window.matchMedia = (query: string) => ({ matches: false, media: query, onchange: null, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {}, dispatchEvent: () => true })

import { FacadeFixture } from './facade-fixture'
import { ChatPage } from '../src/views/chat-page'
import { createChatContributions } from '@extensions/ordessa.chat-api/contract.js'

const roots = new Map<HTMLElement, ReturnType<typeof createRoot>>()
const cleanup: (() => Promise<void>)[] = []
afterEach(async () => { for (const fn of cleanup.splice(0).reverse()) await fn(); vi.restoreAllMocks() })
async function mount(element: React.ReactNode) {
  const container = document.createElement('div')
  document.body.append(container)
  const root = createRoot(container)
  roots.set(container, root)
  cleanup.push(async () => { await act(async () => root.unmount()); roots.delete(container); container.remove() })
  await act(async () => { root.render(element) })
  return container
}
const input = (container: ParentNode) => container.querySelector<HTMLTextAreaElement>('[data-testid="chat-input"]')!
const tick = () => new Promise(resolve => setTimeout(resolve, 0))
const session = () => new FacadeFixture({ sessions: [{ id: 's1', title: '会话一' }], selectedSessionId: 's1', messages: { s1: [] } })
const page = (facade: FacadeFixture) => <ChatPage service={facade} chat={createChatContributions()} theme="light" />
async function type(container: HTMLElement, value: string) {
  const area = input(container)
  await act(async () => {
    // React's value tracker dedupes plain assignments; use the native setter.
    const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!
    setter.call(area, value)
    area.dispatchEvent(new Event('input', { bubbles: true }))
  })
}
async function pressEnter(container: HTMLElement, init: KeyboardEventInit = {}) {
  const area = input(container)
  await act(async () => { area.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true, ...init })) })
}
/** Real typing flow for the slash panel: the keyup after the input event
 * re-syncs the token against the freshly rendered text (seams.test.tsx). */
async function syncSlashToken(container: HTMLElement) {
  await act(async () => {
    input(container).dispatchEvent(new KeyboardEvent('keyup', { bubbles: true }))
    await tick()
  })
}

describe('managed-input and composer boundaries', () => {
  it('IME confirmation does not submit; the next Enter refuses before a gateway and preserves text', async () => {
    const facade = session()
    const chat = createChatContributions()
    const submit = vi.spyOn(chat, 'submit')
    const container = await mount(<ChatPage service={facade} chat={chat} theme="light" />)
    await type(container, '中文候选')
    const area = input(container)
    await act(async () => { area.dispatchEvent(new Event('compositionstart', { bubbles: true })) })
    await act(async () => { area.dispatchEvent(new Event('compositionend', { bubbles: true })) })
    await pressEnter(container, { keyCode: 229 })
    expect(facade.sends).toEqual([])
    expect(input(container).value).toBe('中文候选')
    expect(container.querySelector('[data-testid=chat-send-error]')).toBeNull()
    await pressEnter(container)
    expect(submit).not.toHaveBeenCalled()
    expect(facade.sends).toEqual([])
    expect(input(container).value).toBe('中文候选')
    expect(container.querySelector('[data-testid=chat-send-error]')?.textContent).toContain('managed-input 端口尚未接通')
  })
// Counterexample requested by T009-06. The named `onTriggerDisappear` seam
// does NOT exist (UNKNOWN); what exists is observable: losing the slash token
// closes the panel and the composer regains focus as a valid target.
  it('observable substitute: losing the slash token closes the panel and focus returns to the live composer (onTriggerDisappear seam UNKNOWN)', async () => {
    const facade = session()
    const container = await mount(page(facade))
    await type(container, '/co')
    await syncSlashToken(container)
    expect(container.querySelector('[data-testid="chat-input-panel"]')).not.toBeNull()
    expect(document.activeElement).not.toBe(input(container))

    const area = input(container)
    await act(async () => {
      area.setSelectionRange(0, 0)
      area.dispatchEvent(new Event('select', { bubbles: true }))
      // keyup is the event that reports the caret against the fresh render
      // (seams.test.tsx); select alone does not re-sync in jsdom.
      area.dispatchEvent(new KeyboardEvent('keyup', { key: 'ArrowLeft', bubbles: true }))
      area.dispatchEvent(new Event('selectionchange', { bubbles: true }))
    })
    expect(container.querySelector('[data-testid="chat-input-panel"]')).toBeNull()
    expect(document.activeElement).toBe(area) // valid focus target, never body
    expect(input(container).value).toBe('/co')
    expect(facade.sends).toEqual([])
  })

  // Missing-condition probe: the observable half of "Esc only consumes one
  // layer". Chat consumes Escape exactly when its own panel is the top layer;
  // with no panel open Chat does not touch the event, leaving the global layer
  // (workbench overlay stack) to act. That global half is not mountable in this
  // suite → UNKNOWN here.
  it('Escape consumes exactly the open panel layer once; with no panel Chat leaves the event to the global layer', async () => {
    const facade = session()
    const container = await mount(page(facade))
    await type(container, '/co')
    await syncSlashToken(container)
    expect(container.querySelector('[data-testid="chat-input-panel"]')).not.toBeNull()

    const first = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })
    await act(async () => { input(container).dispatchEvent(first) })
    expect(first.defaultPrevented).toBe(true) // this layer consumed it
    expect(container.querySelector('[data-testid="chat-input-panel"]')).toBeNull()
    expect(input(container).value).toBe('/co')

    const second = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })
    await act(async () => { input(container).dispatchEvent(second) })
    expect(second.defaultPrevented).toBe(false) // the global layer is untouched by Chat
    expect(facade.sends).toEqual([])
  })
})
