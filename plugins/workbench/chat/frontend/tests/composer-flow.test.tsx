// Composer/display behavior remains active. Agent submission is explicitly
// unsupported until a managed-input port is composed; draft gates still apply.
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

describe('unselected product landing', () => {
  it('opens the project dialog from the connected empty Chat without creating a session', async () => {
    const facade = new FacadeFixture({ workspaceSupport: 'supported', workspaces: [] })
    const create = vi.spyOn(facade, 'newSession')
    const send = vi.spyOn(facade, 'send')
    const container = await mount(<ChatPage service={facade} chat={createChatContributions()} />)
    await act(async () => container.querySelector<HTMLButtonElement>('[data-testid=chat-new-session-empty]')!.click())
    expect(container.querySelector('[role=dialog]')).not.toBeNull()
    expect(container.textContent).toContain('选择项目')
    expect(create).not.toHaveBeenCalled()
    expect(send).not.toHaveBeenCalled()
  })
  it('offers observed connectors directly; failed selection is visible and never creates or sends', async () => {
    const facade = new FacadeFixture()
    const snapshot = { ...facade.getSnapshot(), selectedConnectionId: undefined, agent: undefined,
      available: [{ id: 'acp:observed', title: 'ACP · Test harness' }] }
    vi.spyOn(facade, 'getSnapshot').mockReturnValue(snapshot)
    const select = vi.spyOn(facade, 'selectConnection').mockRejectedValue(new Error('Connection refused'))
    const send = vi.spyOn(facade, 'send')
    const create = vi.spyOn(facade, 'newSession')
    const container = await mount(<ChatPage service={facade} chat={createChatContributions()} />)
    const button = container.querySelector<HTMLButtonElement>('[data-chat-connector="acp:observed"]')!
    expect(button.textContent).toBe('ACP · Test harness')
    expect(select).not.toHaveBeenCalled()
    await act(async () => button.click())
    expect(select).toHaveBeenCalledWith('acp:observed')
    expect(container.querySelector('[role=alert]')?.textContent).toBe('Connection refused')
    expect(send).not.toHaveBeenCalled()
    expect(create).not.toHaveBeenCalled()
  })
})

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
function page(facade: FacadeFixture) {
  return <ChatPage service={facade} chat={createChatContributions()} theme="light" />
}

describe('composer input (US3/C04)', () => {
  it('keeps the editor above a compact action row and outside the message scroller', async () => {
    const facade = new FacadeFixture({ sessions: [{ id: 's1', title: '会话一' }], selectedSessionId: 's1', messages: { s1: [] } })
    const container = await mount(page(facade))
    const compose = container.querySelector('[data-testid="chat-compose"]')!
    const card = compose.querySelector('.chat-composer-card')!
    const row = card.querySelector('.chat-composer-bottom')!
    expect(card.firstElementChild?.contains(input(container))).toBe(true)
    expect(row.contains(container.querySelector('[data-testid="chat-plus-button"]'))).toBe(true)
    expect(row.contains(container.querySelector('[data-testid="chat-compose-toolbar"]'))).toBe(true)
    expect(row.contains(container.querySelector('[data-testid="chat-send"]'))).toBe(true)
    expect(container.querySelector('[data-testid="chat-thread"]')?.contains(compose)).toBe(false)
    await type(container, '保留输入')
    expect(input(container).value).toBe('保留输入')
    expect(facade.sends).toEqual([])
  })
  it('dismisses the anchored add menu on an outside pointer without losing draft text', async () => {
    const facade = new FacadeFixture({ sessions: [{ id: 's1', title: '会话一' }], selectedSessionId: 's1', messages: { s1: [] } })
    const container = await mount(page(facade))
    await type(container, '菜单不能清空我')
    await act(async () => container.querySelector<HTMLButtonElement>('[data-testid="chat-plus-button"]')!.click())
    expect(container.querySelector('[data-testid="chat-input-panel"]')).not.toBeNull()
    await act(async () => container.querySelector('.chat-page-head')!.dispatchEvent(new Event('pointerdown', { bubbles: true })))
    expect(container.querySelector('[data-testid="chat-input-panel"]')).toBeNull()
    expect(input(container).value).toBe('菜单不能清空我')
    expect(facade.sends).toEqual([])
  })
  it('returns focus from add-menu search to the live composer after Escape without clearing text', async () => {
    const facade = new FacadeFixture({ sessions: [{ id: 's1', title: '会话一' }], selectedSessionId: 's1', messages: { s1: [] } })
    const container = await mount(page(facade))
    await type(container, '关闭菜单后继续输入')
    await act(async () => container.querySelector<HTMLButtonElement>('[data-testid="chat-plus-button"]')!.click())
    const search = container.querySelector<HTMLInputElement>('[data-testid="chat-panel-search"]')!
    expect(document.activeElement).toBe(search)
    await act(async () => search.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })))
    expect(container.querySelector('[data-testid="chat-input-panel"]')).toBeNull()
    expect(document.activeElement).toBe(input(container))
    expect(input(container).value).toBe('关闭菜单后继续输入')
    expect(facade.sends).toEqual([])
  })
  it('does not restore an old menu focus into a different session pane', async () => {
    const facade = new FacadeFixture({ sessions: [{ id: 's1', title: '一' }, { id: 's2', title: '二' }], selectedSessionId: 's1', messages: { s1: [], s2: [] } })
    const container = await mount(page(facade))
    await act(async () => container.querySelector<HTMLButtonElement>('[data-testid="chat-plus-button"]')!.click())
    await act(async () => facade.selectSession('s2'))
    const search = container.querySelector<HTMLInputElement>('[data-testid="chat-panel-search"]')!
    await act(async () => search.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })))
    expect(container.querySelector('[data-testid="chat-input-panel"]')).toBeNull()
    expect(document.activeElement).not.toBe(input(container))
    expect(facade.sends).toEqual([])
  })
  it('Enter reports unsupported and preserves the draft; Shift+Enter and IME Enter do not submit', async () => {
    const facade = new FacadeFixture({ sessions: [{ id: 's1', title: '会话一' }], selectedSessionId: 's1', messages: { s1: [] } })
    const container = await mount(page(facade))
    await type(container, '保留的草稿')
    await pressEnter(container)
    expect(facade.sends).toEqual([])
    expect(input(container).value).toBe('保留的草稿')
    expect(container.querySelector('[data-testid=chat-send-error]')?.textContent)
      .toContain('managed-input 端口尚未接通')
    await pressEnter(container, { shiftKey: true })
    const area = input(container)
    await act(async () => { area.dispatchEvent(new Event('compositionstart', { bubbles: true })) })
    await pressEnter(container)
    await act(async () => { area.dispatchEvent(new Event('compositionend', { bubbles: true })) })
    expect(facade.sends).toEqual([])
    expect(input(container).value).toBe('保留的草稿')
  })
  it('does not send when an IME confirms with keyCode 229 after composition ends', async () => {
    const facade = new FacadeFixture({ sessions: [{ id: 's1', title: '会话一' }], selectedSessionId: 's1', messages: { s1: [] } })
    const container = await mount(page(facade))
    await type(container, '中文候选')
    await pressEnter(container, { keyCode: 229 })
    expect(facade.sends).toHaveLength(0)
    expect(input(container).value).toBe('中文候选')
    expect(container.querySelector('[data-testid=chat-send-error]')).toBeNull()
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
