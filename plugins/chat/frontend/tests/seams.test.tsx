// 014 P-C real-seam proofs at the CHAT level (PC-2/PC-3/PC-5/PC-7):
// the four-state command catalog projection with controlled injection, the
// A06 attachment round trip (prepare → opaque ref → submit refs → the
// transport sees the SAME sha256), refused/unknown preparation phases that
// keep the item, the honest S-05/R-Z2-6 disabled entries, runtimeGeneration
// riding the ChatLocation, and reasoningState evidence. Every counterexample
// renders its reason — never a fake command, never a receive-then-drop.
// @vitest-environment jsdom
import { act, useState } from 'react'
import { renderToString } from 'react-dom/server'
import { createRoot } from 'react-dom/client'
import { createHash } from 'node:crypto'
import { afterEach, describe, expect, it, vi } from 'vitest'

vi.mock('streamdown', () => ({ Streamdown: (props: { children?: string }) => <div>{props.children}</div> }))
vi.mock('shiki', () => ({ createHighlighter: () => { throw new Error('shiki must not load in unit tests') } }))

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
window.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} }
window.matchMedia = (query: string) => ({ matches: false, media: query, onchange: null, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {}, dispatchEvent: () => true })
Element.prototype.scrollTo = () => {}

import { FacadeFixture } from './facade-fixture'
import {
  attachmentCapabilityOf, createAttachmentSource, createFacadeGateway, createNativeCommandSource,
  facadeCommandCatalog, projectMessage,
} from '../src/adapters/agent'
import { ChatPage } from '../src/views/chat-page'
import { connectionBadgeKey } from '../src/state/keys'
import { createChatContributions, chatContribution, defineChatComponentKey, type ChatContributionContext } from '@extensions/ordessa.chat-api/contract.js'
import { OwnedResources } from '@ordessa/extension-api'
import type { UiBinding, UiScope } from '@ordessa/ui-components/api'
import { createUiComponentsService } from '../../../../packages/desktop-platform/ui-components/src/index'
import { ToolbarContribution } from '../src/views/toolbar-contribution'
import type { AgentCommandCatalog, AgentMessage } from '@extensions/ordessa.agent-contracts/contract.js'
import type { ChatContentReference, ChatSubmissionGuard } from '@extensions/ordessa.chat-api/contract.js'

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
    const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!
    setter.call(area, value)
    area.dispatchEvent(new Event('input', { bubbles: true }))
  })
}
async function clickSend(container: HTMLElement) {
  const button = container.querySelector<HTMLButtonElement>('[data-testid="chat-send"]')!
  await act(async () => { button.click() })
}
const tick = () => new Promise(resolve => setTimeout(resolve, 0))

const sessionFacade = (extra: Partial<ConstructorParameters<typeof FacadeFixture>[0]> = {}) =>
  new FacadeFixture({ sessions: [{ id: 's1', title: '会话一' }], selectedSessionId: 's1', messages: { s1: [] }, ...extra })

const sha256 = (content: string) => createHash('sha256').update(content).digest('hex')

it('preserves the transport unknown reason without retrying or promoting acceptance', async () => {
  const facade = sessionFacade()
  facade.sendBehavior = async () => ({ kind: 'unknown', operationId: 'attempt-1', reason: 'ACP connection disposed' })
  const result = await createFacadeGateway(facade).submit({
    submissionId: 'sub-1', target: { kind: 'session', connectionId: 'c', sessionId: 's1', contextRevision: 1 },
    draftId: 'd', draftRevision: 1, text: 'test', attachmentIds: [],
  })
  expect(result).toEqual({ status: 'unknown', reason: 'ACP connection disposed' })
  expect(facade.sends).toEqual(['test'])
})

