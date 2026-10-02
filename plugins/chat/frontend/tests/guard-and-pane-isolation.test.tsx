// N2.3 / N2.4 on the Chat surface: a configuration route (Profile / model)
// that answers unknown or refused must not lose the user's work, must not
// re-send, must not clear the composer queue, and must never leak across the
// pane the user is actually in.
//
// The guard here is a CONTROLLED stand-in for those two routes — the model and
// Profile submissions are composed in their own packages; what is asserted
// below is Chat's own behaviour when such a route blocks or drops a send.
// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { createHash } from 'node:crypto'
import { afterEach, expect, it, vi } from 'vitest'

vi.mock('streamdown', () => ({ Streamdown: (props: { children?: string }) => <div>{props.children}</div> }))
vi.mock('shiki', () => ({ createHighlighter: () => { throw new Error('shiki must not load in unit tests') } }))

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
window.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} }
window.matchMedia = (query: string) => ({ matches: false, media: query, onchange: null, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {}, dispatchEvent: () => true })

import { FacadeFixture } from './facade-fixture'
import { createAttachmentSource } from '../src/adapters/agent'
import { ChatPage } from '../src/views/chat-page'
import { createChatContributions, type ChatSubmissionGuard } from '@extensions/ordessa.chat-api/contract.js'
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
const text = (container: ParentNode, selector: string) => container.querySelector(selector)?.textContent ?? ''
const input = (container: ParentNode) => container.querySelector<HTMLTextAreaElement>('[data-testid="chat-input"]')!
const tick = () => new Promise(resolve => setTimeout(resolve, 0))
const CONTENT = 'controlled attachment bytes'
const sha256 = (content: string) => createHash('sha256').update(content).digest('hex')
/** A real prepared attachment: the composer queue the blocked send must keep. */
function withReadyAttachment(facade: FacadeFixture) {
  facade.attachmentPrepare = async () => ({ kind: 'prepared' as const,
    reference: { preparedId: 'p-1', name: 'a.txt', uri: 'acp://prepared/p-1', mimeType: 'text/plain',
      sha256: sha256(CONTENT), byteLength: CONTENT.length } })
}
async function type(container: HTMLElement, value: string) {
  const area = input(container)
  await act(async () => {
    const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!
    setter.call(area, value)
    area.dispatchEvent(new Event('input', { bubbles: true }))
  })
}
/** Caret movement is ordinary editing: it must never look like a send. */
async function moveCaret(container: HTMLElement, position: number) {
  await act(async () => {
    const area = input(container)
    area.setSelectionRange(position, position)
    area.dispatchEvent(new Event('select', { bubbles: true }))
    area.dispatchEvent(new KeyboardEvent('keyup', { key: 'ArrowLeft', bubbles: true }))
    area.dispatchEvent(new Event('selectionchange', { bubbles: true }))
  })
}
async function pressEnter(container: HTMLElement, init: KeyboardEventInit = {}) {
  const area = input(container)
  await act(async () => { area.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true, ...init })) })
}
async function clickSend(container: HTMLElement) {
  await act(async () => { container.querySelector<HTMLButtonElement>('[data-testid="chat-send"]')!.click() })
}
const twoSessions = () => new FacadeFixture({
  sessions: [{ id: 's1', title: '会话一' }, { id: 's2', title: '会话二' }],
  selectedSessionId: 's1', messages: { s1: [], s2: [] },
})
/** Chat plus the two composer configuration routes, in the real registry. */
function page(facade: FacadeFixture, guards: ChatSubmissionGuard[] = [], withAttachments = false) {
  const chat = createChatContributions()
  const ui = chat.forScope({ isDisposed: false, add: (d: { dispose(): void }) => d } as never)
  if (withAttachments)
    ui.addInputSource(createAttachmentSource(facade, { pick: async () => ({ sourceId: 'content-1', name: 'a.txt' }) }))
  for (const guard of guards) ui.addSubmissionGuard(guard)
  return <ChatPage service={facade} chat={chat} theme="light" />
}
async function addAttachment(container: HTMLElement) {
  await act(async () => { container.querySelector<HTMLButtonElement>('[data-testid="chat-plus-button"]')!.click() })
  await act(async () => { await tick() })
  await act(async () => { container.querySelector<HTMLButtonElement>('[data-entry-id="attachments:add"]')!.click() })
  await act(async () => { await tick(); await tick() })
}

it('N2.4h an unknown configuration route keeps the draft and the prepared queue, and editing neither resends nor clears it', async () => {
  const facade = twoSessions()
  withReadyAttachment(facade)
  const guard = { id: 'controlled.route', order: 1,
    prepare: vi.fn(async () => ({ status: 'unknown' as const })) } satisfies ChatSubmissionGuard
  const container = await mount(page(facade, [guard], true))
  await addAttachment(container)
  await type(container, '结果未知的草稿')
  await clickSend(container)
  await act(async () => { await tick() })

  const warning = container.querySelector('[data-testid="chat-send-error"]')!
  expect(guard.prepare).toHaveBeenCalledTimes(1)
  expect(facade.sends).toEqual([]) // zero prompt
  expect(text(container, '[data-testid="chat-send-error"]')).toContain('未知')
  expect(container.querySelector('[data-testid="chat-attachments"] [data-phase="ready"]')).not.toBeNull()
  // the draft itself survived the blocked send, untouched
  expect(input(container).value).toBe('结果未知的草稿')

  // ordinary editing — typing, caret moves, IME Enter — changes nothing
  for (const [index, value] of ['结果未知的草稿一', '结果未知的草稿二'].entries()) {
    await type(container, value)
    await moveCaret(container, index + 1)
    await pressEnter(container, { keyCode: 229 })
    expect(container.querySelector('[data-testid="chat-send-error"]')).toBe(warning) // no flicker
    expect(text(container, '[data-testid="chat-send-error"]')).toContain('未知')
  }
  expect(guard.prepare).toHaveBeenCalledTimes(1) // no silent retry
  expect(facade.sends).toEqual([]) // no duplicate send
  expect(input(container).value).toBe('结果未知的草稿二')
  // the composer queue was never emptied or auto-cleaned
  expect(container.querySelector('[data-testid="chat-attachments"] [data-phase="ready"]')).not.toBeNull()
  expect(facade.releasedRefs).toEqual([])
})

