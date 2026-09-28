// The Permissions domain's own Settings region («权限与审批»), contributed
// through the platform's real seam:
//   packages/workbench/api/workbench.ts:41  WorkbenchComposition.forScope(...).addSettingsSection
//   packages/workbench/src/model.ts:124     the scoped registry behind it (scope-owned, auto-released)
// Since T015 every policy fact here comes from a REAL read-only round-trip of
// the wire method `permissions.policy.describe` through the injected
// transport (no fetch/IPC lives in this package; tests fake the transport
// only, no network): the payload runs through the strict closed-shape decoder
// before anything renders. Absence hides the section entirely; a present-but-
// failing provider or an undecodable payload says "unreadable" and never
// "not installed"; `ready:false` reads 无法证明生效; a ceiling whose source is
// unverified renders as non-enforceable and is never presented as an
// organization limit. The ceiling summary stays read-only — the region
// exposes no write path, and a widening attempt is refused with the stable
// POLICY_CEILING_VIOLATION code instead of being applied or downgraded
// (ux.md §Settings, FR-08/FR-09; the UI never becomes an authority).
import { createElement } from 'react'
import type { IDisposable } from '@ordessa/extension-api'
import type { WorkbenchSettingsSection } from '@extensions/ordessa.contracts/contract.js'
import {
  ceilingRecordIsTrusted, decodeApprovalPayload, decodeDescribeResponse, renderRefusalSentence,
  ruleSourceSummaries, filterApprovalHistory,
  type PermissionsApprovalFactsSource, type PermissionsApprovalView,
  type PermissionsDescribeCeiling, type PermissionsDescribeIntent,
  type PermissionsDescribeParams, type PermissionsDescribeReview,
  type PermissionsDescribeTransport, type PermissionsHistoryFilter,
  type PermissionsSettingsHostHandle,
} from './contract'
import { PermissionsSettingsSectionView } from './settings-view'

export { filterApprovalHistory }

/** The rule sources the rendered facts name, derived from the decoded facts. */
export function permissionsRuleSources(facts: PermissionsDecodedFacts): readonly string[] {
  return ruleSourceSummaries(facts.ceilings, facts.intents, facts.approvals)
}

export const PERMISSIONS_SETTINGS_SECTION_ID = 'ordessa.permissions-settings.region'
export const PERMISSIONS_SETTINGS_SECTION_TITLE = '权限与审批'

export interface PermissionsDecodedFacts {
  /** The describe answer's own readiness fact: false means the policy state
   * cannot be proven to be in force — never rendered as an installation claim. */
  readonly ready: boolean
  readonly ceilings: readonly PermissionsDescribeCeiling[]
  readonly intents: readonly PermissionsDescribeIntent[]
  readonly needsReview: readonly PermissionsDescribeReview[]
  readonly approvals: readonly PermissionsApprovalView[]
  /** Approval payloads that failed the whitelist decode: counted and
   * disclosed, never rendered as a fact. (The describe payload decodes
   * all-or-nothing: an invalid shape never yields partial facts.) */
  readonly undecodableApprovals: number
  readonly untrustedCeilings: number
  readonly ceilingCount: number
}

export type PermissionsRegionState =
  /** Nothing to show: the permissions describe provider is not in this composition. */
  | { readonly kind: 'absent' }
  /** A provider exists and refused — a local error, never the "uninstalled" branch. */
  | { readonly kind: 'provider-error'; readonly code: string; readonly message: string }
  | { readonly kind: 'ready'; readonly facts: PermissionsDecodedFacts }

export function isPermissionsRegionVisible(state: PermissionsRegionState): boolean {
  return state.kind !== 'absent'
}

