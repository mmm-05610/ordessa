// The Permissions approval region as a REAL Chat contribution (T06, US2).
// Built through `chatContribution()` and registered through Chat's published
// `ChatContributionsService`; this module never reimplements the registry and
// never imports host internals. The card only REQUESTS a decision (via the
// injected transport) and renders backend facts — it is not an authority:
// 已决定 requires a settled backend decision AND a confirmed native receipt
// (ux.md §Chat, contracts.md §C3, §C4 fail-closed).
import { createElement, useState, type FunctionComponent } from 'react'
import {
  chatContribution, defineChatComponentKey,
  type ChatActionResult, type ChatContributionContext, type ChatContributionRegistration,
  type ChatLocation, type ChatScopedAction,
} from '@extensions/ordessa.chat-api/contract.js'
import {
  applyQueryResult, decodeApprovalPayload, renderRefusalSentence, refusalCodeFromReason,
  type PermissionsApprovalScopeRecord, type PermissionsApprovalTransport,
  type PermissionsApprovalView, type PermissionsDecisionValue, type PermissionsDecideParams,
} from './contract'

// ---------------------------------------------------------------------------
// Component keys and contributions (Chat's own slots; no new conversation
// shell, no popover — the region renders inside Chat's published positions)
// ---------------------------------------------------------------------------

export interface ApprovalRegionProps { readonly location: ChatLocation }
export interface ApprovalCardViewProps { readonly view: PermissionsApprovalView }

export const ApprovalRegionKey = defineChatComponentKey<ApprovalRegionProps>('ordessa.permissions.approval-region', 1)
export const ApprovalCardKey = defineChatComponentKey<ApprovalCardViewProps>('ordessa.permissions.approval-card', 1)

const isSessionAuxiliary = (context: ChatContributionContext): context is
  Extract<ChatContributionContext, { slot: 'session.auxiliary' }> => context.slot === 'session.auxiliary'

/** Fresh registrations each call — ownership is the scope they are added
 * under, never an owner string; Chat refuses duplicates by id/contentKind. */
export function createApprovalContributions(): {
  readonly region: ChatContributionRegistration
  readonly card: ChatContributionRegistration
} {
  const region = chatContribution<ApprovalRegionProps>({
    id: 'permissions.approval-region',
    slot: 'session.auxiliary',
    order: 20,
    key: ApprovalRegionKey,
    project: context => isSessionAuxiliary(context)
      ? { hidden: false, props: { location: context.location } }
      : { hidden: true },
  })
  const card = chatContribution<ApprovalCardViewProps>({
    id: 'permissions.approval-card',
    slot: 'content.renderers',
    order: 20,
    key: ApprovalCardKey,
    contentKind: 'ordessa.permissions.approval-request',
    // Pure masked decode; a bad payload is null (readable fallback), never a
    // throw and never an executed payload.
    decode: payload => {
      const view = decodePayloadOrNothing(payload)
      return view === null ? null : { view }
    },
  })
  return Object.freeze({ region, card })
}

// Fresh masked decode for the renderer contribution.
const decodePayloadOrNothing = (payload: unknown): PermissionsApprovalView | null => decodeApprovalPayload(payload)

// ---------------------------------------------------------------------------
// Card model — the ONLY path to displayed state; local UI state can produce
// `awaiting`, never a decided/allowed rendering (forgery-proof by derivation)
// ---------------------------------------------------------------------------

export interface ApprovalCardLocal {
  readonly pending: boolean
  readonly linkLost: boolean
  readonly controlsClosed: boolean
  readonly recordedDecisionLabel: string | null
  readonly invalidReason: string | null
}

export type ApprovalActionId = 'allow-once' | 'allow-bounded' | 'deny' | 'query'

export interface ApprovalActionModel {
  readonly enabled: boolean
  readonly disabledReason: string | null
}

export interface ApprovalCardModel {
  readonly headline: string
  readonly status: 'awaiting-approval' | 'awaiting-confirmation' | 'decided' | 'not-actionable' | 'link-lost'
  readonly showDecided: boolean
  readonly allowEnabled: boolean
  readonly denyEnabled: boolean
  readonly queryEnabled: boolean
  readonly disabledReason: string | null
  readonly actions: Record<ApprovalActionId, ApprovalActionModel>
}

const decisionLabel = (d: PermissionsDecisionValue | null): string =>
  d === 'allow' ? '允许' : d === 'deny' ? '拒绝' : '未知'

