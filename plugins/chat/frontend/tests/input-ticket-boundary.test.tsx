// T009-06 (verification half): composer/input-panel boundary semantics that the
// existing Chat implementation already carries, pinned before the surface
// input-ticket work lands.
//
// Contract references:
//   specs/026-open-environment-migration/contracts/frontend.md §F1
//     SurfaceAPI write(inputTicket); WorkbenchAPI "Esc 只处理顶层可关闭面"
//   specs/026-open-environment-migration/contracts/lifecycle-evidence.md
//     (late results only through owner revalidation; old generation callbacks
//     cannot withdraw new scope)
//   specs/026-open-environment-migration/orders/009.md T009-06
//     "编辑与 surface input ticket 绑定 target/epoch/lease，输入法 composition
//      尾 Enter 不发送；global Esc 只消费一层，触发器消失返回有效焦点"
//
// Pinned here (existing behaviour, no product change):
//   (a) IME composition tail Enter (compositionend → keyCode 229) never sends;
//   (b) a late accepted ack after an explicit epoch round-trip does not write
//       into the newer input of the same pane;
//   (c) duplicate Enter keydowns cannot double-send (single-flight pending pane);
//   target binding: the submission snapshot freezes the captured ChatLocation
//       (connection/session/contextRevision) before any guard or gateway sees it.
//
// DRIFT/UNKNOWN registered honestly (no fake green):
//   - Chat has no surface input-ticket type with target/epoch/lease; the
//     submission snapshot plus the isCurrent epoch recheck is the closest
//     existing semantics. A real lease concept has NO implementation (UNKNOWN).
//   - no onTriggerDisappear seam exists in the composer/panel; the observable
//     substitute (losing the slash token closes the panel and focus returns to
//     the composer) is pinned, the named seam stays UNKNOWN.
//   - the workbench global overlay Esc stack is not mounted here (no
//     alias/config for it in this suite); this file pins only Chat's own
//     single-layer consumption. Cross-shell "global Esc closes exactly one
//     layer" stays UNKNOWN here (workbench composition tests own the LIFO
//     stack).
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
import { createChatContributions, type ChatSubmissionGuard, type ChatSubmissionSnapshot } from '@extensions/ordessa.chat-api/contract.js'
import { OwnedResources } from '@ordessa/extension-api'

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
async function clickSend(container: HTMLElement) {
  await act(async () => { container.querySelector<HTMLButtonElement>('[data-testid="chat-send"]')!.click() })
}
/** Real typing flow for the slash panel: the keyup after the input event
 * re-syncs the token against the freshly rendered text (seams.test.tsx). */
async function syncSlashToken(container: HTMLElement) {
  await act(async () => {
    input(container).dispatchEvent(new KeyboardEvent('keyup', { bubbles: true }))
    await tick()
  })
}

describe('T009-06 composer input ticket boundary', () => {
  it('IME composition tail Enter (compositionend → keyCode 229) never sends; the next real Enter sends exactly once', async () => {
    const facade = session()
    const container = await mount(page(facade))
    await type(container, '中文候选')
    const area = input(container)
    await act(async () => { area.dispatchEvent(new Event('compositionstart', { bubbles: true })) })
    await act(async () => { area.dispatchEvent(new Event('compositionend', { bubbles: true })) })
    // Desktop IMEs end composition before the confirming Enter; Chromium still
    // marks that key with the 229 sentinel.
    await pressEnter(container, { keyCode: 229 })
    expect(facade.sends).toEqual([])
    expect(input(container).value).toBe('中文候选')
    expect(container.querySelector('[data-testid=chat-send-error]')).toBeNull()
    // The sentinel blocks only the confirming key: the next real Enter sends.
    await pressEnter(container)
    expect(facade.sends).toEqual(['中文候选'])
    expect(input(container).value).toBe('')
  })

  it('the submission ticket freezes the captured target (connection/session/contextRevision) before guard and gateway', async () => {
    const facade = session()
    const chat = createChatContributions(), scope = new OwnedResources()
    cleanup.push(async () => scope.dispose())
    const seen: ChatSubmissionSnapshot[] = []
    chat.forScope(scope).addSubmissionGuard({ id: 'capture.ticket', order: 1,
      prepare: async snapshot => { seen.push(snapshot); return { status: 'ready' } } } satisfies ChatSubmissionGuard)
    const container = await mount(<ChatPage service={facade} chat={chat} theme="light" />)
    await act(async () => { facade.emit() }) // one notification → contextRevision 1
    await type(container, '冻结目标')
    await clickSend(container)

    expect(seen).toHaveLength(1)
    const snapshot = seen[0]
    expect(snapshot.target).toEqual({ kind: 'session', connectionId: 'conn-1', sessionId: 's1', contextRevision: 1 })
    // The captured ticket cannot be mutated by later navigation.
    expect(Object.isFrozen(snapshot)).toBe(true)
    expect(Object.isFrozen(snapshot.target)).toBe(true)
    expect(snapshot.text).toBe('冻结目标')
    expect(snapshot.draftRevision).toBeGreaterThanOrEqual(1)
    expect(facade.sends).toEqual(['冻结目标'])
  })

  it('a repeated Enter while the send is pending sends once (single-flight pending pane)', async () => {
    const facade = session()
    let release!: () => void
    facade.sendBehavior = () => new Promise<void>(resolve => { release = resolve })
    const container = await mount(page(facade))
    await type(container, '只发一次')
    const area = input(container)
    // Two separate event tasks, like a user key repeat. (Two programmatic
    // dispatches inside ONE act() coalesce React state and would double-send;
    // that is a test-harness artifact of act, not a reachable browser path.)
    await pressEnter(container)
    expect(facade.sends).toEqual(['只发一次'])
    expect(container.querySelector('[data-testid="chat-send-pending"]')).not.toBeNull()
    await pressEnter(container)
    expect(facade.sends).toEqual(['只发一次'])
    await act(async () => { release() })
    expect(input(container).value).toBe('')
  })

  it('a late accepted ack after an epoch round-trip does not overwrite the newer input in the same pane', async () => {
    const facade = session()
    facade.selectionRevision = 1 // explicit navigation epoch
    let release!: () => void
    facade.sendBehavior = () => new Promise<void>(resolve => { release = resolve })
    const container = await mount(page(facade))
    await type(container, 'epoch A 已发送')
    await clickSend(container)
    await act(async () => { await tick() })
    expect(facade.sends).toEqual(['epoch A 已发送'])

    // Epoch moves away and back while the ack is still outstanding, then the
    // user writes a new input in the same pane.
    await act(async () => { facade.selectSession('s2') })
    await type(container, 'B 的草稿')
    await act(async () => { facade.selectSession('s1') })
    await type(container, 'epoch A 的新输入')
    await act(async () => { release() })
    await act(async () => { await tick() })

    // The stale ack belonged to the old epoch: it wrote nothing into the new input.
    expect(input(container).value).toBe('epoch A 的新输入')
    expect(container.querySelector('[data-testid=chat-send-error]')).toBeNull()
    expect(facade.sends).toEqual(['epoch A 已发送'])
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