export async function resolvePermissionsRegionState(
  transport: PermissionsDescribeTransport,
  approvalFacts?: PermissionsApprovalFactsSource,
  describeParams?: PermissionsDescribeParams,
): Promise<PermissionsRegionState> {
  let answer: Awaited<ReturnType<PermissionsDescribeTransport['describe']>>
  try {
    answer = await transport.describe(describeParams ?? {})
  } catch {
    return {
      kind: 'provider-error', code: 'POLICY_SCOPE_UNVERIFIED',
      message: '策略读回调用未能完成：无法确认后端状态，界面不代替后端给出结论。',
    }
  }
  if (answer.status === 'no-provider') return { kind: 'absent' }
  if (answer.status === 'error') return { kind: 'provider-error', code: answer.code, message: answer.message }
  const decoded = decodeDescribeResponse(answer.payload)
  if (decoded === null) {
    return {
      kind: 'provider-error', code: 'POLICY_SCOPE_UNVERIFIED',
      message: 'describe 响应未通过闭合形态校验（未知或缺失字段不被忽略）：整批事实按未证实处理，不作为事实呈现。',
    }
  }
  let rawApprovals: readonly unknown[] = []
  if (approvalFacts !== undefined) {
    try {
      rawApprovals = await approvalFacts.load()
    } catch {
      return {
        kind: 'provider-error', code: 'APPROVAL_RESULT_UNKNOWN',
        message: '审批事实读取未完成：审批历史按未证实处理，界面不代替后端给出结论。',
      }
    }
  }
  const decodedApprovals = rawApprovals.map(decodeApprovalPayload)
  const approvals = decodedApprovals.filter((v): v is PermissionsApprovalView => v !== null)
  return {
    kind: 'ready',
    facts: {
      ready: decoded.ready,
      ceilings: decoded.ceilings,
      intents: decoded.intents,
      needsReview: decoded.needsReview,
      approvals,
      undecodableApprovals: rawApprovals.length - approvals.length,
      untrustedCeilings: decoded.ceilings.filter(c => !ceilingRecordIsTrusted(c)).length,
      ceilingCount: decoded.ceilings.length,
    },
  }
}

/** Widening an organization ceiling from the ordinary Settings page is always
 * refused — this region is not an admin-controlled entry (ux.md §Settings).
 * The outcome is computed from the request alone; no state can make it apply,
 * and there is nothing here that could write even if it wanted to. */
export type CeilingChangeOutcome = {
  readonly status: 'refused'
  readonly code: 'POLICY_CEILING_VIOLATION'
  readonly message: string
}

export function attemptCeilingWidening(_state: PermissionsRegionState, request: { readonly policyId: string }): CeilingChangeOutcome {
  return {
    status: 'refused', code: 'POLICY_CEILING_VIOLATION',
    message: renderRefusalSentence('POLICY_CEILING_VIOLATION', {
      operationCategory: '修改组织上限',
      targetSummary: `上限记录 ${request.policyId}`,
      policySource: '组织上限',
    }),
  }
}

/** Copy lives in one object so the wording rules (no uninstalled claim, no
 * cross-brand synonyms, unknown never reads as unlimited) are checkable. */
export const permissionsSettingsCopy = {
  regionDescription: '以下内容全部来自 permissions.policy.describe 只读回路与后端贡献的审批事实；本页不产生任何放行决定。',
  providerError: (code: string) =>
    `「权限与审批」数据当前不可读（${code}）：后端服务在场，但本次策略读回失败，界面不代替后端给出结论。`,
  describeNotReady: '策略生效性未证实：无法证明生效（后端服务在场，本轮读回未能证明上限正在执行；这也不表示服务缺席或已放宽）。',
  noCeiling: '当前没有可信的组织上限记录：未证实没有上限，不等于没有上限。',
  ceilingReadonly: '该项由组织/宿主限制，只能在管理员受控入口修改',
  ceilingNonEnforceable: '未通过可信来源校验：非可执行上限，不作为组织上限呈现，仅供知情',
  ceilingUnproven: '生效性未证实：非可执行上限（无法证明生效）',
  exposureLabel: {
    none: '无暴露', read: '只读', write: '可写', network: '可触网', exec: '可执行', full: '最高档（Ordessa 解释档位，不是任何品牌的模式名）',
  } as Record<string, string>,
  appliedRefusal: (outcome: CeilingChangeOutcome) => `拒绝：${outcome.message}`,
  needsReview: (review: PermissionsDescribeReview) =>
    `待复核：${review.source} 第 ${review.index ?? '未编号'} 条——原因：${review.reason}；未进入用户意图，按更严格一侧解析，不放行`,
  noHistory: '没有匹配的后端审批记录',
  historyRow: (view: PermissionsApprovalView) => {
    const state = view.status === 'settled'
      ? `已决定${view.decision === 'allow' ? '允许' : '拒绝'}`
      : view.status === 'open' ? '待审批'
        : view.status === 'invalid' ? '已失效' : '结果 unknown（未证实，不等于允许）'
    return `${view.approvalId}｜${view.display.operationCategory}｜${view.display.targetSummary}｜来源：${view.display.policySource}｜${state}`
  },
  intentRow: (intent: PermissionsDescribeIntent) => {
    const mode = intent.desiredMode === null
      ? '' : `｜期望模式：${intent.desiredMode.brand}:${intent.desiredMode.name}（品牌原生名称，仅对该品牌有效，不做跨品牌等价）`
    return `${intent.intentId}@${intent.revision}（作用域：${intent.scope}${mode}）`
  },
} as const