export function computeApprovalCardModel(
  view: PermissionsApprovalView,
  location: ChatLocation,
  local: ApprovalCardLocal,
): ApprovalCardModel {
  const mk = (
    status: ApprovalCardModel['status'], headline: string,
    allowOnce: ApprovalActionModel, allowBounded: ApprovalActionModel, deny: ApprovalActionModel,
  ): ApprovalCardModel => {
    if (local.recordedDecisionLabel && status !== 'decided') headline = `决定已记录：${local.recordedDecisionLabel}。${headline}`
    return {
      status, headline,
      showDecided: status === 'decided',
      allowEnabled: allowOnce.enabled,
      denyEnabled: deny.enabled,
      queryEnabled: true,
      disabledReason: allowOnce.disabledReason ?? allowBounded.disabledReason ?? deny.disabledReason,
      actions: { 'allow-once': allowOnce, 'allow-bounded': allowBounded, 'deny': deny, 'query': { enabled: true, disabledReason: null } },
    }
  }
  const off = (reason: string): ApprovalActionModel => ({ enabled: false, disabledReason: reason })
  const on = (): ApprovalActionModel => ({ enabled: true, disabledReason: null })

  const crossSession = location.kind !== 'session' || location.sessionId !== view.sessionId
  const receipt = view.nativeReceipt
  const showDecided = view.status === 'settled' && view.decision !== null && receipt.kind === 'confirmed'

  if (crossSession) {
    const reason = '跨会话：审批绑定的会话与当前 Chat 位置不一致，自动不可操作'
    return mk('not-actionable', '不可操作：该审批属于其他会话（跨会话切换后自动不可操作）', off(reason), off(reason), off(reason))
  }
  if (view.status === 'invalid') {
    const sentence = view.refusal
      ? renderRefusalSentence(view.refusal.code, view.display)
      : '不可操作：审批已失效（原因未登记）'
    const reason = '审批已失效或不可操作'
    return mk('not-actionable', `不可操作：${sentence}`, off(reason), off(reason), off(reason))
  }
  if (local.invalidReason !== null) {
    const reason = '后端拒绝了对该审批的操作'
    return mk('not-actionable', `不可操作：${local.invalidReason}`, off(reason), off(reason), off(reason))
  }
  if (showDecided) {
    const reason = '决定已记录并经原生回执确认，不再接受新的操作'
    return mk('decided', `已决定：${decisionLabel(view.decision)}`, off(reason), off(reason), off(reason))
  }
  if (local.linkLost || view.status === 'unknown') {
    const allowReason = '连接不可用或结果 unknown：允许动作已禁用（fail-closed，断连不等于允许）'
    return mk('link-lost', '结果 unknown：连接不可用——允许动作已禁用（无法证明生效，未执行），请使用查询/恢复',
      off(allowReason), off(allowReason),
      local.controlsClosed ? off('决定已记录，不再接受新的操作') : on())
  }
  if (view.status === 'settled') {
    const reason = '已有决定等待原生回执确认，请使用查询/恢复'
    return mk('awaiting-confirmation', '待确认：回执 unknown——无法证明生效，未执行', off(reason), off(reason), off(reason))
  }
  if (local.controlsClosed) {
    const reason = '决定已记录，不再接受新的操作'
    return mk('awaiting-confirmation', '待确认：等待后端与原生回执确认', off(reason), off(reason), off(reason))
  }
  if (local.pending) {
    const reason = '决定提交中，等待后端回应'
    return mk('awaiting-confirmation', '待确认：已提交决定，等待后端与原生回执确认', off(reason), off(reason), off(reason))
  }
  // open: actions are offered only with the backend-supplied binding.
  if (view.requestId === null) {
    const reason = '缺少操作关联（requestId），安全起见不可操作'
    return mk('awaiting-approval', '待审批：该请求缺少可绑定的操作关联，不可操作', off(reason), off(reason), off(reason))
  }
  const onceScope = view.display.selectableScopes.find(s => s.kind === 'once')
  const boundedScope = view.display.selectableScopes.find(s => s.kind === 'bounded')
  return mk('awaiting-approval', '待审批：请确认操作类别、目标与范围',
    onceScope ? on() : off('后端未提供“仅一次”范围选项'),
    boundedScope ? on() : off('后端未提供可选的受限范围'),
    on())
}

