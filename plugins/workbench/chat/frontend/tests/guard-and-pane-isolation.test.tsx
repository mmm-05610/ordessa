// Work order 006: Chat must refuse Agent submission before guards or the
// generic Chat gateway. Draft editing and owner-prepared resource state remain.
// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
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

const roots: ReturnType<typeof createRoot>[] = []
afterEach(async () => { for (const root of roots.splice(0)) await act(async () => root.unmount()); document.body.replaceChildren(); vi.restoreAllMocks() })
async function mount(element: React.ReactNode) {
  const container = document.createElement('div'); document.body.append(container)
  const root = createRoot(container); roots.push(root)
  await act(async () => root.render(element))
  return container
}
const input = (container: ParentNode) => container.querySelector<HTMLTextAreaElement>('[data-testid="chat-input"]')!
async function type(container: HTMLElement, value: string) {
  const area = input(container)
  await act(async () => {
    const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!
    setter.call(area, value)
    area.dispatchEvent(new Event('input', { bubbles: true }))
  })
}
async function clickSend(container: HTMLElement) {
  await act(async () => container.querySelector<HTMLButtonElement>('[data-testid="chat-send"]')!.click())
}
async function addAttachment(container: HTMLElement) {
  await act(async () => container.querySelector<HTMLButtonElement>('[data-testid="chat-plus-button"]')!.click())
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 0)) })
  await act(async () => container.querySelector<HTMLButtonElement>('[data-entry-id="attachments:add"]')!.click())
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 0)) })
}

it('refuses before Chat submit, registered guards, and AgentSessions.send', async () => {
  const facade = new FacadeFixture({ sessions: [{ id: 's1', title: '会话一' }], selectedSessionId: 's1', messages: { s1: [] } })
  const chat = createChatContributions(), scope = new OwnedResources()
  const guard = { id: 'controlled.guard', order: 1, prepare: vi.fn(async () => ({ status: 'ready' as const })) } satisfies ChatSubmissionGuard
  chat.forScope(scope).addSubmissionGuard(guard)
  const submit = vi.spyOn(chat, 'submit')
  const container = await mount(<ChatPage service={facade} chat={chat} theme="light" />)
  await type(container, '必须保留的草稿')
  await clickSend(container)

  expect(container.querySelector('[data-testid="chat-send-error"]')?.textContent).toContain('managed-input 端口尚未接通')
  expect(input(container).value).toBe('必须保留的草稿')
  expect(guard.prepare).not.toHaveBeenCalled()
  expect(submit).not.toHaveBeenCalled()
  expect(facade.sends).toEqual([])
  scope.dispose()
})

it('keeps prepared Assets resources in the draft when the page rejects Agent submit', async () => {
  const facade = new FacadeFixture({ sessions: [{ id: 's1', title: '会话一' }], selectedSessionId: 's1', messages: { s1: [] } })
  facade.attachmentPrepare = async () => ({ kind: 'prepared', reference: {
    preparedId: 'prepared-1', name: 'notes.txt', uri: 'acp://prepared/prepared-1', mimeType: 'text/plain',
    sha256: 'a'.repeat(64), byteLength: 12,
  } })
  const chat = createChatContributions(), scope = new OwnedResources()
  const guard = { id: 'controlled.guard', order: 1, prepare: vi.fn(async () => ({ status: 'ready' as const })) } satisfies ChatSubmissionGuard
  chat.forScope(scope).addInputSource(createAttachmentSource(facade, { pick: async () => ({ sourceId: 'content-1', name: 'notes.txt' }) }))
  chat.forScope(scope).addSubmissionGuard(guard)
  const submit = vi.spyOn(chat, 'submit')
  const container = await mount(<ChatPage service={facade} chat={chat} theme="light" />)
  await addAttachment(container)
  await type(container, '留住附件草稿')
  await clickSend(container)

  expect(container.querySelector('[data-testid="chat-attachments"] [data-phase="ready"]')).not.toBeNull()
  expect(input(container).value).toBe('留住附件草稿')
  expect(container.querySelector('[data-testid="chat-send-error"]')?.textContent).toContain('managed-input 端口尚未接通')
  expect(guard.prepare).not.toHaveBeenCalled()
  expect(submit).not.toHaveBeenCalled()
  expect(facade.sends).toEqual([])
  expect(facade.releasedRefs).toEqual([])
  scope.dispose()
})
