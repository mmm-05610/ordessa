// Chat page: pane identity, draft store, send controller with stale guards,
// shared +/slash input panel, fixed bottom composer, approval surface and the
// project dialog entry.
//
// Pane discipline (ported from ordessa.agent-conversation view.tsx, the
// FC-0052/FC-0060 line): the draft is a fixed pane marker no session id can
// produce; the remount key, composer buffer and session identity all derive
// from ONE predicate; a draft never routes to the previously selected session
// (the facade owns that gate).
//
// Send discipline (service-adaptation §3 + input-spec C04): the submission
// freezes text/items/revision at capture time; the late result only clears the
// exact sent version — user typing after the send survives; a result arriving
// after a pane switch updates NOTHING in the new pane (X05); unknown keeps the
// draft and never auto-retries.
import { createElement, useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react'
import type { AgentSessions } from '@extensions/ordessa.agent-contracts/contract.js'
import type {
  ChatContributionsService, ChatInputEntry, ChatInputQuery, ChatSubmissionResult, ChatSubmissionSnapshot,
} from '@extensions/ordessa.chat-api/contract.js'
import { DraftStore, attachmentBlockReason } from '../state/draft'
import { useViewState } from '../state/expansion'
import {
  createFacadeGateway, facadeAttachmentCapability, interactionsForSession, paneRunState, projectConversation,
} from '../adapters/agent'
import type { ChatTheme } from '../components/messages/markdown-body'
import { ThreadBody, makeDefaultResolver, type ErasedComponent } from './thread'
import { ChatTextInput } from '../components/composer/text-input'
import { InputPanel } from '../components/composer/input-panel'
import { AttachmentStrip } from '../components/composer/attachments'
import { ApprovalPanel } from '../components/interactions/approval-panel'
import { ProjectDialog } from './project-dialog'
import { ConnectionBadge } from './connection-badge'
import { connectionBadgeKey } from '../state/keys'
import { chatStyles } from '../styles'
import { usePreferredTheme } from '../theme'
import { reconcileSlashSnapshot, slashReplacementRange, type SlashTokenSnapshot } from '../components/composer/trigger'

const draftPaneOf = 'draft'
const sessionPane = (sessionId: string) => `session:${sessionId}`

const draftBlockCopy: Record<string, string> = {
  unsupported: '当前连接不支持在项目中创建会话。',
  'no-project': '还没有选择项目，先在弹窗中选择一个项目。',
  'project-invalid': '所选项目在该服务上已失效，请重新选择。',
}

type PanelState = { readonly mode: 'plus'; readonly caret: number } | { readonly mode: 'slash'; readonly token: SlashTokenSnapshot } | null

export function ChatPage({ service, chat, theme: themeProp, openViaOverlay }: {
  service: AgentSessions
  chat: ChatContributionsService
  /** Explicit theme from the host; defaults to the OS preference. */
  theme?: ChatTheme
  /** Workbench overlay opener for the global dialog (absent → in-page render). */
  openViaOverlay?: () => void
}) {
  const theme = themeProp ?? usePreferredTheme()
  const state = useSyncExternalStore(service.subscribe, service.getSnapshot, service.getSnapshot)
  const agent = state.agent
  const connectionId = state.selectedConnectionId
  const drafting = state.draft?.active === true
  const sessionId = agent?.selectedSessionId
  const pane = drafting ? draftPaneOf : sessionPane(sessionId ?? '')
  // contextRevision bumps on every facade notification: contributions and
  // actions capture it and refuse to act on stale locations (contracts.md §3).
  const [revision, setRevision] = useState(0)
  useEffect(() => service.subscribe(() => setRevision(value => value + 1)), [service])
  const store = useMemo(() => new DraftStore(), [])
  const expansion = useViewState()
  const resolver = useMemo(() => makeDefaultResolver({ [connectionBadgeKey.id]: ConnectionBadge as unknown as ErasedComponent }), [])
  const gateway = useMemo(() => createFacadeGateway(service), [service])
  const [dialogOpen, setDialogOpen] = useState(false)
  const [panel, setPanel] = useState<PanelState>(null)
  const [sendError, setSendError] = useState('')
  const [pendingPane, setPendingPane] = useState<string | undefined>(undefined)
  const [plusQuery, setPlusQuery] = useState('')
  const panelKeyRef = useRef<((event: { key: string; preventDefault(): void }) => boolean) | undefined>(undefined)
  const caretRef = useRef<number | null>(null)
  const paneRef = useRef(pane)
  paneRef.current = pane

  useEffect(() => () => { store.dispose() }, [store])

  // A discarded draft loses its buffered text (FC-0030 port); an opened
  // session keeps it so the user can step back to the draft.
  const endedBy = state.draft?.endedBy
  useEffect(() => {
    if (!connectionId || !endedBy) return
    if (endedBy === 'discarded') store.disposePane(draftPaneOf)
  }, [connectionId, endedBy, store])

    // Live subscription: the composer is a controlled input whose value comes
  // from the store through useSyncExternalStore, so a text mutation re-renders.
  const composition = useSyncExternalStore(store.subscribe, () => store.read(pane), () => store.read(pane))
  const workspaceId = state.draft?.workspaceId
  const projectName = agent?.workspaces?.items.find(item => item.id === workspaceId)?.normalizedPath
  const run = agent && sessionId ? paneRunState(agent, sessionId) : undefined
  const running = run?.status === 'starting' || run?.status === 'running' || run?.status === 'stop-requested'
  const canSend = !drafting || state.draft?.canSend === true
  const blockReason = drafting ? state.draft?.blockReason : undefined
  const attachmentBlocked = attachmentBlockReason(composition.items)
  const sendDisabled = !composition.text.trim() || !canSend || (pendingPane !== undefined && pendingPane === pane) || attachmentBlocked !== null

  const location = useMemo(() => (drafting
    ? { kind: 'draft' as const, draftId: pane, connectionId: connectionId ?? undefined,
        serverInstanceId: agent?.connection.serverInstanceId, projectId: workspaceId, contextRevision: revision }
    : { kind: 'session' as const, connectionId: connectionId ?? '', sessionId: sessionId ?? '',
        serverInstanceId: agent?.connection.serverInstanceId, contextRevision: revision }),
  [drafting, pane, connectionId, agent?.connection.serverInstanceId, workspaceId, revision, sessionId])

  // Slash token reconciliation: any text/caret change re-derives or closes the
  // panel; the + panel and the slash panel are mutually exclusive.
  const syncSlashToken = useCallback((text: string, caret: number) => {
    setPanel(current => {
      if (current?.mode === 'plus') return current
      const next = reconcileSlashSnapshot(current?.mode === 'slash' ? current.token : null, text, caret)
      return next ? { mode: 'slash', token: next } : null
    })
  }, [])

  const submit = useCallback(async () => {
    const capturedPane = paneRef.current
    if (pendingPane !== undefined || !canSend) return
    const captured = store.read(capturedPane)
    if (!captured.text.trim()) return
    const snapshot: ChatSubmissionSnapshot = {
      submissionId: globalThis.crypto.randomUUID(),
      target: { ...location },
      draftId: capturedPane,
      draftRevision: captured.revision,
      text: captured.text,
      attachmentIds: captured.items.filter(item => item.phase.state === 'ready').map(item => item.id),
    }
    setSendError('')
    setPendingPane(capturedPane)
    let result: ChatSubmissionResult
    try {
      result = await gateway.submit(snapshot)
    } catch (cause) {
      result = { status: 'refused', reason: cause instanceof Error ? cause.message : String(cause) }
    } finally {
      setPendingPane(current => (current === capturedPane ? undefined : current))
    }
    if (paneRef.current !== capturedPane) return // X05: a switched pane is never touched
    if (result.status === 'accepted') {
      const now = store.read(capturedPane)
      // Clear exactly the sent version; typing that happened after the send
      // stays (C04).
      const text = now.text === snapshot.text ? '' : now.text
      store.markHandedOff(capturedPane, snapshot.attachmentIds)
      store.write(capturedPane, { ...now, text, revision: now.revision + 1 })
      setPanel(null)
    } else if (result.status === 'refused') {
      setSendError(result.reason)
    } else {
      setSendError('发送结果未知：连接可能已中断。草稿已保留，请核实后手动重发。')
    }
  }, [canSend, gateway, location, pendingPane, store])

  const stop = useCallback(() => {
    if (!run?.runId) return
    setSendError('')
    void service.stop(run.runId).catch(cause => setSendError(cause instanceof Error ? cause.message : String(cause)))
  }, [run?.runId, service])

  const pickEntry = useCallback((entry: ChatInputEntry) => {
    const current = store.read(paneRef.current)
    if (entry.availability.kind !== 'ready') return
    if (entry.action.kind === 'insert-command') {
      const text = current.text
      const caret = caretRef.current ?? text.length
      if (panel?.mode === 'slash') {
        const range = slashReplacementRange(panel.token, text, caret)
        if (!range) {
          // Stale token: the caret moved away — refuse the old insert.
          setSendError('命令插入位置已变化，未插入。')
          setPanel(null)
          return
        }
        store.write(paneRef.current, {
          ...current,
          text: text.slice(0, range.start) + entry.action.text + text.slice(range.end),
          revision: current.revision + 1,
        })
      } else {
        // plus: insert at the caret the panel captured when it opened.
        const at = Math.min(panel?.caret ?? caret, text.length)
        const inserted = text.slice(0, at) + entry.action.text + (at === 0 ? ' ' : '') + text.slice(at)
        store.write(paneRef.current, { ...current, text: inserted, revision: current.revision + 1 })
      }
      setPanel(null)
      return
    }
    if (entry.action.kind === 'invoke') {
      setPanel(null)
      void entry.action.execute({ ...location }).then(result => {
        if (result.status === 'refused') setSendError(result.message)
      })
      return
    }
    // add-content: only meaningful with a real attachment transport; the
    // honest facade capability is unsupported today, so the reference is
    // never faked into the draft.
    if (!facadeAttachmentCapability.supported) {
      setSendError(facadeAttachmentCapability.reason)
      setPanel(null)
      return
    }
    void entry.action.prepare({ ...location }).then(result => {
      if (result.status === 'accepted' && result.reference) {
        store.addItem(paneRef.current, {
          id: globalThis.crypto.randomUUID(), sourceId: entry.id, kind: 'file',
          displayName: String(result.reference), phase: { state: 'ready', reference: result.reference! },
        })
      } else if (result.status === 'refused') {
        setSendError(result.message)
      }
      setPanel(null)
    })
  }, [location, panel, store])

  const sourcesView = useMemo(() => {
    if (!panel) return undefined
    const request: ChatInputQuery = panel.mode === 'slash'
      ? { location: { ...location }, query: panel.token.query, surface: 'slash', signal: new AbortController().signal }
      : { location: { ...location }, query: plusQuery, surface: 'plus', signal: new AbortController().signal }
    // The query re-issues when the panel opens, the slash token changes or the
    // plus search string changes; per-source states live in the service.
    return chat.queryInputSources(request)
  }, [panel, location, chat, plusQuery])

  const panelConsumeKey = panel
    ? (event: { key: string; preventDefault(): void }) => {
        if (event.key === 'Escape') {
          event.preventDefault()
          setPanel(null)
          return true
        }
        if (panel.mode === 'slash' && ['Enter', 'Tab', 'ArrowUp', 'ArrowDown'].includes(event.key)) {
          return panelKeyRef.current?.(event) ?? false
        }
        if (panel.mode === 'plus' && (event.key === 'Enter' || event.key === 'ArrowUp' || event.key === 'ArrowDown')) {
          return panelKeyRef.current?.(event) ?? false
        }
        return false
      }
    : undefined

  // All hooks run unconditionally, BEFORE any early return (rules of hooks):
  // the placeholder branches must not change the hook count between renders.
  const toolbarSlot = useMemo(() => chat.contributionsBySlot('composer.toolbar'), [chat])
  const toolbarViews = useSyncExternalStore(toolbarSlot.subscribe, toolbarSlot.getSnapshot, toolbarSlot.getSnapshot)

  if (!connectionId) {
    return <div className="chat-page chat-placeholder"><h2>选择一个连接</h2><p>从连接面板选择一个已启用的代理。</p></div>
  }
  if (!agent) {
    return <div className="chat-page chat-placeholder"><h2>连接中</h2><p>{state.error ?? '正在等待代理连接。'}</p></div>
  }
  if (!drafting && !sessionId) {
    return <div className="chat-page chat-placeholder"><h2>选择一个会话</h2>
      <p><button type="button" className="chat-primary-action" data-testid="chat-new-session-empty"
        onClick={() => (openViaOverlay ? openViaOverlay() : setDialogOpen(true))}>新会话</button></p></div>
  }

  const conversation = drafting ? { conversationKey: `${connectionId}:draft`, parts: [] } : projectConversation(agent, sessionId ?? '')
  const interactions = drafting ? [] : interactionsForSession(agent, sessionId ?? '')

  return (
    <section className="chat-page" data-pane={pane} data-testid="chat-page" data-chat-theme={theme}>
      <style>{chatStyles}</style>
      <header className="chat-page-head">
        <div>
          <small>{drafting ? '新会话' : '会话'}</small>
          <h2>{drafting
            ? (projectName ? `你想在 ${projectName.split('/').filter(Boolean).at(-1)} 中做什么？` : '选择项目后开始')
            : agent.sessions.find(item => item.id === sessionId)?.title ?? sessionId}</h2>
        </div>
        <div className="chat-page-head-actions">
          <button type="button" className="chat-primary-action" data-testid="chat-new-session"
            onClick={() => (openViaOverlay ? openViaOverlay() : setDialogOpen(true))}>新会话</button>
          <span className="chat-run-state" data-status={run?.status ?? 'idle'}>{run?.status ?? 'idle'}</span>
        </div>
      </header>
      {agent.connection.status !== 'connected' && (
        <p role="alert" className="chat-error">连接已断开。正在运行的任务结果未知，请在连接面板重连。</p>
      )}
      {run?.status === 'stop-requested' && <p role="status" className="chat-note">已请求停止，等待代理确认。</p>}
      {run?.status === 'unknown' && <p role="status" className="chat-note">断连后任务结果未知。</p>}
      {agent.diagnostic && <p role="status" className="chat-note">{agent.diagnostic}</p>}
      {!drafting && conversation.parts.length === 0 && (
        <p className="chat-note" data-testid="chat-thread-empty">这个会话还没有消息。</p>
      )}
      <ThreadBody display={conversation} expansion={expansion} theme={theme} />
      <div className="chat-compose" data-testid="chat-compose">
        <ApprovalPanel interactions={interactions} interactionsCapability={agent.connection.capabilities.interactions}
          respond={(id, answer) => service.respond(id, answer)} />
        {drafting && !canSend && blockReason && (
          <p role="status" className="chat-compose-block" data-testid="chat-compose-block">
            {draftBlockCopy[blockReason] ?? '发送被项目门禁阻止。'}
          </p>
        )}
        <AttachmentStrip items={composition.items} onRemove={itemId => store.removeItem(pane, itemId)}
          onRetry={itemId => store.updateItem(pane, itemId, { phase: { state: 'preparing' } })} />
        {attachmentBlocked && <p role="status" className="chat-compose-block" data-testid="chat-attachment-block">{attachmentBlocked}</p>}
        {panel && sourcesView && (
          <InputPanel mode={panel.mode} sources={sourcesView} initialPlusQuery={plusQuery}
            keyForwardRef={panelKeyRef}
            onPick={pickEntry}
            onComplete={entry => pickEntry(entry)}
            onRetry={() => setPlusQuery(query => `${query}`)}
            onClose={() => setPanel(null)} />
        )}
        <div className="chat-compose-toolbar" data-testid="chat-compose-toolbar">
          {toolbarViews.map(view => {
            if (!view.project) return null
            const projected = view.project({
              slot: 'composer.toolbar', location: { ...location },
              connection: { status: agent.connection.status, runStatus: run?.status },
            })
            if (projected.hidden) return null
            const Component = resolver(view.keyId)
            if (!Component) return null // provider absent pre-foundation: position stays empty
            // The erased read side hands untyped props; the pairing was
            // enforced at registration by chatContribution's generic.
            return createElement(Component, { ...(projected.props as Record<string, unknown>), key: view.id })
          })}
        </div>
        <div className="chat-input-row">
          <button type="button" className="chat-icon-action" aria-label="打开添加与操作面板" data-testid="chat-plus-button"
            aria-expanded={panel?.mode === 'plus' ? 'true' : 'false'}
            onClick={() => {
              caretRef.current = null
              setPanel(current => (current?.mode === 'plus' ? null : { mode: 'plus', caret: caretRef.current ?? composition.text.length }))
            }}>＋</button>
          <ChatTextInput
            value={composition.text}
            editable={pendingPane === undefined || pendingPane === pane}
            placeholder={drafting ? '向新会话发送第一条消息' : '向这个代理发送消息'}
            submitDisabled={sendDisabled}
            onTextChange={value => store.setText(pane, value)}
            onCaretChange={caret => { caretRef.current = caret; syncSlashToken(composition.text, caret) }}
            panelConsumeKey={panelConsumeKey}
            onSubmit={() => void submit()}
            testid="chat-input"
          />
          {running
            ? <button type="button" className="chat-primary-action" data-testid="chat-stop"
                disabled={run?.status === 'stop-requested' || run?.status === 'starting'} onClick={stop}>
                {run?.status === 'stop-requested' ? '停止中…' : '请求停止'}
              </button>
            : <button type="button" className="chat-primary-action" data-testid="chat-send"
                disabled={sendDisabled} onClick={() => void submit()}>发送</button>}
        </div>
        {sendError && <p role="alert" className="chat-error" data-testid="chat-send-error">{sendError}</p>}
        {pendingPane === pane && <p role="status" className="chat-note" data-testid="chat-send-pending">发送中…</p>}
        <p className="chat-compose-meta">
          <span data-testid="chat-capability-note">{facadeAttachmentCapability.reason}</span>
        </p>
      </div>
      {dialogOpen && !openViaOverlay && (
        <ProjectDialog service={service} snapshot={state} close={() => setDialogOpen(false)}
          onProjectSelected={() => { setDialogOpen(false); service.startDraft?.() }} />
      )}
    </section>
  )
}