// ---------------------------------------------------------------------------
// The card component. It exposes exactly three decision actions
// (允许一次 / 允许受限范围 / 拒绝) as ChatScopedActions, plus a read-only
// 查询/恢复 action; a press only ever sends `permissions.approvals.decide`.
// ---------------------------------------------------------------------------

export interface ApprovalDecisionInput { readonly approvalId: string }

export interface ApprovalCardProps {
  readonly view: PermissionsApprovalView
  readonly location: ChatLocation
  readonly transport: PermissionsApprovalTransport
}

interface LiveState extends ApprovalCardLocal { readonly view: PermissionsApprovalView }

const factsKey = (view: PermissionsApprovalView): string =>
  `${view.approvalId}:${view.version}:${view.status}:${view.decision ?? '-'}:${view.nativeReceipt.kind}`

export const PermissionsApprovalCard: FunctionComponent<ApprovalCardProps> = props => {
  const h = createElement
  const fresh = (): LiveState => ({
    view: props.view, pending: false, linkLost: false, controlsClosed: false,
    recordedDecisionLabel: null, invalidReason: null,
  })
  const [live, setLive] = useState<LiveState>(fresh)
  const [lastKey, setLastKey] = useState(() => factsKey(props.view))
  const key = factsKey(props.view)
  if (key !== lastKey) {
    // Newer backend facts replace stale local optimism; nothing flows the
    // other way — local state can never rewrite these fields.
    setLastKey(key)
    setLive(fresh())
  }

  const model = computeApprovalCardModel(live.view, props.location, live)

  const local = (): ApprovalCardLocal => ({
    pending: live.pending, linkLost: live.linkLost, controlsClosed: live.controlsClosed,
    recordedDecisionLabel: live.recordedDecisionLabel, invalidReason: live.invalidReason,
  })

  const reconcile = async (): Promise<ChatActionResult> => {
    const view = live.view
    if (view.approvalId.length === 0) return { status: 'unavailable' }
    try {
      const result = await props.transport.query({ approvalId: view.approvalId, nativeRequestId: view.nativeRequestId })
      const merged = applyQueryResult(view, result)
      setLive(s => ({ ...s, view: merged.view, pending: false, linkLost: merged.linkLost }))
      return result.outcome === 'resolved' ? { status: 'accepted' } : { status: 'unavailable' }
    } catch {
      setLive(s => ({ ...s, pending: false, linkLost: true }))
      return { status: 'unavailable' }
    }
  }

  /** The one decision sender: params are exactly `_DECIDE_REQUIRED` of the
   * backend wire; the result is folded in as *facts*, never as a local
   * "allowed" state. */
  const submitDecision = async (
    decision: PermissionsDecisionValue, scope: PermissionsApprovalScopeRecord, actionId: ApprovalActionId,
    input: ApprovalDecisionInput,
  ): Promise<ChatActionResult> => {
    const view = live.view
    if (input.approvalId !== view.approvalId) return { status: 'refused', message: '审批 id 与当前卡片不一致' }
    const actionModel = model.actions[actionId]
    if (!actionModel.enabled) return { status: 'unavailable' } // stale/forbidden press: no business call at all
    setLive(s => ({ ...s, pending: true }))
    const params: PermissionsDecideParams = {
      requestId: view.requestId ?? '', approvalId: view.approvalId, expectedVersion: view.version,
      decision, scope, sessionId: view.sessionId,
    }
    try {
      const result = await props.transport.decide(params)
      switch (result.outcome) {
        case 'recorded': {
          const decided: PermissionsApprovalView = { ...view, status: 'settled', decision: result.decision, version: result.version }
          setLive(s => ({ ...s, view: decided }))
          const action: ChatActionResult = { status: 'accepted' } // accepted ≠ completed
          const q = await reconcileQuery(decided)
          setLive(s => ({ ...s, view: q.view, pending: false, linkLost: q.linkLost }))
          return action
        }
        case 'already_recorded': {
          const decided: PermissionsApprovalView = {
            ...view, status: 'settled', decision: result.decision, version: result.version, requestId: result.requestId,
          }
          const q = await reconcileQuery(decided)
          setLive(s => ({
            ...s, view: q.view, pending: false, linkLost: q.linkLost, controlsClosed: true,
            recordedDecisionLabel: decisionLabel(result.decision),
          }))
          return { status: 'accepted' }
        }
        case 'invalid': {
          const code = refusalCodeFromReason(result.reason)
          const sentence = code !== null
            ? renderRefusalSentence(code, view.display)
            : '操作决定未被接受：审批当前不可操作（原因码未登记，安全起见不显示原文）'
          setLive(s => ({ ...s, pending: false, invalidReason: sentence }))
          return { status: 'refused', message: sentence }
        }
        case 'version_conflict': {
          const sentence = renderRefusalSentence('APPROVAL_STALE', view.display)
          setLive(s => ({ ...s, pending: false, invalidReason: sentence }))
          return { status: 'refused', message: sentence }
        }
        case 'unknown':
          setLive(s => ({ ...s, pending: false, linkLost: true }))
          return { status: 'unavailable' }
      }
      return { status: 'unavailable' }
    } catch {
      // Transport error / timeout: fail closed. Disconnect never means allow.
      setLive(s => ({ ...s, pending: false, linkLost: true }))
      return { status: 'unavailable' }
    }
  }

  const reconcileQuery = async (view: PermissionsApprovalView) => {
    try {
      const result = await props.transport.query({ approvalId: view.approvalId, nativeRequestId: view.nativeRequestId })
      return applyQueryResult(view, result)
    } catch {
      return { view: { ...view, status: 'unknown' as const }, linkLost: true }
    }
  }

  const onceScope = live.view.display.selectableScopes.find(s => s.kind === 'once')
  const boundedScope = live.view.display.selectableScopes.find(s => s.kind === 'bounded')

  // The three decision affordances are ChatScopedActions by construction.
  const allowOnce: ChatScopedAction<ApprovalDecisionInput> = input =>
    onceScope ? submitDecision('allow', onceScope, 'allow-once', input) : Promise.resolve({ status: 'unavailable' })
  const allowBounded: ChatScopedAction<ApprovalDecisionInput> = input =>
    boundedScope ? submitDecision('allow', boundedScope, 'allow-bounded', input) : Promise.resolve({ status: 'unavailable' })
  const deny: ChatScopedAction<ApprovalDecisionInput> = input =>
    submitDecision('deny', { kind: 'once' }, 'deny', input)

  const runAction = (id: ApprovalActionId) => {
    const input: ApprovalDecisionInput = { approvalId: live.view.approvalId }
    void (id === 'allow-once' ? allowOnce(input)
      : id === 'allow-bounded' ? allowBounded(input)
        : id === 'deny' ? deny(input)
          : reconcile())
  }

  const scopeLabels = (scopes: readonly PermissionsApprovalScopeRecord[]): string =>
    scopes.map(s => s.kind === 'once' ? '仅一次' : '受限至本会话结束').join('、') || '（无可选范围）'

  const actionButton = (id: ApprovalActionId, label: string) => {
    const action = model.actions[id]
    const reasonId = `permissions-approval-reason-${id}`
    return h('div', { key: id, 'data-action-wrap': id },
      h('button', {
        type: 'button',
        'data-action': id,
        'aria-label': label,
        'aria-disabled': action.enabled ? 'false' : 'true',
        'aria-describedby': action.enabled || action.disabledReason === null ? undefined : reasonId,
        onClick: () => runAction(id),
      }, label),
      !action.enabled && action.disabledReason !== null
        ? h('p', { id: reasonId, 'data-testid': 'approval-disabled-reason' }, action.disabledReason)
        : null)
  }

  return h('div', {
    role: 'group', 'aria-label': '待审批操作', 'data-testid': 'permissions-approval-card',
  },
    h('p', { 'data-testid': 'approval-headline', 'aria-live': 'polite' }, model.headline),
    h('dl', { 'data-testid': 'approval-fields' },
      h('div', null, h('dt', null, '操作类别'), h('dd', { 'data-field': 'operation-category' }, live.view.display.operationCategory)),
      h('div', null, h('dt', null, '目标'), h('dd', { 'data-field': 'target' }, live.view.display.targetSummary)),
      h('div', null, h('dt', null, '权限来源'), h('dd', { 'data-field': 'policy-source' }, live.view.display.policySource)),
      h('div', null, h('dt', null, '可选范围'), h('dd', { 'data-field': 'scopes' }, scopeLabels(live.view.display.selectableScopes)))),
    actionButton('allow-once', '允许一次'),
    actionButton('allow-bounded', '允许受限范围'),
    actionButton('deny', '拒绝'),
    actionButton('query', '查询/恢复'),
  )
}
