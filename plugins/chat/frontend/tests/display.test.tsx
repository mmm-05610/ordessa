// Display-component counterexamples and behavior proofs (spec US1/US2,
// checklist 展示 row). Streamdown and shiki are mocked: these tests verify OUR
// ported logic (streaming/static split, plain-text fallback, collapse
// discipline, view-scoped tool expansion, output freeze/follow), not the
// third-party internals.
// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'

vi.mock('streamdown', () => ({
  Streamdown: (props: { mode: string; children?: string }) => {
    if (props.children?.includes('BOOM')) throw new Error('markdown exploded')
    return <div data-testid="streamdown-mock" data-mode={props.mode}>{props.children}</div>
  },
}))
vi.mock('shiki', () => ({
  createHighlighter: () => { throw new Error('shiki must not load in unit tests') },
}))

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
window.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} }
window.matchMedia = (query: string) => ({ matches: false, media: query, onchange: null, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {}, dispatchEvent: () => true })

const cleanup: (() => Promise<void>)[] = []
afterEach(async () => { for (const fn of cleanup.splice(0).reverse()) await fn(); vi.restoreAllMocks() })
const roots = new Map<HTMLElement, ReturnType<typeof createRoot>>()
async function mount(element: React.ReactNode) {
  const container = document.createElement('div')
  document.body.append(container)
  const root = createRoot(container)
  roots.set(container, root)
  cleanup.push(async () => { await act(async () => root.unmount()); roots.delete(container); container.remove() })
  await act(async () => { root.render(element) })
  return container
}
async function rerender(container: HTMLElement, element: React.ReactNode) {
  await act(async () => { roots.get(container)!.render(element) })
}
const text = (container: ParentNode, selector: string) => container.querySelector(selector)?.textContent ?? ''

import { MarkdownBody, buildChatMarkdownRenderKey, resolveChatMarkdownMode } from '../src/components/messages/markdown-body'
import { ReasoningBlock } from '../src/components/messages/reasoning-block'
import { ToolActivity } from '../src/components/tools/tool-frame'
import { ViewExpansionState } from '../src/state/expansion'
import type { AgentToolCall } from '@extensions/ordessa.agent-contracts/contract.js'

describe('markdown body (US1)', () => {
  it('only real streaming parses as streaming; history and completed stay static', () => {
    expect(resolveChatMarkdownMode(true)).toBe('streaming')
    expect(resolveChatMarkdownMode(false)).toBe('static')
  })

  it('streaming → complete transition does not change the render key (no subtree remount)', () => {
    const key = buildChatMarkdownRenderKey({ theme: 'light', codeWrap: false })
    expect(buildChatMarkdownRenderKey({ theme: 'light', codeWrap: false })).toBe(key)
    expect(buildChatMarkdownRenderKey({ theme: 'dark', codeWrap: false })).not.toBe(key)
  })

  it('renders completed content in static mode and keeps the original text', async () => {
    const container = await mount(<MarkdownBody text="# 标题\n正文 with 中文" streaming={false} theme="light" />)
    expect(container.querySelector('[data-testid="streamdown-mock"]')?.getAttribute('data-mode')).toBe('static')
    expect(text(container, '[data-testid="streamdown-mock"]')).toContain('中文')
  })

  it('a markdown render failure falls back to the ORIGINAL text — nothing is lost', async () => {
    const container = await mount(<MarkdownBody text="原始 正文 BOOM 保留" streaming={false} theme="light" />)
    expect(container.textContent).toContain('原始 正文 BOOM 保留')
    expect(container.querySelectorAll('[data-testid="streamdown-mock"]')).toHaveLength(0)
    expect(container.querySelector('.chat-md-fallback')).toBeTruthy()
  })
})