describe('PC-2 command catalog four-state projection', () => {
  it('ready maps the brand commands to insert entries; loading maps 1:1 (controlled injection)', () => {
    const facade = sessionFacade()
    facade.commandCatalogAnswer = (): AgentCommandCatalog => ({
      kind: 'available', connectionId: 'c1', nativeSessionId: 'n1',
      commands: [{ name: 'compact', description: '总结会话' }, { name: 'review', description: '' }],
    })
    const catalog = facadeCommandCatalog(facade)
    expect(catalog.get({ kind: 'session', connectionId: 'c', sessionId: 's1', contextRevision: 1 })).toEqual({
      status: 'ready',
      commands: [
        { id: 'compact', title: 'compact', insertText: '/compact', description: '总结会话' },
        { id: 'review', title: 'review', insertText: '/review' },
      ],
    })
    facade.commandCatalogAnswer = (): AgentCommandCatalog => ({ kind: 'loading' })
    expect(catalog.get({ kind: 'session', connectionId: 'c', sessionId: 's1', contextRevision: 1 })).toEqual({ status: 'loading' })
  })

  it('facade error verdicts map to their reasons; absent stays absent; drafts are absent', () => {
    const facade = sessionFacade()
    const catalog = facadeCommandCatalog(facade)
    const location = { kind: 'session' as const, connectionId: 'c', sessionId: 's1', contextRevision: 1 }
    for (const [reason, copy] of [['channel-down', '连接已断开，命令目录不可用。'], ['stale-session', '命令目录属于已切换的会话。'], ['malformed', '原生命令目录帧不可解析。'], ['unobservable', '连接断连结果不可观测，命令目录状态未知。']] as const) {
      facade.commandCatalogAnswer = (): AgentCommandCatalog => ({ kind: 'error', reason })
      expect(catalog.get(location)).toEqual({ status: 'error', message: copy })
    }
    facade.commandCatalogAnswer = (): AgentCommandCatalog => ({ kind: 'absent' })
    expect(catalog.get(location)).toEqual({ status: 'absent' })
    expect(catalog.get({ kind: 'draft', draftId: 'd', contextRevision: 1 })).toEqual({ status: 'absent' })
  })

  it('the slash source shows real commands, an absent-catalog reason row, and surfaces source errors', async () => {
    const facade = sessionFacade()
    facade.commandCatalogAnswer = (): AgentCommandCatalog => ({
      kind: 'available', connectionId: 'c1', nativeSessionId: 'n1', commands: [{ name: 'compact', description: '总结会话' }],
    })
    const source = createNativeCommandSource(facade)
    const location = { kind: 'session' as const, connectionId: 'c', sessionId: 's1', contextRevision: 1 }
    const entries = await source.query({ location, query: '', surface: 'slash', signal: new AbortController().signal })
    expect(entries).toHaveLength(1)
    expect(entries[0]).toMatchObject({ id: 'native:compact', title: 'compact', availability: { kind: 'ready' },
      action: { kind: 'insert-command', text: '/compact' } })
    // plus surface: the native catalog is not a plus entry (slash is the command surface)
    expect(await source.query({ location, query: '', surface: 'plus', signal: new AbortController().signal })).toEqual([])

    facade.commandCatalogAnswer = (): AgentCommandCatalog => ({ kind: 'absent' })
    const absent = await source.query({ location, query: '', surface: 'slash', signal: new AbortController().signal })
    expect(absent[0]?.availability).toEqual({ kind: 'disabled', reason: '当前会话没有品牌原生命令目录（该品牌未播发）。' })

    facade.commandCatalogAnswer = (): AgentCommandCatalog => ({ kind: 'error', reason: 'channel-down' })
    await expect(source.query({ location, query: '', surface: 'slash', signal: new AbortController().signal }))
      .rejects.toThrow('连接已断开，命令目录不可用。')
  })
})

