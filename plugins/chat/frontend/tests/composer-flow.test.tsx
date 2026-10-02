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
import { OwnedResources } from '@ordessa/extension-api'

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
async function clickSend(container: HTMLElement) {
  const button = container.querySelector<HTMLButtonElement>('[data-testid="chat-send"]')!
  await act(async () => { button.click() })
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

describe('send flow (C04/A04/unknown)', () => {
  it('native preparation notifications preserve admission with an unchanged explicit navigation epoch', async () => {
    const facade = new FacadeFixture({ sessions: [{ id: 's1', title: '会话一' }], selectedSessionId: 's1', messages: { s1: [] } })
    facade.selectionRevision = 1
    const chat = createChatContributions(), scope = new OwnedResources()
    cleanup.push(async () => scope.dispose())
    chat.forScope(scope).addSubmissionGuard({ id: 'native.progress', order: 1, prepare: async () => {
      facade.emit()
      return { status: 'ready' }
    } })
    const container = await mount(<ChatPage service={facade} chat={chat} theme="light" />)
    await type(container, 'prepared text')
    await clickSend(container)
    expect(facade.sends).toEqual(['prepared text'])
  })

  it('an explicit navigation epoch prevents sending after moving away and back during preparation', async () => {
    const facade = new FacadeFixture({ sessions: [{ id: 's1', title: '一' }, { id: 's2', title: '二' }], selectedSessionId: 's1', messages: { s1: [], s2: [] } })
    facade.selectionRevision = 1
    const chat = createChatContributions(), scope = new OwnedResources()
    cleanup.push(async () => scope.dispose())
    let release!: () => void
    chat.forScope(scope).addSubmissionGuard({ id: 'native.held', order: 1,
      prepare: () => new Promise(resolve => { release = () => resolve({ status: 'ready' }) }) })
    const container = await mount(<ChatPage service={facade} chat={chat} theme="light" />)
    await type(container, 'keep text')
    await clickSend(container)
    await act(async () => { facade.selectSession('s2'); facade.selectSession('s1'); release() })
    expect(facade.sends).toEqual([])
    expect(input(container).value).toBe('keep text')
  })

  it('submission guards refuse before the real facade send and preserve the draft', async () => {
    const facade = new FacadeFixture({ sessions: [{ id: 's1', title: '会话一' }], selectedSessionId: 's1', messages: { s1: [] } })
    const chat = createChatContributions()
    const scope = new OwnedResources()
    cleanup.push(async () => scope.dispose())
    const prepare = vi.fn(async () => ({ status: 'refused' as const, reason: '配置准备被拒' }))
    chat.forScope(scope).addSubmissionGuard({ id: 'controlled.guard', order: 1, prepare })
    const container = await mount(<ChatPage service={facade} chat={chat} theme="light" />)
    await type(container, '需要准备的草稿')
    await clickSend(container)
    expect(prepare).toHaveBeenCalledTimes(1)
    expect(facade.sends).toEqual([])
    expect(input(container).value).toBe('需要准备的草稿')
    expect(text(container, '[data-testid="chat-send-error"]')).toContain('配置准备被拒')
  })

  it('switching panes while preparation awaits prevents any gateway send, including switching back', async () => {
    const facade = new FacadeFixture({ sessions: [{ id: 's1', title: '会话一' }, { id: 's2', title: '会话二' }], selectedSessionId: 's1', messages: { s1: [], s2: [] } })
    const chat = createChatContributions()
    const scope = new OwnedResources()
    cleanup.push(async () => scope.dispose())
    let release!: () => void
    chat.forScope(scope).addSubmissionGuard({ id: 'controlled.guard', order: 1,
      prepare: () => new Promise(resolve => { release = () => resolve({ status: 'ready' }) }) })
    const container = await mount(<ChatPage service={facade} chat={chat} theme="light" />)
    await type(container, 'A草稿')
    await clickSend(container)
    await act(async () => { facade.selectSession('s2') })
    await type(container, 'B草稿')
    await act(async () => { release() })
    expect(facade.sends).toEqual([])
    expect(input(container).value).toBe('B草稿')
    await act(async () => { facade.selectSession('s1') })
    expect(input(container).value).toBe('A草稿')
    // Even returning to the original pane before prepare settles is stale.
    await clickSend(container)
    await act(async () => { facade.selectSession('s2'); facade.selectSession('s1'); release() })
    expect(facade.sends).toEqual([])
    expect(input(container).value).toBe('A草稿')
  })

  it('Enter while output is running invokes neither preparation nor the send gateway', async () => {
    const facade = new FacadeFixture({ sessions: [{ id: 's1', title: '会话一' }], selectedSessionId: 's1', messages: { s1: [] }, run: { id: 'run-1', sessionId: 's1', status: 'running' } })
    const chat = createChatContributions()
    const scope = new OwnedResources()
    cleanup.push(async () => scope.dispose())
    const prepare = vi.fn(async () => ({ status: 'ready' as const }))
    chat.forScope(scope).addSubmissionGuard({ id: 'controlled.guard', order: 1, prepare })
    const container = await mount(<ChatPage service={facade} chat={chat} theme="light" />)
    await type(container, '下轮草稿')
    await pressEnter(container)
    expect(prepare).not.toHaveBeenCalled()
    expect(facade.sends).toEqual([])
    expect(input(container).value).toBe('下轮草稿')
    expect(container.querySelector('[data-testid="chat-stop"]')).not.toBeNull()
  })
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
    // Facade semantics since contracts 0.2.0: the facade itself decides the
    // outcome is undecidable (evidenced channel loss) and says so — the UI
    // never guesses.
    facade.sendBehavior = async () => {
      facade.setConnectionStatus('disconnected')
      return { kind: 'unknown', operationId: 'op-1', reason: 'connection lost' }
    }
    const container = await mount(page(facade))
    await type(container, '结果不明的消息')
    await clickSend(container)
    expect(input(container).value).toBe('结果不明的消息')
    expect(text(container, '[data-testid="chat-send-error"]')).toContain('未知')
    expect(text(container, '[data-testid="chat-send-error"]')).toContain('请核实状态')
    expect(text(container, '[data-testid="chat-send-error"]')).not.toContain('连接可能')
    expect(facade.sends).toHaveLength(1) // no automatic resend
  })
  it('keeps an unknown warning stable while editing and confirming IME candidates, without another send', async () => {
    const facade = new FacadeFixture({ sessions: [{ id: 's1', title: '会话一' }], selectedSessionId: 's1', messages: { s1: [] } })
    facade.sendBehavior = async () => ({ kind: 'unknown', operationId: 'op-1', reason: 'unobserved configuration' })
    const container = await mount(page(facade))
    await type(container, '未确认草稿')
    await clickSend(container)
    const warning = container.querySelector('[data-testid=chat-send-error]')!
    expect(warning.textContent).toContain('未知')
    for (const value of ['未确认草稿一', '未确认草稿二']) {
      await type(container, value)
      await pressEnter(container, { keyCode: 229 })
      expect(container.querySelector('[data-testid=chat-send-error]')).toBe(warning)
      expect(facade.sends).toHaveLength(1)
    }
    expect(input(container).value).toBe('未确认草稿二')
  })
  it('successful configuration preparation does not turn an unknown gateway outcome into acceptance', async () => {
    const facade = new FacadeFixture({ sessions: [{ id: 's1', title: '会话一' }], selectedSessionId: 's1', messages: { s1: [] } })
    const chat = createChatContributions(), scope = new OwnedResources()
    cleanup.push(async () => scope.dispose())
    const prepare = vi.fn(async () => ({ status: 'ready' as const }))
    chat.forScope(scope).addSubmissionGuard({ id: 'controlled.configuration', order: 1, prepare })
    facade.sendBehavior = async () => ({ kind: 'unknown', operationId: 'op-after-ready', reason: 'outcome not observed' })
    const container = await mount(<ChatPage service={facade} chat={chat} theme="light" />)
    await type(container, '配置成功仍不能丢掉我')
    await clickSend(container)
    expect(prepare).toHaveBeenCalledTimes(1)
    expect(facade.sends).toEqual(['配置成功仍不能丢掉我'])
    expect(input(container).value).toBe('配置成功仍不能丢掉我')
    expect(text(container, '[data-testid="chat-send-error"]')).toContain('未知')
    expect(container.querySelector('[data-testid="chat-send-pending"]')).toBeNull()
    expect(facade.getSnapshot().agent?.connection.status).toBe('connected')
    await act(async () => { facade.emit() })
    expect(prepare).toHaveBeenCalledTimes(1)
    expect(facade.sends).toHaveLength(1)
    expect(input(container).value).toBe('配置成功仍不能丢掉我')
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