export interface PermissionsSettingsSnapshot {
  readonly state: PermissionsRegionState
  readonly generation: number
  readonly filter: PermissionsHistoryFilter
  readonly history: readonly PermissionsApprovalView[]
  readonly lastCeilingOutcome: CeilingChangeOutcome | undefined
  readonly registered: boolean
}

export interface PermissionsSettingsRegion extends IDisposable {
  readonly sectionId: string
  /** The exact object handed to `addSettingsSection`; tests read it off the real registry. */
  readonly section: WorkbenchSettingsSection
  readonly registered: boolean
  getSnapshot(): PermissionsSettingsSnapshot
  subscribe(listener: () => void): () => void
  /** Display-only filter over the decoded backend facts; it can never add,
   * remove or rewrite a fact, and it triggers no backend call. */
  setHistoryFilter(filter: PermissionsHistoryFilter): void
  attemptCeilingWidening(request: { readonly policyId: string }): CeilingChangeOutcome
  refresh(): Promise<PermissionsRegionState>
  hide(): void
  show(): Promise<PermissionsRegionState>
}

export interface PermissionsSettingsRegionDeps {
  host: PermissionsSettingsHostHandle
  /** The injected wire transport; the region performs the describe round-trip
   * through it and nothing else (no fetch/IPC lives in this package). */
  transport: PermissionsDescribeTransport
  /** Backend approval payloads for the history area (whitelist-decoded
   * before display); absent ⇒ the area honestly shows no rows. */
  approvalFacts?: PermissionsApprovalFactsSource
  /** Optional describe params, forwarded verbatim (principal/scope only). */
  describeParams?: PermissionsDescribeParams
  order?: number
}

export async function createPermissionsSettingsRegion(
  deps: PermissionsSettingsRegionDeps,
): Promise<PermissionsSettingsRegion> {
  const { host, transport, approvalFacts, describeParams } = deps
  let state = await resolvePermissionsRegionState(transport, approvalFacts, describeParams)
  let generation = 1
  let filter: PermissionsHistoryFilter = { status: 'all', decision: 'all', sessionId: 'all' }
  let lastCeilingOutcome: CeilingChangeOutcome | undefined
  let registration: IDisposable | undefined
  let disposed = false
  const listeners = new Set<() => void>()

  const buildSnapshot = (): PermissionsSettingsSnapshot => ({
    state, generation, filter,
    history: state.kind === 'ready' ? filterApprovalHistory(state.facts.approvals, filter) : [],
    lastCeilingOutcome, registered: registration !== undefined,
  })
  let snapshot = buildSnapshot()
  const publish = () => {
    snapshot = buildSnapshot()
    for (const listener of [...listeners]) listener()
  }
  const detach = () => { registration?.dispose(); registration = undefined }
  const attach = () => {
    if (registration !== undefined || !isPermissionsRegionVisible(state)) return
    registration = host.addSettingsSection(region.section)
  }
  const reload = async (): Promise<PermissionsRegionState> => {
    state = await resolvePermissionsRegionState(transport, approvalFacts, describeParams)
    generation += 1
    if (isPermissionsRegionVisible(state)) attach()
    else detach()
    publish()
    return state
  }

  const region: PermissionsSettingsRegion = {
    sectionId: PERMISSIONS_SETTINGS_SECTION_ID,
    section: {
      id: PERMISSIONS_SETTINGS_SECTION_ID,
      title: PERMISSIONS_SETTINGS_SECTION_TITLE,
      order: deps.order ?? 25,
      component: () => createElement(PermissionsSettingsSectionView, { region }),
    },
    get registered() { return registration !== undefined },
    getSnapshot: () => snapshot,
    subscribe(listener) {
      listeners.add(listener)
      return () => { listeners.delete(listener) }
    },
    setHistoryFilter(next) {
      // Pure display change over already-decoded facts: no transport call, no
      // fact rewrite — extra keys on `next` simply do not match any view row.
      filter = next
      publish()
    },
    attemptCeilingWidening(request) {
      lastCeilingOutcome = attemptCeilingWidening(state, request)
      publish()
      return lastCeilingOutcome
    },
    refresh: reload,
    hide() { detach(); publish() },
    show: reload,
    dispose() {
      detach()
      listeners.clear()
      disposed = true
    },
    get isDisposed() { return disposed },
  }
  attach()
  publish()
  return region
}