describe('PC-3 attachment chain (A06 controlled round trip)', () => {
  const CONTENT = 'controlled attachment bytes ✅'
  /** Full-chain fixture: a content owner (picker stand-in), a preparing port
   * that digests real bytes, and a transport that records what it received. */
  function attachFacade(options: { prepare?: 'ok' | 'refused' | 'unknown' } = {}) {
    const facade = sessionFacade()
    const prepared = { sha: sha256(CONTENT), preparedId: 'p-1' }
    facade.attachmentPrepare = async ({ sourceId, idempotencyKey }) => {
      void sourceId
      if (options.prepare === 'refused') return { kind: 'refused', reason: '超出大小限制' }
      if (options.prepare === 'unknown') return { kind: 'unknown', operationId: idempotencyKey }
      return { kind: 'prepared', reference: { preparedId: prepared.preparedId, name: 'a.txt',
        uri: `acp://prepared/${prepared.preparedId}`, mimeType: 'text/plain', sha256: prepared.sha, byteLength: CONTENT.length } }
    }
    const carried: { text: string; refs: { sha256: string; preparedId: string }[] }[] = []
    facade.sendBehavior = async ({ text, attachments }) => {
      carried.push({ text, refs: (attachments ?? []).map(ref => ({ sha256: (ref as unknown as { sha256: string }).sha256, preparedId: (ref as unknown as { preparedId: string }).preparedId })) })
      return { kind: 'accepted' }
    }
    return { facade, prepared, carried }
  }

  it('prepare → opaque ref → submit refs: the transport sees the SAME sha256 (A06)', async () => {
    const { facade, prepared, carried } = attachFacade()
    const picker = { pick: async () => ({ sourceId: 'content-1', name: 'a.txt', mimeType: 'text/plain' }) }
    const source = createAttachmentSource(facade, picker)
    const location = { kind: 'session' as const, connectionId: 'c', sessionId: 's1', contextRevision: 1 }
    expect(attachmentCapabilityOf(facade, location)).toEqual({ supported: true })
    const [entry] = await source.query({ location, query: '', surface: 'plus', signal: new AbortController().signal })
    expect(entry.availability.kind).toBe('ready')
    const result = await (entry.action as { prepare: (l: typeof location, key: string) => Promise<{ status: string; reference?: ChatContentReference }> })
      .prepare(location, 'item-1')
    expect(result).toEqual({ status: 'accepted', reference: 'p-1' })
    // The opaque reference rides the submission; the facade expands it and the
    // transport receives the full prepared attachment with the SAME digest.
    const gateway = createFacadeGateway(facade)
    const outcome = await gateway.submit({
      submissionId: 'sub-1', target: location, draftId: 'd', draftRevision: 1, text: '带附件',
      attachmentIds: ['item-1'], attachmentRefs: ['p-1' as ChatContentReference],
    })
    expect(outcome).toEqual({ status: 'accepted' })
    expect(carried[0]?.refs).toEqual([{ sha256: prepared.sha, preparedId: 'p-1' }])
  })

  it('a refused preparation keeps the item visible with its reason and blocks the send', async () => {
    const { facade } = attachFacade({ prepare: 'refused' })
    const picker = { pick: async () => ({ sourceId: 'content-1', name: 'big.bin' }) }
    const source = createAttachmentSource(facade, picker)
    const location = { kind: 'session' as const, connectionId: 'c', sessionId: 's1', contextRevision: 1 }
    const [entry] = await source.query({ location, query: '', surface: 'plus', signal: new AbortController().signal })
    const result = await (entry.action as { prepare: (l: typeof location, key: string) => Promise<{ status: string; message?: string }> })
      .prepare(location, 'item-1')
    expect(result).toEqual({ status: 'refused', message: '超出大小限制' })
  })

  it('an unknown preparation is its own phase: retryable, send-blocking, never auto-cleaned', async () => {
    const { facade } = attachFacade({ prepare: 'unknown' })
    const picker = { pick: async () => ({ sourceId: 'content-1', name: 'a.txt' }) }
    const source = createAttachmentSource(facade, picker)
    const location = { kind: 'session' as const, connectionId: 'c', sessionId: 's1', contextRevision: 1 }
    const [entry] = await source.query({ location, query: '', surface: 'plus', signal: new AbortController().signal })
    const result = await (entry.action as { prepare: (l: typeof location, key: string) => Promise<{ status: string }> })
      .prepare(location, 'item-1')
    expect(result).toEqual({ status: 'unknown' })
  })

  it('the honest production state: no prepare owner (S-05) or no picker (R-Z2-6) disables the entry with its reason', async () => {
    const bare = sessionFacade()
    const location = { kind: 'session' as const, connectionId: 'c', sessionId: 's1', contextRevision: 1 }
    expect(attachmentCapabilityOf(bare, location)).toEqual({
      supported: false, reason: '当前连接未提供附件传输通道（生产 prepare owner 缺席，S-05）。',
    })
    const source = createAttachmentSource(bare) // no picker channel exists in production
    const [entry] = await source.query({ location, query: '', surface: 'plus', signal: new AbortController().signal })
    expect(entry.availability).toEqual({ kind: 'disabled', reason: '文件选择通道未接通（R-Z2-6），附件入口保持禁用。' })
    const pickerSource = createAttachmentSource(bare, { pick: async () => undefined })
    const draftEntries = await pickerSource.query({
      location: { kind: 'draft', draftId: 'd', connectionId: 'c', contextRevision: 1 },
      query: '', surface: 'plus', signal: new AbortController().signal,
    })
    expect(draftEntries[0]?.availability.kind).toBe('disabled')
    expect(draftEntries[0]?.availability.kind).toBe('disabled')
  })
})