it('N2.4i a refused configuration route keeps the draft and the queue, and shows a stable named reason', async () => {
  const facade = twoSessions()
  withReadyAttachment(facade)
  const guard = { id: 'controlled.route', order: 1,
    prepare: vi.fn(async () => ({ status: 'refused' as const, reason: '所选预设属于另一 Harness' })) } satisfies ChatSubmissionGuard
  const container = await mount(page(facade, [guard], true))
  await addAttachment(container)
  await type(container, '被拒绝的草稿')
  await clickSend(container)

  const warning = container.querySelector('[data-testid="chat-send-error"]')!
  expect(text(container, '[data-testid="chat-send-error"]')).toContain('所选预设属于另一 Harness')
  expect(facade.sends).toEqual([])
  expect(input(container).value).toBe('被拒绝的草稿')
  await type(container, '被拒绝的草稿 续写')
  await moveCaret(container, 3)
  expect(container.querySelector('[data-testid="chat-send-error"]')).toBe(warning)
  expect(guard.prepare).toHaveBeenCalledTimes(1)
  expect(facade.sends).toEqual([])
  expect(input(container).value).toBe('被拒绝的草稿 续写')
  expect(container.querySelector('[data-testid="chat-attachments"] [data-phase="ready"]')).not.toBeNull()
  expect(facade.releasedRefs).toEqual([])
})

it('N2.3j an answer that arrives after the pane switch touches nothing in the pane now shown', async () => {
  const facade = twoSessions()
  facade.selectionRevision = 1
  let release!: () => void
  const guard = { id: 'controlled.route', order: 1,
    prepare: () => new Promise(resolve => { release = () => resolve({ status: 'unknown' as const }) }) } satisfies ChatSubmissionGuard
  const container = await mount(page(facade, [guard]))
  await type(container, '会话一里的草稿')
  await clickSend(container)
  await act(async () => { await tick() })

  // leave pane A while its configuration answer is still outstanding
  await act(async () => { facade.selectSession('s2') })
  await type(container, '会话二里的草稿')
  await act(async () => { release() })
  await act(async () => { await tick() })

  expect(container.querySelector('[data-testid="chat-send-error"]')).toBeNull() // A's answer is not B's
  expect(input(container).value).toBe('会话二里的草稿')
  expect(facade.sends).toEqual([])

  // and A's own draft is still exactly as the user left it
  await act(async () => { facade.selectSession('s1') })
  expect(input(container).value).toBe('会话一里的草稿')
  expect(facade.sends).toEqual([])
})

it('N2.3k alternating panes keep each draft and each send independent', async () => {
  const facade = twoSessions()
  const seen: string[] = []
  const guard = { id: 'controlled.route', order: 1, prepare: async () => {
    const pane = facade.getSnapshot().agent?.selectedSessionId
    seen.push(String(pane))
    return pane === 's2' ? { status: 'unknown' as const } : { status: 'ready' as const }
  } } satisfies ChatSubmissionGuard
  const container = await mount(page(facade, [guard]))
  await type(container, 'A 的第一版')
  await clickSend(container)
  expect(facade.sends).toEqual(['A 的第一版'])

  await act(async () => { facade.selectSession('s2') })
  await type(container, 'B 的草稿')
  await clickSend(container)
  expect(facade.sends).toEqual(['A 的第一版']) // B was blocked, nothing sent for it
  expect(text(container, '[data-testid="chat-send-error"]')).toContain('未知')
  expect(input(container).value).toBe('B 的草稿')

  // each pane keeps only its OWN draft: A's accepted send cleared A's composer
  // and left B's blocked draft exactly as the user typed it
  await act(async () => { facade.selectSession('s1') })
  expect(input(container).value).toBe('')
  await type(container, 'A 的第二版')
  await act(async () => { facade.selectSession('s2') })
  expect(input(container).value).toBe('B 的草稿')
  expect(text(container, '[data-testid="chat-send-error"]')).toContain('未知')
  await act(async () => { facade.selectSession('s1') })
  expect(input(container).value).toBe('A 的第二版')
  // nothing was sent on A's behalf either — B's blocked send stays blocked
  expect(facade.sends).toEqual(['A 的第一版'])
  expect(seen).toEqual(['s1', 's2'])
})

it('N2.2e ordinary typing and caret movement never invoke a configuration route', async () => {
  const facade = twoSessions()
  const guard = { id: 'controlled.route', order: 1,
    prepare: vi.fn(async () => ({ status: 'ready' as const })) } satisfies ChatSubmissionGuard
  const container = await mount(page(facade, [guard]))
  for (const value of ['一', '一二', '一二三', '一二三四']) {
    await type(container, value)
    await moveCaret(container, 0)
    await pressEnter(container, { keyCode: 229 })
  }
  expect(guard.prepare).not.toHaveBeenCalled()
  expect(facade.sends).toEqual([])
  expect(input(container).value).toBe('一二三四')
})