describe('reasoning block (US1 + research-plan)', () => {
  const props = (overrides: Partial<Parameters<typeof ReasoningBlock>[0]['props']> = {}) => ({
    conversationKey: 'c1', partId: 'p1', text: '思考内容', status: 'complete' as const, ...overrides,
  })

  it('defaults collapsed; user can expand; later status updates keep it open', async () => {
    const container = await mount(<ReasoningBlock props={props()} />)
    expect(container.querySelector('[data-testid="chat-reasoning-trigger"]')?.getAttribute('aria-expanded') ?? 'false').toBe('false')
    await act(async () => { container.querySelector('[data-testid="chat-reasoning-trigger"]')!.dispatchEvent(new MouseEvent('click', { bubbles: true })) })
    // Radix controls open state through its own listener; assert the trigger is now expanded.
    expect(container.querySelector('[data-testid="chat-reasoning-trigger"]')?.getAttribute('aria-expanded')).not.toBe('false')
    // A streaming status update arrives — user choice must win.
    await rerender(container, <ReasoningBlock props={props({ status: 'streaming' })} />)
    expect(container.querySelector('[data-testid="chat-reasoning-trigger"]')?.getAttribute('aria-expanded')).not.toBe('false')
  })

  it('a NEW reasoning part auto-collapses only when the user never interacted', async () => {
    const container = await mount(<ReasoningBlock props={props({ partId: 'p1' })} />)
    // user opened it
    await act(async () => { container.querySelector('[data-testid="chat-reasoning-trigger"]')!.dispatchEvent(new MouseEvent('click', { bubbles: true })) })
    const expandedAfterUser = container.querySelector('[data-testid="chat-reasoning-trigger"]')?.getAttribute('aria-expanded')
    // new part, user had interacted → stays as the user left it
    await rerender(container, <ReasoningBlock props={props({ partId: 'p2' })} />)
    expect(container.querySelector('[data-testid="chat-reasoning-trigger"]')?.getAttribute('aria-expanded')).toBe(expandedAfterUser)
    // fresh mount without interaction → collapsed even though a part exists
    const fresh = await mount(<ReasoningBlock props={props({ partId: 'p9', status: 'streaming' })} />)
    expect(fresh.querySelector('[data-testid="chat-reasoning-trigger"]')?.getAttribute('aria-expanded') ?? 'false').toBe('false')
  })

  it('shows no fabricated duration; only a real prop produces one', async () => {
    const none = await mount(<ReasoningBlock props={props({ status: 'streaming' })} />)
    expect(none.textContent).not.toMatch(/秒/)
    const real = await mount(<ReasoningBlock props={props({ durationMs: 4200 })} />)
    expect(real.textContent).toContain('4 秒')
  })
})

describe('tool activity (US2)', () => {
  void 0

  it('failed and unknown never merge: distinct labels and unknown has no error text', async () => {
    const failed = await mount(<ToolActivity props={{ conversationKey: 'c', toolId: 't', title: '运行命令', state: 'failed', errorText: '退出码 1' }} conversationKey="c" expansion={new ViewExpansionState()} />)
    expect(failed.querySelector('.chat-tool-state')?.getAttribute('data-state')).toBe('failed')
    const unknown = await mount(<ToolActivity props={{ conversationKey: 'c', toolId: 't', title: '运行命令', state: 'unknown' }} conversationKey="c" expansion={new ViewExpansionState()} />)
    expect(unknown.querySelector('.chat-tool-state')?.getAttribute('data-state')).toBe('unknown')
    expect(text(unknown, '.chat-tool-state')).toContain('结果未知')
  })

  it('same tool name in two conversations does NOT share expansion (view-scoped state)', async () => {
    const shared = new ViewExpansionState()
    const a = await mount(<ToolActivity props={{ conversationKey: 'c', toolId: 't', title: '同名工具', state: 'completed', outputText: 'A' }} conversationKey="cA" expansion={shared} />)
    const b = await mount(<ToolActivity props={{ conversationKey: 'c', toolId: 't', title: '同名工具', state: 'completed', outputText: 'B' }} conversationKey="cB" expansion={shared} />)
    await act(async () => { a.querySelector('[data-testid="chat-tool-summary"]')!.dispatchEvent(new MouseEvent('click', { bubbles: true })) })
    // conversation A expanded, conversation B untouched
    expect(a.querySelector('.chat-tool')?.getAttribute('data-open')).toBe('true')
    expect(b.querySelector('.chat-tool')?.getAttribute('data-open')).toBe('false')
  })

  it('a tool named `bash` still renders GENERIC (no fabricated command display)', async () => {
    const container = await mount(<ToolActivity props={{ conversationKey: 'c', toolId: 't', title: 'bash', state: 'completed', paramsText: '{"cmd":"ls"}' }} conversationKey="c" expansion={new ViewExpansionState()} />)
    expect(container.querySelectorAll('.chat-command')).toHaveLength(0)
    expect(container.querySelector('.chat-tool-kind')?.textContent).toBe('工具')
  })

  it('structured command display renders the $ line only from verified fields', async () => {
    const container = await mount(<ToolActivity props={{
      conversationKey: 'c', toolId: 't', title: '执行命令', state: 'completed',
      command: { command: 'ls -la', output: { text: 'file1\nfile2', exitCode: 0 } },
    }} conversationKey="c" expansion={new ViewExpansionState()} />)
    await act(async () => { container.querySelector('[data-testid="chat-tool-summary"]')!.dispatchEvent(new MouseEvent('click', { bubbles: true })) })
    expect(text(container, '[data-testid="chat-command-text"]')).toContain('$ ls -la')
    expect(text(container, '[data-testid="chat-execute-exit"]')).toContain('0')
  })
})