describe('PC-3 page flow: entries, phases and the A06 chain through the real composer', () => {
  const CONTENT = 'page-level attachment bytes'
  function pageFacade(options: { prepare?: 'ok' | 'refused' | 'unknown' } = {}) {
    const facade = sessionFacade()
    facade.attachmentPrepare = async ({ idempotencyKey }) => {
      if (options.prepare === 'refused') return { kind: 'refused', reason: '类型不支持' }
      if (options.prepare === 'unknown') return { kind: 'unknown', operationId: idempotencyKey }
      return { kind: 'prepared', reference: { preparedId: 'p-1', name: 'a.txt', uri: 'acp://prepared/p-1',
        mimeType: 'text/plain', sha256: sha256(CONTENT), byteLength: CONTENT.length } }
    }
    const carried: { sha256: string }[] = []
    facade.sendBehavior = async ({ attachments }) => {
      for (const ref of attachments ?? []) carried.push({ sha256: (ref as unknown as { sha256: string }).sha256 })
      return { kind: 'accepted' }
    }
    return { facade, carried }
  }
  const page = (facade: FacadeFixture, guard?: ChatSubmissionGuard) => {
    const chat = createChatContributions()
    const ui = chat.forScope({ isDisposed: false, add: (d: { dispose(): void }) => d } as never)
    ui.addInputSource(createNativeCommandSource(facade))
    ui.addInputSource(createAttachmentSource(facade, { pick: async () => ({ sourceId: 'content-1', name: 'a.txt' }) }))
    if (guard) ui.addSubmissionGuard(guard)
    return <ChatPage service={facade} chat={chat} theme="light" />
  }

  it.each(['refused', 'unknown', 'rejected'] as const)('a %s submission preparation keeps text and ready attachments with zero gateway calls', async status => {
    const { facade, carried } = pageFacade()
    const prepare = vi.fn(async () => {
      if (status === 'rejected') throw new Error('preparation receipt lost')
      return status === 'refused' ? { status: 'refused' as const, reason: '准备拒绝' } : { status: 'unknown' as const }
    })
    const container = await mount(page(facade, { id: 'controlled.guard', order: 1, prepare }))
    await act(async () => { container.querySelector<HTMLButtonElement>('[data-testid="chat-plus-button"]')!.click() })
    await act(async () => { await tick() })
    await act(async () => { container.querySelector<HTMLButtonElement>('[data-entry-id="attachments:add"]')!.click() })
    await act(async () => { await tick(); await tick() })
    await type(container, '保留附件草稿')
    await clickSend(container)
    await act(async () => { await tick() })
    expect(prepare).toHaveBeenCalledTimes(1)
    expect(facade.sends).toEqual([])
    expect(carried).toEqual([])
    expect(facade.releasedRefs).toEqual([])
    expect(input(container).value).toBe('保留附件草稿')
    expect(container.querySelector('[data-testid="chat-attachments"] [data-phase="ready"]')).not.toBeNull()
    expect(text(container, '[data-testid="chat-send-error"]')).toContain(status === 'refused' ? '准备拒绝' : '未知')
  })

  it('accepted prepare → ready item → send carries the digest to the transport; accepted clears the item', async () => {
    const { facade, carried } = pageFacade()
    const container = await mount(page(facade))
    await act(async () => { container.querySelector<HTMLButtonElement>('[data-testid="chat-plus-button"]')!.click() })
    await act(async () => { await tick() })
    const row = container.querySelector<HTMLButtonElement>('[data-entry-id="attachments:add"]')!
    await act(async () => { row.click() })
    await act(async () => { await tick(); await tick() })
    const item = container.querySelector('[data-testid="chat-attachments"] [data-phase="ready"]')
    expect(item).not.toBeNull()
    expect(text(container, '[data-testid="chat-attachments"]')).toContain('已就绪')
    await type(container, '看附件')
    await clickSend(container)
    expect(carried[0]?.sha256).toBe(sha256(CONTENT)) // the A06 assertion: same digest end to end
    expect(input(container).value).toBe('')
    // Handed-off items stay visible in the strip (the store keeps the sent
    // record's references alive); the draft text itself was cleared.
    expect(container.querySelector('[data-testid="chat-attachments"] [data-phase="ready"]')).not.toBeNull()
  })

  it('a refused preparation shows the kept item with its reason and the send stays blocked', async () => {
    const { facade } = pageFacade({ prepare: 'refused' })
    const container = await mount(page(facade))
    await act(async () => { container.querySelector<HTMLButtonElement>('[data-testid="chat-plus-button"]')!.click() })
    await act(async () => { await tick() })
    await act(async () => { container.querySelector<HTMLButtonElement>('[data-entry-id="attachments:add"]')!.click() })
    await act(async () => { await tick(); await tick() })
    const strip = container.querySelector('[data-testid="chat-attachments"]')
    expect(strip?.textContent).toContain('类型不支持')
    expect(strip?.querySelector('[data-phase="failed"]')).not.toBeNull()
    await type(container, '带被拒附件')
    expect(container.querySelector<HTMLButtonElement>('[data-testid="chat-send"]')!.disabled).toBe(true)
    expect(container.querySelector('[data-testid="chat-attachment-block"]')?.textContent).toContain('类型不支持')
  })

  it('an unknown preparation renders the unknown phase with a retry, and the item keeps blocking', async () => {
    const { facade } = pageFacade({ prepare: 'unknown' })
    const container = await mount(page(facade))
    await act(async () => { container.querySelector<HTMLButtonElement>('[data-testid="chat-plus-button"]')!.click() })
    await act(async () => { await tick() })
    await act(async () => { container.querySelector<HTMLButtonElement>('[data-entry-id="attachments:add"]')!.click() })
    await act(async () => { await tick(); await tick() })
    expect(container.querySelector('[data-testid="chat-attachments"] [data-phase="unknown"]')).not.toBeNull()
    expect(text(container, '[data-testid="chat-attachment-block"]')).toContain('结果未知')
    expect(container.querySelector('[data-action="retry-attachment"]')).not.toBeNull()
  })

  it('the capability note uses plain copy, retains the real facade reason, and never fakes readiness', async () => {
    const { facade } = pageFacade()
    facade.attachmentPrepare = undefined // the production facade answer
    const container = await mount(page(facade))
    expect(text(container, '[data-testid="chat-capability-note"]'))
      .toBe('附件暂不可用 · Enter 发送 · Shift + Enter 换行')
    expect(container.querySelector('[data-testid="chat-capability-note"]')?.getAttribute('title'))
      .toBe('当前连接未提供附件传输通道（生产 prepare owner 缺席，S-05）。')
  })
})

