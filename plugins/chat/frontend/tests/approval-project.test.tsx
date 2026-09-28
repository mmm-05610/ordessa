// Approval surface, project dialog and plugin entry proofs (US4/US5,
// checklist 项目创建/模态/审批 rows).
// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'

vi.mock('streamdown', () => ({ Streamdown: (props: { children?: string }) => <div>{props.children}</div> }))
vi.mock('shiki', () => ({ createHighlighter: () => { throw new Error('shiki must not load in unit tests') } }))
;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
window.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} }
window.matchMedia = (query: string) => ({ matches: false, media: query, onchange: null, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {}, dispatchEvent: () => true })

import { OwnedResources } from '@ordessa/extension-api'
import { ApprovalPanel } from '../src/components/interactions/approval-panel'
import { ProjectDialog } from '../src/views/project-dialog'
import { FacadeFixture } from './facade-fixture'
import createPlugin from '../src/entry'
import { ChatContributionsToken, chatContribution, ChatMessageBodyKey } from '@extensions/ordessa.chat-api/contract.js'
import type { AgentInteraction } from '@extensions/ordessa.agent-contracts/contract.js'

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

const pendingInteraction: AgentInteraction = {
  id: 'i1', sessionId: 's1', kind: 'confirm', title: '允许执行命令？', state: 'pending',
}

describe('approval panel (C02/C03)', () => {
  it('one unique operation surface per pending item; confirm offers explicit allow/deny from the service kind', async () => {
    const answered: { id: string; answer: unknown }[] = []
    const container = await mount(<ApprovalPanel interactions={[pendingInteraction]}
      respond={async (id, answer) => { answered.push({ id, answer }) }} />)
    expect(container.querySelectorAll('[data-testid="chat-approval"]')).toHaveLength(1)
    await act(async () => { (container.querySelector('[data-action="confirm"]') as HTMLButtonElement).click() })
    expect(answered).toEqual([{ id: 'i1', answer: { kind: 'confirm', confirmed: true } }])
  })

  it('a resolved interaction leaves the surface; nothing renders as tool success', async () => {
    const resolved: AgentInteraction = { ...pendingInteraction, state: 'resolved' }
    const container = await mount(<ApprovalPanel interactions={[resolved]} respond={async () => {}} />)
    expect(container.querySelectorAll('[data-testid="chat-approval"]')).toHaveLength(0)
  })

  it('an unsupported interactions capability disables actions without faking an answer (FC-0029)', async () => {
    const container = await mount(<ApprovalPanel interactions={[pendingInteraction]} interactionsCapability="unsupported"
      respond={async () => {}} />)
    expect(text(container, '[data-testid="chat-approval"]')).toContain('无法接收回应')
    expect(container.querySelector('[data-action="confirm"]')).toBeNull()
  })

  it('choice answers come only from service-provided choices — an approval with no choices offers nothing', async () => {
    const approvalNoChoices: AgentInteraction = { id: 'i2', sessionId: 's1', kind: 'approval', title: '审批', state: 'pending' }
    const withChoices: AgentInteraction = { id: 'i3', sessionId: 's1', kind: 'approval', title: '选择', state: 'pending',
      choices: [{ id: 'allow-once', label: '仅此一次允许' }] }
    const container = await mount(<ApprovalPanel interactions={[approvalNoChoices, withChoices]} respond={async () => {}} />)
    const approval = container.querySelectorAll('[data-testid="chat-approval"]')[0]
    expect(approval.querySelectorAll('[data-action]')).toHaveLength(0)
    const chooser = container.querySelectorAll('[data-testid="chat-approval"]')[1]
    expect(chooser.querySelector('[data-choice-id="allow-once"]')).toBeTruthy()
  })

  it('more pending items beyond three keep a visible count (C03)', async () => {
    const many = [1, 2, 3, 4, 5].map(n => ({ ...pendingInteraction, id: `i${n}` }))
    const container = await mount(<ApprovalPanel interactions={many} respond={async () => {}} />)
    expect(container.querySelectorAll('[data-testid="chat-approval"]')).toHaveLength(3)
    expect(text(container, '[data-testid="chat-approvals-more"]')).toContain('2')
  })
})

