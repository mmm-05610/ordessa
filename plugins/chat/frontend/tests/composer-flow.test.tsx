// Composer + page flow counterexamples (spec US3, checklist 草稿/固定输入/
// 目标守卫 rows): IME Enter never submits; refused and unknown keeps the
// draft; a late accepted result never clears newer typing; a result arriving
// after a pane switch touches nothing (X05); draft block reasons gate sends.
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
const text = (container: ParentNode, selector: string) => container.querySelector(selector)?.textContent ?? ''
const input = (container: ParentNode) => container.querySelector<HTMLTextAreaElement>('[data-testid="chat-input"]')!
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
  const button = container.querySelector<HTMLButtonElement>('[data-testid="chat-send"]')!
  await act(async () => { button.click() })
}

function page(facade: FacadeFixture) {
  return <ChatPage service={facade} chat={createChatContributions()} theme="light" />
}

describe('composer input (US3/C04)', () => {
  it('Enter submits, Shift+Enter does not, IME-composing Enter does not', async () => {
    const facade = new FacadeFixture({ sessions: [{ id: 's1', title: '会话一' }], selectedSessionId: 's1', messages: { s1: [] } })
    const container = await mount(page(facade))
    await type(container, '你好')
    await pressEnter(container)
    expect(facade.sends).toEqual(['你好'])
    // draft cleared after accepted send
    expect(input(container).value).toBe('')
    // Shift+Enter: no submit
    await type(container, '第二行')
    await pressEnter(container, { shiftKey: true })
    expect(facade.sends).toHaveLength(1)
    expect(input(container).value).toBe('第二行')
    // IME composition: compositionStart then Enter must not submit
    const area = input(container)
    await act(async () => { area.dispatchEvent(new Event('compositionstart', { bubbles: true })) })
    await pressEnter(container)
    await act(async () => { area.dispatchEvent(new Event('compositionend', { bubbles: true })) })
    expect(facade.sends).toHaveLength(1)
  })
})

describe('send flow (C04/A04/unknown)', () => {
  it('a refused send keeps the draft and shows the reason', async () => {
    const facade = new FacadeFixture({ sessions: [{ id: 's1', title: '会话一' }], selectedSessionId: 's1', messages: { s1: [] } })
    facade.sendBehavior = async () => { throw new Error('项目门禁拒绝') }
    const container = await mount(page(facade))
    await type(container, '未发出的草稿')
    await clickSend(container)
    expect(input(container).value).toBe('未发出的草稿')
    expect(text(container, '[data-testid="chat-send-error"]')).toContain('项目门禁拒绝')
  })

  it('an unknown outcome (link dropped while awaiting) keeps the draft and never auto-retries', async () => {
    const facade = new FacadeFixture({ sessions: [{ id: 's1', title: '会话一' }], selectedSessionId: 's1', messages: { s1: [] } })
    facade.sendBehavior = async () => {
      facade.setConnectionStatus('disconnected')
      throw new Error('connection lost')
    }
    const container = await mount(page(facade))
    await type(container, '结果不明的消息')
    await clickSend(container)
    expect(input(container).value).toBe('结果不明的消息')
    expect(text(container, '[data-testid="chat-send-error"]')).toContain('未知')
    expect(facade.sends).toHaveLength(1) // no automatic resend
  })

  it('typing while a send is in flight is preserved by the accepted result (C04)', async () => {
    const facade = new FacadeFixture({ sessions: [{ id: 's1', title: '会话一' }], selectedSessionId: 's1', messages: { s1: [] } })
    let release: (() => void) | undefined
    facade.sendBehavior = () => new Promise<void>(resolve => { release = resolve })
    const container = await mount(page(facade))
    await type(container, '已发送的文本')
    await clickSend(container)
    // user keeps typing while pending
    await type(container, '已发送的文本 加上新的输入')
    await act(async () => { release!() })
    // only the SENT version is cleared; newer typing stays
    expect(input(container).value).toBe('已发送的文本 加上新的输入')
  })

  it('a late result after switching panes touches nothing in the new pane (X05)', async () => {
    const facade = new FacadeFixture({
      sessions: [{ id: 's1', title: '会话一' }, { id: 's2', title: '会话二' }],
      selectedSessionId: 's1',
      messages: { s1: [], s2: [] },
    })
    let release: (() => void) | undefined
    facade.sendBehavior = () => new Promise<void>(resolve => { release = resolve })
    const container = await mount(page(facade))
    await type(container, 'A 里的待发文本')
    await clickSend(container)
    // switch to session B while the send is pending
    await act(async () => { facade.selectSession('s2') })
    const bInput = input(container)
    await type(container, 'B 里的新输入')
    await act(async () => { release!() })
    // the accepted result belonged to A: B's draft must be untouched
    expect(input(container).value).toBe('B 里的新输入')
    void bInput
  })
})

describe('draft gate (US4/N05)', () => {
  it('a draft without a selected project blocks send with the named reason and zero backend calls', async () => {
    const facade = new FacadeFixture({ workspaceSupport: 'supported', workspaces: [{ id: 'w1', normalizedPath: '/repos/demo' }] })
    const container = await mount(page(facade))
    await act(async () => { facade.startDraft() })
    await type(container, '还没有项目的草稿')
    const sendButton = container.querySelector<HTMLButtonElement>('[data-testid="chat-send"]')
    expect(sendButton?.disabled).toBe(true)
    expect(text(container, '[data-testid="chat-compose-block"]')).toContain('还没有选择项目')
    expect(facade.sends).toHaveLength(0)
    // select the project: the gate opens
    await act(async () => { facade.setWorkspaceSelected('w1') })
    expect(container.querySelector<HTMLButtonElement>('[data-testid="chat-send"]')?.disabled).toBe(false)
  })

  it('an unsupported connection names the reason instead of a fake send path', async () => {
    const facade = new FacadeFixture({ workspaceSupport: 'unsupported' })
    const container = await mount(page(facade))
    await act(async () => { facade.startDraft() })
    expect(text(container, '[data-testid="chat-compose-block"]')).toContain('不支持在项目中创建会话')
  })
})