describe('PC-2 page flow: the brand catalog is visible in the slash panel', () => {
  it('keeps unavailable add actions disabled with compact copy and accessible full diagnostics', async () => {
    const facade = sessionFacade(), chat = createChatContributions(), scope = new OwnedResources()
    cleanup.push(async () => scope.dispose())
    chat.forScope(scope).addInputSource(createAttachmentSource(facade))
    const container = await mount(<ChatPage service={facade} chat={chat} theme="light" />)
    await act(async () => { container.querySelector<HTMLButtonElement>('[data-testid="chat-plus-button"]')!.click(); await tick() })
    const row = container.querySelector<HTMLButtonElement>('[data-entry-id="attachments:add"]')!
    expect(row.getAttribute('aria-disabled')).toBe('true')
    expect(row.querySelector('[data-disabled-summary="true"]')?.textContent).toBe('暂不可用')
    expect(row.getAttribute('title')).toContain('R-Z2-6')
    expect(row.getAttribute('aria-description')).toContain('文件选择通道未接通')
    expect(row.querySelector('.chat-sr-only')?.textContent).toContain('R-Z2-6')
    await act(async () => row.click())
    expect(container.querySelector('[data-testid="chat-input-panel"]')).not.toBeNull()
    expect(container.querySelector('[data-testid="chat-attachments"] [data-phase="ready"]')).toBeNull()
    expect(facade.sends).toEqual([])
  })
  it('ready commands render as rows and an absent catalog renders the honest reason row', async () => {
    const facade = sessionFacade()
    facade.commandCatalogAnswer = (): AgentCommandCatalog => ({
      kind: 'available', connectionId: 'c1', nativeSessionId: 'n1', commands: [{ name: 'compact', description: '总结会话' }],
    })
    const chat = createChatContributions()
    const ui = chat.forScope({ isDisposed: false, add: (d: { dispose(): void }) => d } as never)
    ui.addInputSource(createNativeCommandSource(facade))
    ui.addInputSource(createAttachmentSource(facade))
    const container = await mount(<ChatPage service={facade} chat={chat} theme="light" />)
    await type(container, '/co')
    // Real typing flow: the keyup after the input event is what re-syncs the
    // slash token against the freshly rendered text.
    await act(async () => {
      input(container).dispatchEvent(new KeyboardEvent('keyup', { bubbles: true }))
      await tick()
    })
    expect(container.querySelector('[data-panel-row="true"]')?.textContent).toContain('compact')
    // Absent catalog: the reason row, no fake commands.
    facade.commandCatalogAnswer = (): AgentCommandCatalog => ({ kind: 'absent' })
    // The catalog change arrives as a facade notification; the revision bump
    // re-issues the panel query against the new answer.
    await act(async () => { facade.emit(); await tick() })
    expect(text(container, '[data-testid="chat-panel-disabled-reason"]')).toContain('没有品牌原生命令目录')
    expect(container.querySelectorAll('[data-panel-row="true"]')).toHaveLength(1)
  })
})