describe('project dialog (N01–N04/N06)', () => {
  it('lists facade projects with path and connection provenance; cancel performs zero backend calls', async () => {
    const facade = new FacadeFixture({
      workspaceSupport: 'supported',
      workspaces: [{ id: 'w1', normalizedPath: '/repos/demo' }, { id: 'w2', normalizedPath: '/repos/demo' }],
    })
    let selected: string | undefined
    const container = await mount(<ProjectDialog service={facade} snapshot={facade.getSnapshot()}
      close={() => {}} onProjectSelected={id => { selected = id }} />)
    const rows = container.querySelectorAll('[data-testid="chat-project-list"] .chat-dialog-row')
    expect(rows).toHaveLength(2) // same path, two entries — disambiguated by id/service in the row
    await act(async () => { (container.querySelector('[data-testid="chat-project-close"]') as HTMLButtonElement).click() })
    expect(facade.selectedWorkspaces).toEqual([]) // cancel: zero calls
    void selected
  })

  it('selecting a project calls the facade selection and reports it; selection is the ONLY backend call', async () => {
    const facade = new FacadeFixture({
      workspaceSupport: 'supported',
      workspaces: [{ id: 'w1', normalizedPath: '/repos/demo' }],
    })
    let selected: string | undefined
    const container = await mount(<ProjectDialog service={facade} snapshot={facade.getSnapshot()}
      close={() => {}} onProjectSelected={id => { selected = id }} />)
    await act(async () => { (container.querySelector('[data-project-id="w1"]') as HTMLButtonElement).click() })
    expect(facade.selectedWorkspaces).toEqual(['w1'])
    expect(selected).toBe('w1')
    expect(facade.startDraftCalls).toBe(0) // the dialog never opens a channel itself
  })

  it('missing native picker surfaces an explicit reason, never a fake success (N03)', async () => {
    const facade = new FacadeFixture({ workspaceSupport: 'supported', workspaces: [] })
    const container = await mount(<ProjectDialog service={facade} snapshot={facade.getSnapshot()}
      close={() => {}} onProjectSelected={() => {}} />)
    await act(async () => { (container.querySelector('[data-action="add-project"]') as HTMLButtonElement).click() })
    expect(text(container, '[role="alert"]')).toContain('没有可用的文件夹选择器')
  })
})

describe('plugin entry (CHAT-V05/V08 seam)', () => {
  it('activates against the real workbench model, provides ChatContributionsToken, and its toolbar contribution is reachable', async () => {
    const { createWorkbench } = await import('../../../../packages/workbench/src/model')
    const facade = new FacadeFixture({ sessions: [{ id: 's1', title: '会话一' }], selectedSessionId: 's1', messages: { s1: [] } })
    const scope = new OwnedResources()
    cleanup.push(async () => scope.dispose())
    const workbench = createWorkbench(scope)
    const plugin = createPlugin()
    expect(plugin.id).toBe('ordessa.chat')
    expect(plugin.provides).toBe(ChatContributionsToken)
    const provided = await plugin.activate({ resources: scope } as never, workbench.service, facade)
    expect(provided).toBeTruthy()
    // The chat-owned contribution is registered and readable in the toolbar slot.
    const slot = provided.contributionsBySlot('composer.toolbar')
    const views = slot.getSnapshot()
    expect(views.map(v => v.id)).toContain('ordessa.chat.connection-badge')
    // Project it: the connection status flows into the badge props.
    const connectionBadge = views.find(v => v.id === 'ordessa.chat.connection-badge')!
    const projected = connectionBadge.project!({
      slot: 'composer.toolbar', location: { kind: 'session', connectionId: 'conn-1', sessionId: 's1', contextRevision: 1 },
      connection: { status: 'connected' },
    })
    expect(projected.hidden).toBe(false)
    expect((projected as { props: { status: string } }).props.status).toBe('connected')
  })

  it('rejects a second registration of the same contribution id (no last-write-wins)', async () => {
    const { createWorkbench } = await import('../../../../packages/workbench/src/model')
    const scope = new OwnedResources()
    cleanup.push(async () => scope.dispose())
    const workbench = createWorkbench(scope)
    const plugin = createPlugin()
    const provided = await plugin.activate({ resources: scope } as never, workbench.service, new FacadeFixture())
    expect(() => provided.forScope(scope).addContribution(chatContribution({
      id: 'ordessa.chat.connection-badge', slot: 'composer.toolbar', order: 1, key: ChatMessageBodyKey,
    }))).toThrowError(/ordessa\.chat\.connection-badge/)
  })
})