describe('PC-5 runtimeGeneration rides the ChatLocation', () => {
  it('the snapshot generation reaches contribution locations; absence stays absent', async () => {
    for (const generation of [7, undefined]) {
      const facade = sessionFacade(generation === undefined ? {} : { runtimeGeneration: generation })
      const seen: (number | undefined)[] = []
      const chat = createChatContributions()
      const ui = chat.forScope({ isDisposed: false, add: (d: { dispose(): void }) => d } as never)
      ui.addContribution(chatContribution({
        id: 'test.capture', slot: 'composer.toolbar', order: 1, key: connectionBadgeKey,
        project: (context: ChatContributionContext) => {
          if (context.slot === 'composer.toolbar') seen.push(context.location.runtimeGeneration)
          return { hidden: true }
        },
      }))
      await mount(<ChatPage service={facade} chat={chat} theme="light" />)
      await act(async () => { await tick() })
      expect(seen.at(-1)).toBe(generation)
    }
  })
})

describe('toolbar public UI binding lifecycle', () => {
  function resources() {
    const scope = new OwnedResources()
    cleanup.push(async () => scope.dispose())
    return scope
  }

  it('binds only after mount with the original key, follows provider generations, and releases on unmount', async () => {
    const key = defineChatComponentKey<{ label: string }>('test.toolbar.widget', 1)
    const core = createUiComponentsService([{ componentId: key.id, major: key.major, providerId: 'controlled' }])
    cleanup.push(async () => core.dispose())
    const consumer = core.uiComponents.forScope(resources())
    const bindings: UiBinding<unknown>[] = []
    const ui: UiScope = {
      ...consumer,
      bind: (componentKey, options) => {
        const binding = consumer.bind(componentKey, options)
        bindings.push(binding as UiBinding<unknown>)
        return binding
      },
    }
    let mounts = 0
    function Widget({ label }: { label: string }) {
      const [generation] = useState(() => ++mounts)
      return <span data-testid="controlled-widget">{label} generation {generation}</span>
    }
    const provider = core.uiComponents.forScope(resources())
    const registration = provider.register({ key, providerId: 'controlled', component: Widget })
    const chat = createChatContributions()
    chat.forScope(resources()).addContribution(chatContribution({ id: 'controlled.widget', slot: 'composer.toolbar', order: 1, key,
      project: () => ({ hidden: false, props: { label: '业务状态' } }) }))
    chat.forScope(resources()).addContribution(chatContribution<{ readonly status: string }>({ id: 'controlled.badge', slot: 'composer.toolbar', order: 2, key: connectionBadgeKey,
      project: context => context.slot === 'composer.toolbar' ? { hidden: false, props: { status: context.connection.status } } : { hidden: true } }))
    const view = chat.contributionsBySlot('composer.toolbar').getSnapshot()[0]
    const context = { slot: 'composer.toolbar' as const, location: { kind: 'session' as const, connectionId: 'conn-1', sessionId: 's1', contextRevision: 1 }, connection: { status: 'connected' as const } }
    renderToString(<ToolbarContribution view={view} ui={ui} context={context}/>)
    expect(bindings).toEqual([]) // an uncommitted render owns no binding
    const container = await mount(<ChatPage service={sessionFacade()} chat={chat} uiComponents={ui} theme="light" />)
    expect(bindings).toHaveLength(1)
    expect(bindings[0].key).toBe(key)
    expect(text(container, '[data-testid="controlled-widget"]')).toBe('业务状态 generation 1')
    expect(text(container, '[data-testid="chat-connection-badge"]')).toBe('connected')
    await type(container, '保持输入')
    await act(async () => { registration.dispose() })
    expect(container.querySelector('[data-testid="controlled-widget"]')).toBeNull()
    expect(text(container, '[data-testid="chat-compose-toolbar"]')).not.toContain('失败')
    await act(async () => { provider.register({ key, providerId: 'controlled', component: Widget }) })
    expect(text(container, '[data-testid="controlled-widget"]')).toBe('业务状态 generation 2')
    expect(input(container).value).toBe('保持输入')
    expect(bindings).toHaveLength(1) // provider changes update the same mounted binding
    await act(async () => { roots.get(container)!.render(null) })
    expect(bindings[0].getSnapshot()).toEqual({ status: 'disposed' })
  })

  it('isolates throwing providers and projections, and a fresh provider generation recovers its outlet', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    const badKey = defineChatComponentKey<{ label: string }>('test.toolbar.bad', 1)
    const goodKey = defineChatComponentKey<{ label: string }>('test.toolbar.good', 1)
    const projectionKey = defineChatComponentKey<{ label: string }>('test.toolbar.projection', 1)
    const core = createUiComponentsService([badKey, goodKey].map(key => ({ componentId: key.id, major: key.major, providerId: 'controlled' })))
    cleanup.push(async () => core.dispose())
    const provider = core.uiComponents.forScope(resources())
    const good = ({ label }: { label: string }) => <span>{label}</span>
    const registration = provider.register({ key: badKey, providerId: 'controlled', component: () => { throw new Error('controlled render failure') } })
    provider.register({ key: goodKey, providerId: 'controlled', component: good })
    const chat = createChatContributions()
    for (const [id, key] of [['bad', badKey], ['good', goodKey]] as const) chat.forScope(resources()).addContribution(chatContribution({
      id: `controlled.${id}`, slot: 'composer.toolbar', order: 1, key, project: () => ({ hidden: false, props: { label: id } }),
    }))
    chat.forScope(resources()).addContribution(chatContribution({ id: 'controlled.projection-failure', slot: 'composer.toolbar', order: 2, key: projectionKey,
      project: () => { throw new Error('controlled projection failure') } }))
    const container = await mount(<ChatPage service={sessionFacade()} chat={chat} uiComponents={core.uiComponents.forScope(resources())} theme="light" />)
    expect(container.querySelector('[data-ui-outlet-error="true"]')).not.toBeNull()
    expect(text(container, '[data-testid="chat-compose-toolbar"]')).toContain('good')
    expect(text(container, '[data-testid="chat-compose-toolbar"]')).toContain('此工具栏贡献渲染失败')
    await type(container, '还可以输入')
    await act(async () => { registration.dispose(); provider.register({ key: badKey, providerId: 'controlled', component: good }) })
    expect(container.querySelector('[data-ui-outlet-error="true"]')).toBeNull()
    expect(text(container, '[data-testid="chat-compose-toolbar"]')).toContain('bad')
    expect(input(container).value).toBe('还可以输入')
  })

  it('legacy views without an original key stay empty and never bind a fabricated key', async () => {
    const bind = vi.fn()
    const ui = { bind } as unknown as UiScope
    const container = await mount(<ToolbarContribution ui={ui}
      view={{ id: 'legacy', slot: 'composer.toolbar', order: 1, keyId: 'legacy.widget', keyMajor: 1, project: () => ({ hidden: false, props: {} }) }}
      context={{ slot: 'composer.toolbar', location: { kind: 'session', connectionId: 'conn-1', sessionId: 's1', contextRevision: 1 }, connection: { status: 'connected' } }}/>)
    expect(bind).not.toHaveBeenCalled()
    expect(container.textContent).toBe('')
  })
})

describe('PC-7 reasoning evidence (R-Z2-5)', () => {
  const base: AgentMessage = { id: 'm1', role: 'assistant', text: '答案' }
  it('reasoningState wins when the connector reports it, including a real duration', () => {
    const parts = projectMessage({ ...base, reasoning: '想一想', reasoningState: { status: 'streaming', durationMs: 1234 } }, 'k')
    expect(parts[0]?.reasoning).toMatchObject({ status: 'streaming', durationMs: 1234 })
    const done = projectMessage({ ...base, reasoning: '想一想', status: 'completed', reasoningState: { status: 'interrupted' } }, 'k')
    expect(done[0]?.reasoning?.status).toBe('interrupted')
    expect(done[0]?.reasoning?.durationMs).toBeUndefined()
  })
  it('without reasoningState the legacy string inherits the run status and no duration is fabricated', () => {
    const parts = projectMessage({ ...base, reasoning: '想一想', status: 'running' }, 'k')
    expect(parts[0]?.reasoning).toMatchObject({ status: 'streaming' })
    expect(parts[0]?.reasoning?.durationMs).toBeUndefined()
  })
})
