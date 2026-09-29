/**
 * Framework-free, DOM-free view model + pure reducers for the Settings
 * definition library (T09 / G15).
 *
 * Everything here is unit-testable without a browser: no `window`, no React, no
 * DOM node, no timers. The renderer (`view.ts` → `component.ts`) consumes the
 * state produced here and adds nothing of its own.
 *
 * Load-bearing invariants, each with a test in `tests/`:
 *  - §C2 per-target stamping: an async result whose stamp is not the current
 *    target is *dropped* and counted, never applied
 *    (`verification.md` G15 negative column "另一服务晚响应覆盖").
 *  - Draft safety: an error, a discarded dialog or a target switch never clears
 *    unsaved draft content (G15 "错误清草稿").
 *  - Capability truthfulness: `stored` alone can never render as an effect
 *    claim; `unknown` is a third value, distinct from `false` (FR07).
 *  - §C2 service absence renders an explained state, not a spinner and not a
 *    "plugin failed" card.
 */
import type {
  AssignmentView, BrandCapability, DefinitionDetail, DefinitionRevisionContent, DefinitionSummary,
  EffectiveSet, ErrorCode, ImportPlanResult, ImportPreview, ListQuery, NativeInspection,
  NativeObservation, OriginFilter, ResourceRef, RevisionInput, ServiceFailure, ServiceResult, TargetStamp,
} from './contract'
import { ASSIGNMENT_LAYERS, FACET_ID, sameStamp } from './contract'

// ---------------------------------------------------------------------------
// Async slices
// ---------------------------------------------------------------------------

export type SliceStatus = 'idle' | 'loading' | 'ready' | 'error' | 'absent'

/** Why something is absent, phrased so the gap is actionable (§C2). */
export interface AbsenceExplanation {
  readonly reason: string
  /** The exact missing symbol/checkpoint, so the gap is routable. */
  readonly missing: string
  readonly owner: string
}

export interface Slice<T> {
  readonly status: SliceStatus
  readonly data: T | null
  readonly failure: ServiceFailure | null
  /** Stamp of the request that produced this slice, for stale-request diagnosis. */
  readonly requestStamp: TargetStamp | null
  readonly absence: AbsenceExplanation | null
}

export function emptySlice<T>(): Slice<T> {
  return { status: 'idle', data: null, failure: null, requestStamp: null, absence: null }
}

export function absentSlice<T>(absence: AbsenceExplanation): Slice<T> {
  return { status: 'absent', data: null, failure: null, requestStamp: null, absence }
}

export function loadingSlice<T>(prev: Slice<T>, stamp: TargetStamp): Slice<T> {
  return { status: 'loading', data: prev.data, failure: null, requestStamp: stamp, absence: null }
}

export function sliceFromResult<T>(prev: Slice<T>, stamp: TargetStamp, result: ServiceResult<T>): Slice<T> {
  return result.ok
    ? { status: 'ready', data: result.data, failure: null, requestStamp: stamp, absence: null }
    : { status: 'error', data: prev.data, failure: result.error, requestStamp: stamp, absence: prev.absence }
}

/**
 * The one honest absence explanation today: the port has no wire. Recorded as
 * SR-7 in `specs/011-q3-subagents/api-requests.md`; nothing in this package may
 * fake it as production.
 */
export const SERVICE_ABSENCE: AbsenceExplanation = {
  reason: '定义服务尚未接线：本界面按端口契约渲染，不假设任何 HTTP/文件/CLI 通道，也不伪造数据。',
  missing: 'assets.native-subagents 的 Server 插件组合与 wire 方法（`DefinitionService` 的 assignment/resolve 入口仍是 NotImplementedError）',
  owner: 'C0 foundation（SR-7）',
}

// ---------------------------------------------------------------------------
// Draft
// ---------------------------------------------------------------------------

export type DraftField = 'displayName' | 'slug' | 'description' | 'roleBody'

export interface Draft {
  readonly definitionId: string | null
  readonly draftTarget: TargetStamp
  readonly baseRevision: number | null
  readonly expectedRowVersion: number
  readonly displayName: string
  readonly slug: string
  readonly description: string
  readonly roleBody: string
  /** True once the user has typed something not yet saved. */
  readonly dirty: boolean
  /** Marker of the last *explicitly saved* content, if any. */
  readonly savedMarker: string | null
}

export function startDraft(definition: DefinitionDetail | null, target: TargetStamp): Draft {
  return {
    definitionId: definition?.definitionId ?? null,
    draftTarget: target,
    baseRevision: definition?.latestRevision ?? null,
    expectedRowVersion: definition?.rowVersion ?? 0,
    displayName: definition?.displayName ?? '',
    slug: definition?.slug ?? '',
    description: definition?.description ?? '',
    roleBody: definition?.latestContent?.roleBody ?? '',
    dirty: false,
    savedMarker: definition?.latestContent?.contentDigest ?? null,
  }
}

/**
 * A draft written under one target must not be applied to another; it is kept
 * (draft safety) while the apply intent is refused with a reason.
 */
export function draftAppliesTo(draft: Draft, target: TargetStamp): boolean {
  return sameStamp(draft.draftTarget, target)
}

// ---------------------------------------------------------------------------
// Import two-step (preview → explicit approval)
// ---------------------------------------------------------------------------

export type ImportStep = 'idle' | 'previewing' | 'preview' | 'approving' | 'approved' | 'error' | 'absent'

export interface ImportFlow {
  readonly step: ImportStep
  readonly sourceRef: string
  readonly preview: ImportPreview | null
  readonly selectedPaths: readonly string[]
  readonly failure: ServiceFailure | null
  readonly result: readonly DefinitionSummary[] | null
}

export function emptyImportFlow(): ImportFlow {
  return { step: 'idle', sourceRef: '', preview: null, selectedPaths: [], failure: null, result: null }
}

/** FR14: approval only ever copies explicitly selected, selectable files. */
export function importApprovalPaths(flow: ImportFlow): readonly string[] {
  if (flow.step !== 'preview' || flow.preview === null) return []
  const selectable = new Set(flow.preview.files.filter(f => f.selectable).map(f => f.relativePath))
  return flow.selectedPaths.filter(p => selectable.has(p))
}

// ---------------------------------------------------------------------------
// Dialogs / notices
// ---------------------------------------------------------------------------

export interface DiffLine {
  readonly kind: 'added' | 'removed' | 'context'
  readonly text: string
}

export type Dialog =
  | { readonly kind: 'none' }
  | { readonly kind: 'archive'; readonly definitionId: string; readonly effectText: string; readonly pinned: readonly AssignmentView[] }
  | { readonly kind: 'restore'; readonly definitionId: string }
  | { readonly kind: 'clone'; readonly definitionId: string; readonly revision: number }
  | { readonly kind: 'publish-revision'; readonly definitionId: string; readonly nonMovementText: string; readonly pinned: readonly AssignmentView[] }
  | { readonly kind: 'revision-diff'; readonly definitionId: string; readonly from: number; readonly to: number; readonly lines: readonly DiffLine[] }

export const NO_DIALOG: Dialog = { kind: 'none' }

export interface Notice {
  readonly id: string
  readonly level: 'info' | 'warning' | 'refusal'
  readonly code: ErrorCode | null
  readonly text: string
}

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

export type MutationKind = 'save-revision' | 'archive' | 'restore' | 'clone' | 'assignment'

export interface OperationIntent {
  readonly operationKey: string
  readonly kind: MutationKind
  readonly stamp: TargetStamp
  readonly definitionId: string | null
  readonly assignment: AssignmentView | null
}

export interface DefaultsState {
  readonly 'user-global': Slice<readonly AssignmentView[]>
  readonly 'project': Slice<readonly AssignmentView[]>
}

export interface SettingsState {
  readonly target: TargetStamp
  /** The service-issued identity, used for the origin *label* only. It never
   * authorises anything here (§C1: 客户端不可自报 principal). */
  readonly viewerPrincipal: string
  readonly serviceAvailable: boolean
  readonly originFilter: OriginFilter
  readonly showArchived: boolean
  readonly list: Slice<readonly DefinitionSummary[]>
  readonly native: Slice<NativeInspection>
  readonly effective: Slice<EffectiveSet>
  readonly defaults: DefaultsState
  readonly selection: string | null
  readonly detail: Slice<DefinitionDetail>
  readonly draft: Draft | null
  readonly importFlow: ImportFlow
  readonly dialog: Dialog
  readonly pending: readonly OperationIntent[]
  readonly notices: readonly Notice[]
  /** Provable counters: how many late/foreign results were dropped. */
  readonly stats: { readonly droppedResults: number; readonly refusedMutations: number }
}

export function initialState(input: {
  readonly target: TargetStamp
  readonly viewerPrincipal: string
  readonly serviceAvailable: boolean
}): SettingsState {
  const mk = <T>(): Slice<T> => (input.serviceAvailable ? emptySlice<T>() : absentSlice<T>(SERVICE_ABSENCE))
  return {
    target: input.target,
    viewerPrincipal: input.viewerPrincipal,
    serviceAvailable: input.serviceAvailable,
    originFilter: 'all',
    showArchived: false,
    list: mk<readonly DefinitionSummary[]>(),
    native: mk<NativeInspection>(),
    effective: mk<EffectiveSet>(),
    defaults: { 'user-global': mk<readonly AssignmentView[]>(), 'project': mk<readonly AssignmentView[]>() },
    selection: null,
    detail: mk<DefinitionDetail>(),
    draft: null,
    importFlow: emptyImportFlow(),
    dialog: NO_DIALOG,
    pending: [],
    notices: [],
    stats: { droppedResults: 0, refusedMutations: 0 },
  }
}

// ---------------------------------------------------------------------------
// Actions
// ---------------------------------------------------------------------------

export type Action =
  | { type: 'target/switch'; target: TargetStamp }
  | { type: 'filter/origin'; filter: OriginFilter }
  | { type: 'filter/archived'; show: boolean }
  | { type: 'list/request' }
  | { type: 'list/result'; stamp: TargetStamp; result: ServiceResult<readonly DefinitionSummary[]> }
  | { type: 'native/request' }
  | { type: 'native/result'; stamp: TargetStamp; result: ServiceResult<NativeInspection> }
  | { type: 'effective/request' }
  | { type: 'effective/result'; stamp: TargetStamp; result: ServiceResult<EffectiveSet> }
  | { type: 'assignments/request'; layer: 'user-global' | 'project' }
  | { type: 'assignments/result'; layer: 'user-global' | 'project'; stamp: TargetStamp; result: ServiceResult<readonly AssignmentView[]> }
  | { type: 'detail/select'; definitionId: string | null }
  | { type: 'detail/request'; definitionId: string }
  | { type: 'detail/result'; definitionId: string; stamp: TargetStamp; result: ServiceResult<DefinitionDetail> }
  | { type: 'draft/start'; definitionId: string | null }
  | { type: 'draft/edit'; field: DraftField; value: string }
  | { type: 'draft/discard' }
  | { type: 'mutation/request'; intent: OperationIntent; refusal: string | null }
  | { type: 'mutation/result'; operationKey: string; kind: MutationKind; stamp: TargetStamp; result: ServiceResult<DefinitionSummary> }
  | { type: 'assignment-mutation/result'; operationKey: string; stamp: TargetStamp; result: ServiceResult<AssignmentView> }
  | { type: 'import/source'; sourceRef: string }
  | { type: 'import/preview-request' }
  | { type: 'import/preview-result'; stamp: TargetStamp; result: ServiceResult<ImportPreview> }
  | { type: 'import/toggle-path'; relativePath: string }
  | { type: 'import/approve-request'; operationKey: string }
  | { type: 'import/approve-result'; operationKey: string; stamp: TargetStamp; result: ServiceResult<ImportPlanResult> }
  | { type: 'dialog/open'; dialog: Dialog }
  | { type: 'dialog/close' }
  | { type: 'notice/dismiss'; id: string }

/** The query the current state implies, so `list/request` carries no hidden input. */
export function listQuery(state: SettingsState): ListQuery {
  return { includeArchived: state.showArchived, originFilter: state.originFilter }
}

// ---------------------------------------------------------------------------
// Reducer helpers
// ---------------------------------------------------------------------------

/**
 * §C2/G15: the single gate every async result passes through. A result whose
 * stamp is not the current target is counted as dropped and returns state that
 * differs in the counter *only* — no data, no status, no notice.
 */
export function droppedResult(state: SettingsState, stamp: TargetStamp): SettingsState | null {
  if (sameStamp(state.target, stamp)) return null
  return { ...state, stats: { ...state.stats, droppedResults: state.stats.droppedResults + 1 } }
}

function addNotice(state: SettingsState, item: Notice): SettingsState {
  return { ...state, notices: [...state.notices.filter(n => n.id !== item.id), item] }
}

function mergeSummary(rows: readonly DefinitionSummary[] | null, summary: DefinitionSummary): readonly DefinitionSummary[] {
  const current = rows ?? []
  return current.some(r => r.definitionId === summary.definitionId)
    ? current.map(r => (r.definitionId === summary.definitionId ? summary : r))
    : [...current, summary]
}

function mergeAssignment(rows: readonly AssignmentView[] | null, view: AssignmentView): readonly AssignmentView[] {
  const current = rows ?? []
  const key = (a: AssignmentView) => `${a.scopeKind}:${a.scopeId ?? ''}:${a.harnessId}:${a.definitionId}`
  return current.some(a => key(a) === key(view)) ? current.map(a => (key(a) === key(view) ? view : a)) : [...current, view]
}

// ---------------------------------------------------------------------------
// Reducer
// ---------------------------------------------------------------------------

export function reduce(state: SettingsState, action: Action): SettingsState {
  switch (action.type) {
    case 'target/switch': {
      // Re-read everything for the new target, but the user's unsaved draft, the
      // open dialog and dismissible notices are NOT destroyed (draft safety).
      // The draft keeps its own `draftTarget`, so applying it afterwards is
      // refused instead of silently landing on the new target.
      const fresh = initialState({ target: action.target, viewerPrincipal: state.viewerPrincipal, serviceAvailable: state.serviceAvailable })
      return {
        ...fresh,
        originFilter: state.originFilter,
        showArchived: state.showArchived,
        draft: state.draft,
        dialog: state.dialog,
        importFlow: state.importFlow.preview === null
          ? emptyImportFlow()
          : { ...emptyImportFlow(), sourceRef: state.importFlow.sourceRef, preview: state.importFlow.preview, selectedPaths: state.importFlow.selectedPaths, step: state.importFlow.step },
        notices: state.notices,
        stats: state.stats,
      }
    }
    case 'filter/origin':
      return { ...state, originFilter: action.filter }
    case 'filter/archived':
      return { ...state, showArchived: action.show }

    case 'list/request':
      return { ...state, list: loadingSlice(state.list, state.target) }
    case 'list/result': {
      const drop = droppedResult(state, action.stamp)
      if (drop) return drop
      return { ...state, list: sliceFromResult(state.list, action.stamp, action.result) }
    }

    case 'native/request':
      return { ...state, native: loadingSlice(state.native, state.target) }
    case 'native/result': {
      const drop = droppedResult(state, action.stamp)
      if (drop) return drop
      return { ...state, native: sliceFromResult(state.native, action.stamp, action.result) }
    }

    case 'effective/request':
      return { ...state, effective: loadingSlice(state.effective, state.target) }
    case 'effective/result': {
      const drop = droppedResult(state, action.stamp)
      if (drop) return drop
      return { ...state, effective: sliceFromResult(state.effective, action.stamp, action.result) }
    }

    case 'assignments/request':
      return { ...state, defaults: { ...state.defaults, [action.layer]: loadingSlice(state.defaults[action.layer], state.target) } }
    case 'assignments/result': {
      const drop = droppedResult(state, action.stamp)
      if (drop) return drop
      const slice = sliceFromResult(state.defaults[action.layer], action.stamp, action.result)
      const next: SettingsState = { ...state, defaults: { ...state.defaults, [action.layer]: slice } }
      return slice.status === 'error' && slice.failure
        ? addNotice(next, {
          id: `assignments:${action.layer}:${slice.failure.code}`, level: 'refusal', code: slice.failure.code,
          text: `${action.layer === 'user-global' ? '用户全局' : '项目'}默认分配读取失败：${slice.failure.detail}。上次读取结果已保留，未写入任何分配。`,
        })
        : next
    }

    case 'detail/select':
      return { ...state, selection: action.definitionId, detail: { ...emptySlice<DefinitionDetail>(), status: action.definitionId === null ? 'idle' : 'idle' } }
    case 'detail/request':
      return { ...state, detail: loadingSlice(state.detail, state.target) }
    case 'detail/result': {
      // A detail response for a row the user already abandoned must not land.
      if (action.definitionId !== state.selection) return state
      const drop = droppedResult(state, action.stamp)
      if (drop) return drop
      return { ...state, detail: sliceFromResult(state.detail, action.stamp, action.result) }
    }

    case 'draft/start': {
      const definition = state.detail.data !== null && state.detail.data.definitionId === action.definitionId ? state.detail.data : null
      return { ...state, draft: startDraft(definition, state.target) }
    }
    case 'draft/edit': {
      const base = state.draft ?? startDraft(state.detail.data, state.target)
      return { ...state, draft: { ...base, [action.field]: action.value, dirty: true } }
    }
    case 'draft/discard':
      // The ONLY action that removes a draft, and it is an explicit user action.
      return { ...state, draft: null }

    case 'mutation/request': {
      if (action.refusal !== null) {
        return addNotice({ ...state, stats: { ...state.stats, refusedMutations: state.stats.refusedMutations + 1 } }, {
          id: `refuse:${action.intent.operationKey}`, level: 'refusal', code: null, text: action.refusal,
        })
      }
      return { ...state, pending: [...state.pending.filter(p => p.operationKey !== action.intent.operationKey), action.intent] }
    }
    case 'mutation/result': {
      const drop = droppedResult(state, action.stamp)
      if (drop) return drop
      const pending = state.pending.find(p => p.operationKey === action.operationKey)
      // An untracked or duplicate arrival never re-applies.
      if (!pending) return state
      const cleared: SettingsState = { ...state, pending: state.pending.filter(p => p.operationKey !== action.operationKey) }
      if (!action.result.ok) {
        // CAS / ceiling / busy failures keep the draft AND the last saved content.
        return addNotice(cleared, {
          id: `mutation:${action.operationKey}`, level: 'refusal', code: action.result.error.code,
          text: mutationFailureText(action.kind, action.result.error),
        })
      }
      const summary = action.result.data
      const draft = cleared.draft === null || action.kind === 'assignment'
        ? cleared.draft
        : { ...cleared.draft, dirty: false, savedMarker: `rev:${summary.latestRevision}` }
      return addNotice({ ...cleared, draft, list: { ...cleared.list, status: 'ready', data: mergeSummary(cleared.list.data, summary), requestStamp: action.stamp, absence: null } }, {
        id: `mutation:${action.operationKey}`, level: 'info', code: null, text: mutationSuccessText(action.kind, summary),
      })
    }

    case 'assignment-mutation/result': {
      const drop = droppedResult(state, action.stamp)
      if (drop) return drop
      const pending = state.pending.find(p => p.operationKey === action.operationKey)
      if (!pending) return state
      const cleared: SettingsState = { ...state, pending: state.pending.filter(p => p.operationKey !== action.operationKey) }
      if (!action.result.ok) {
        return addNotice(cleared, {
          id: `mutation:${action.operationKey}`, level: 'refusal', code: action.result.error.code,
          text: mutationFailureText('assignment', action.result.error),
        })
      }
      const view = action.result.data
      const layer = view.scopeKind.startsWith('project') ? 'project' : 'user-global'
      const slice = cleared.defaults[layer]
      return addNotice({
        ...cleared,
        defaults: { ...cleared.defaults, [layer]: { ...slice, status: 'ready', data: mergeAssignment(slice.data, view), requestStamp: action.stamp, absence: null } },
      }, { id: `mutation:${action.operationKey}`, level: 'info', code: null, text: assignmentSuccessText(view) })
    }

    case 'import/source':
      return { ...state, importFlow: { ...state.importFlow, sourceRef: action.sourceRef } }
    case 'import/preview-request':
      return { ...state, importFlow: { ...state.importFlow, step: 'previewing', failure: null, result: null } }
    case 'import/preview-result': {
      const drop = droppedResult(state, action.stamp)
      if (drop) return drop
      // A failed preview keeps any edit draft and the previously shown preview.
      if (!action.result.ok) return { ...state, importFlow: { ...state.importFlow, step: 'error', failure: action.result.error } }
      return { ...state, importFlow: { ...state.importFlow, step: 'preview', preview: action.result.data, selectedPaths: [], failure: null } }
    }
    case 'import/toggle-path': {
      if (state.importFlow.step !== 'preview') return state
      const has = state.importFlow.selectedPaths.includes(action.relativePath)
      return {
        ...state,
        importFlow: {
          ...state.importFlow,
          selectedPaths: has ? state.importFlow.selectedPaths.filter(p => p !== action.relativePath) : [...state.importFlow.selectedPaths, action.relativePath],
        },
      }
    }
    case 'import/approve-request': {
      if (importApprovalPaths(state.importFlow).length === 0) {
        return addNotice({ ...state, stats: { ...state.stats, refusedMutations: state.stats.refusedMutations + 1 } }, {
          id: `refuse:${action.operationKey}`, level: 'refusal', code: 'DEFINITION_INVALID',
          text: '尚未显式选择可导入的文件；导入只复制经批准的内容（FR14），未写入任何定义。',
        })
      }
      return { ...state, importFlow: { ...state.importFlow, step: 'approving' } }
    }
    case 'import/approve-result': {
      const drop = droppedResult(state, action.stamp)
      if (drop) return drop
      if (!action.result.ok) return { ...state, importFlow: { ...state.importFlow, step: 'error', failure: action.result.error } }
      return { ...state, importFlow: { ...state.importFlow, step: 'approved', result: action.result.data.definitions, failure: null } }
    }

    case 'dialog/open':
      return { ...state, dialog: action.dialog }
    case 'dialog/close':
      // Abandoning a dialog must not clear the draft (G15 negative column).
      return { ...state, dialog: NO_DIALOG }

    case 'notice/dismiss':
      return { ...state, notices: state.notices.filter(n => n.id !== action.id) }
  }
}

// ---------------------------------------------------------------------------
// Failure / success texts
// ---------------------------------------------------------------------------

export function mutationFailureText(kind: MutationKind, error: ServiceFailure): string {
  switch (error.code) {
    case 'REVISION_STALE':
      return `该行已被别处更新（${error.detail}）。草稿与上次成功保存的内容都保留了；请重新加载后再保存。`
    case 'PERMISSION_EXCEEDS_CEILING':
      return `超出实际授权上限，已拒绝：${error.detail}。声明仍作为文本保留，不会被静默收窄并声称原样生效。`
    case 'ASSIGNMENT_CONFLICT':
      return `分配冲突，未写入：${error.detail}`
    case 'PROVIDER_BUSY':
      return `目标正忙，未卸载也未改写：${error.detail}`
    case 'OPERATION_UNKNOWN':
      return `操作结果未知，可按同一 operationKey 复查；未回退为静默成功：${error.detail}`
    case 'NATIVE_DISCOVERY_UNCONTROLLED':
      return `原生发现不受控，未声称已屏蔽：${error.detail}`
    case 'LOAD_UNVERIFIED':
      return `装载未经验证，不报告为已装载：${error.detail}`
    default:
      return `${kind} 失败：${error.detail}（草稿未清空，已存内容未改动）`
  }
}

export function mutationSuccessText(kind: MutationKind, summary: DefinitionSummary): string {
  switch (kind) {
    case 'archive':
      return `已归档"${summary.displayName}"：新的选择不再提供，已有固定分配与会话快照未改动。`
    case 'restore':
      return `已恢复"${summary.displayName}"为可选内容；未自动启用任何分配。`
    case 'clone':
      return `已复制为"${summary.displayName}"（新 definitionId，原固定分配未改动）。`
    case 'save-revision':
      return `已存为修订 v${summary.latestRevision}。存内容不等于启用；固定分配未移动。`
    case 'assignment':
      return `已按批准写入分配（v${summary.latestRevision}）。生效时机仍由提交闸门决定。`
  }
}

export function assignmentSuccessText(view: AssignmentView): string {
  if (view.decision === 'disable') return `已在 ${view.scopeKind} 排除受管定义 ${view.definitionId}；不改动其它层，也不触碰原生发现项。`
  if (view.decision === 'inherit') return `已在 ${view.scopeKind} 恢复继承（${view.definitionId}）；本层不再作决定。`
  return `已在 ${view.scopeKind} 固定启用 ${view.definitionId}@v${view.revision ?? ''}；其它项目/Profile 不受影响。存内容与生效是两件事。`
}

// ---------------------------------------------------------------------------
// Intent builders (pure request descriptors; the host executes them on the port)
// ---------------------------------------------------------------------------

export interface BuiltIntent {
  readonly intent: OperationIntent
  readonly refusal: string | null
}

function intentOf(kind: MutationKind, operationKey: string, stamp: TargetStamp, definitionId: string | null, assignment: AssignmentView | null = null): OperationIntent {
  return { operationKey, kind, stamp, definitionId, assignment }
}

export function archiveIntent(definition: DefinitionSummary, target: TargetStamp, nonce: string): BuiltIntent {
  return { intent: intentOf('archive', `archive:${definition.definitionId}:${definition.rowVersion}:${nonce}`, target, definition.definitionId), refusal: null }
}

export function restoreIntent(definition: DefinitionSummary, target: TargetStamp, nonce: string): BuiltIntent {
  return { intent: intentOf('restore', `restore:${definition.definitionId}:${definition.rowVersion}:${nonce}`, target, definition.definitionId), refusal: null }
}

export function cloneIntent(definition: DefinitionSummary, revision: number, target: TargetStamp, nonce: string): BuiltIntent {
  return { intent: intentOf('clone', `clone:${definition.definitionId}:${revision}:${nonce}`, target, definition.definitionId), refusal: null }
}

export function saveRevisionIntent(draft: Draft, content: RevisionInput, target: TargetStamp, nonce: string): BuiltIntent {
  const operationKey = `save:${draft.definitionId ?? 'new'}:${draft.expectedRowVersion}:${content.expectedRowVersion}:${nonce}`
  if (!draftAppliesTo(draft, target)) {
    return { intent: intentOf('save-revision', operationKey, target, draft.definitionId), refusal: '草稿属于另一个目标（Server/项目/Profile/会话已切换），未应用；草稿内容保留。' }
  }
  if (!draft.dirty) {
    return { intent: intentOf('save-revision', operationKey, target, draft.definitionId), refusal: '草稿没有未保存的改动；未发布新修订（发布须显式动作）。' }
  }
  if (draft.definitionId !== null && content.definitionId !== draft.definitionId) {
    return { intent: intentOf('save-revision', operationKey, target, draft.definitionId), refusal: '修订内容与草稿所属定义不一致，已拒绝，未写入。' }
  }
  if (content.roleBody === '') {
    return { intent: intentOf('save-revision', operationKey, target, draft.definitionId), refusal: '角色正文为空；未发布新修订。' }
  }
  return { intent: intentOf('save-revision', operationKey, target, draft.definitionId), refusal: null }
}

/** The revision input the current draft implies; digests stay service-owned. */
export function revisionInput(draft: Draft): RevisionInput {
  return {
    definitionId: draft.definitionId,
    displayName: draft.displayName,
    slug: draft.slug,
    description: draft.description,
    roleBody: draft.roleBody,
    expectedRowVersion: draft.expectedRowVersion,
  }
}

/**
 * Default assignment intent, user-global or per-project (FR02/US2).
 * `enable` must pin a revision; `inherit` clears this layer's decision;
 * `disable` only ever applies to a managed definition.
 */
export function assignmentIntent(input: {
  readonly definition: DefinitionSummary
  readonly layer: 'user-global' | 'project'
  readonly decision: 'inherit' | 'enable' | 'disable'
  readonly revision?: number | null
  readonly target: TargetStamp
  readonly harnessId?: string
  readonly nonce: string
  readonly rowVersion?: number
}): BuiltIntent {
  const scopeKind = input.layer === 'user-global' ? 'user-global-generic' : 'project-generic'
  const operationKey = `assign:${scopeKind}:${input.definition.definitionId}:${input.rowVersion ?? 0}:${input.nonce}`
  if (input.definition.originScope === 'profile' && input.layer === 'user-global') {
    return { intent: intentOf('assignment', operationKey, input.target, input.definition.definitionId), refusal: 'Profile 专用定义不得进入用户全局默认（仅该 Profile 及其合法同 Harness 会话可用）。' }
  }
  if (input.decision === 'enable' && (input.revision === undefined || input.revision === null)) {
    return { intent: intentOf('assignment', operationKey, input.target, input.definition.definitionId), refusal: '启用必须指向一个已批准的固定修订；未写入分配。' }
  }
  if (input.decision === 'enable' && input.revision !== undefined && input.revision !== null && input.revision > input.definition.latestRevision) {
    return { intent: intentOf('assignment', operationKey, input.target, input.definition.definitionId), refusal: `请求的 v${input.revision} 不存在（当前最新 v${input.definition.latestRevision}）；未写入分配。` }
  }
  const assignment: AssignmentView = {
    serverScope: input.definition.serverScope,
    principal: input.target.serverId,
    scopeKind,
    scopeId: input.layer === 'project' ? input.target.projectId : null,
    harnessId: input.harnessId ?? 'any',
    definitionId: input.definition.definitionId,
    decision: input.decision,
    revision: input.decision === 'enable' ? input.revision ?? null : null,
    rowVersion: input.rowVersion ?? 0,
  }
  return { intent: intentOf('assignment', operationKey, input.target, input.definition.definitionId, assignment), refusal: null }
}

/**
 * US5: a native-discovered item is not ours to mask. When the observation does
 * not establish suppressibility the disable intent is refused with the exact
 * §C5 code, instead of pretending a "disabled" state.
 */
export function nativeDisableIntent(observation: NativeObservation, target: TargetStamp, nonce: string): BuiltIntent {
  const operationKey = `native-disable:${observation.scope}:${observation.nativeName}:${nonce}`
  if (observation.suppressible === true) {
    return { intent: intentOf('assignment', operationKey, target, null), refusal: null }
  }
  return {
    intent: intentOf('assignment', operationKey, target, null),
    refusal: observation.suppressible === false
      ? 'NATIVE_DISCOVERY_UNCONTROLLED：目标原生机制无法屏蔽该项；界面不会把它标成已被关闭，因为它仍在生效。'
      : 'NATIVE_DISCOVERY_UNCONTROLLED：可屏蔽性未确立；不提供该动作，也不谎报屏蔽状态。',
  }
}

// ---------------------------------------------------------------------------
// Effect-scope texts (ux.md §"交互验收": 归档/版本更新对话框明确影响范围)
// ---------------------------------------------------------------------------

export function archiveEffectText(definition: DefinitionSummary, pinned: readonly AssignmentView[]): string {
  const scope = pinned.length === 0
    ? '当前没有任何固定分配引用该定义。'
    : `现有 ${pinned.length} 个固定分配仍指向各自的修订，不会随归档移动：\n${pinned.map(describeAssignment).join('\n')}`
  return [
    `归档"${definition.displayName}"（${definition.definitionId}）的影响范围：`,
    '- 归档后不再出现在新的选择里；',
    '- 已固定的分配与已冻结的会话快照不受影响，历史修订仍可解析（FR01/FR02）；',
    '- 归档不删除正文、来源与批准记录；删除属于另一个数据保留政策，本包不实现。',
    `- ${scope}`,
  ].join('\n')
}

export function revisionNonMovementText(definition: DefinitionSummary, pinned: readonly AssignmentView[]): string {
  const still = pinned.length === 0
    ? '没有固定分配会受影响。'
    : `以下 ${pinned.length} 个分配保持原固定修订不变：\n${pinned.map(describeAssignment).join('\n')}`
  return [
    `发布新修订到"${definition.displayName}"（当前 v${definition.latestRevision} → 新 v${definition.latestRevision + 1}）：`,
    '- 修订不可变，新版本不写回旧版本；',
    '- 现有固定版分配不会移动，逐个升级需单独批准（FR02）；',
    '- 不自动启用：存内容与应用到某个项目/Profile 是两件事。',
    `- ${still}`,
  ].join('\n')
}

export function describeAssignment(a: AssignmentView): string {
  const scope = a.scopeId === null ? a.scopeKind : `${a.scopeKind}=${a.scopeId}`
  const pin = a.revision === null || a.revision === undefined ? '' : `@v${a.revision}`
  return `  · ${scope} / harness=${a.harnessId} → ${a.definitionId}${pin}（rowVersion=${a.rowVersion}）`
}

// ---------------------------------------------------------------------------
// Revision diff (pure; reachable by keyboard through the view builder)
// ---------------------------------------------------------------------------

export function revisionDiff(from: DefinitionRevisionContent, to: DefinitionRevisionContent): readonly DiffLine[] {
  const header: DiffLine[] = [
    { kind: 'context', text: `v${from.revision} (${shortDigest(from.contentDigest)}) → v${to.revision} (${shortDigest(to.contentDigest)})` },
    { kind: 'context', text: `声明模型：${refText(from.declaredModelRef)} → ${refText(to.declaredModelRef)}` },
    { kind: 'context', text: `工具引用：${from.toolRefs?.length ?? 0} 条 → ${to.toolRefs?.length ?? 0} 条（仅声明，不代表授权）` },
  ]
  return [...header, ...lineDiff(from.roleBody.split('\n'), to.roleBody.split('\n'))]
}

export function shortDigest(digest: string): string {
  return digest.startsWith('sha256:') ? `sha256:${digest.slice(7, 15)}…` : digest.slice(0, 12)
}

function refText(ref: ResourceRef | null | undefined): string {
  if (!ref) return '未声明'
  return `${ref.ownerId}${ref.revision ? `@${ref.revision}` : ''}`
}

/** Order-preserving line LCS diff; no heuristics, no dependency. */
export function lineDiff(a: readonly string[], b: readonly string[]): readonly DiffLine[] {
  const n = a.length, m = b.length
  const table: number[][] = Array.from({ length: n + 1 }, () => new Array<number>(m + 1).fill(0))
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      table[i]![j] = a[i] === b[j] ? table[i + 1]![j + 1]! + 1 : Math.max(table[i + 1]![j]!, table[i]![j + 1]!)
    }
  }
  const out: DiffLine[] = []
  let i = 0, j = 0
  while (i < n && j < m) {
    if (a[i] === b[j]) { out.push({ kind: 'context', text: a[i]! }); i++; j++ }
    else if (table[i + 1]![j]! >= table[i]![j + 1]!) { out.push({ kind: 'removed', text: a[i]! }); i++ }
    else { out.push({ kind: 'added', text: b[j]! }); j++ }
  }
  while (i < n) { out.push({ kind: 'removed', text: a[i]! }); i++ }
  while (j < m) { out.push({ kind: 'added', text: b[j]! }); j++ }
  return out
}

// ---------------------------------------------------------------------------
// Row / origin selectors
// ---------------------------------------------------------------------------

export type RowOrigin = 'mine' | 'project' | 'profile-only' | 'native-discovered' | 'shared'

const ORIGIN_LABELS: Record<RowOrigin, string> = {
  mine: '我的',
  project: '项目',
  'profile-only': 'Profile 专用',
  'native-discovered': '仅原生发现',
  shared: '公共（他人来源）',
}

export function originLabel(origin: RowOrigin): string {
  return ORIGIN_LABELS[origin]
}

export function rowOrigin(definition: DefinitionSummary, viewerPrincipal: string): RowOrigin {
  if (definition.originScope === 'project') return 'project'
  if (definition.originScope === 'profile') return 'profile-only'
  return definition.originOwner === viewerPrincipal ? 'mine' : 'shared'
}

export interface RowView {
  readonly id: string
  readonly kind: 'managed' | 'native'
  readonly origin: RowOrigin
  readonly displayName: string
  readonly slug: string
  readonly archived: boolean
  readonly latestRevision: number
  readonly lastApprovedSource: string | null
  readonly readOnly: boolean
  readonly brands: readonly BrandCapability[]
  readonly native: NativeObservation | null
  readonly disableLabel: string | null
}

/**
 * The list rows after the origin filter (ux.md §"Settings 中的定义库").
 * Native-discovered items appear under `all` and `native-discovered` only, and
 * are always read-only.
 */
export function visibleRows(state: SettingsState): readonly RowView[] {
  const managed: RowView[] = (state.list.data ?? [])
    .filter(row => state.showArchived || !row.archived)
    .map(row => ({
      id: row.definitionId,
      kind: 'managed' as const,
      origin: rowOrigin(row, state.viewerPrincipal),
      displayName: row.displayName,
      slug: row.slug,
      archived: row.archived,
      latestRevision: row.latestRevision,
      lastApprovedSource: row.lastApprovedSource
        ? `${row.lastApprovedSource.origin}:${shortDigest(row.lastApprovedSource.contentDigest)}`
        : null,
      readOnly: false,
      brands: row.capabilities ?? [],
      native: null,
      disableLabel: null,
    }))
  const nativeRows: RowView[] = nativeObservations(state).map(obs => ({
    id: `native:${obs.scope}:${obs.nativeName}`,
    kind: 'native' as const,
    origin: 'native-discovered' as const,
    displayName: obs.nativeName,
    slug: obs.nativeName,
    archived: false,
    latestRevision: 0,
    lastApprovedSource: null,
    readOnly: true,
    brands: [],
    native: obs,
    // US5: never "已禁用" — only what the observation actually established.
    disableLabel: obs.suppressible === true
      ? '可屏蔽'
      : obs.suppressible === false
        ? '无法屏蔽（原生发现不受控）'
        : '可屏蔽性未验证',
  }))
  const all = [...managed, ...nativeRows]
  if (state.originFilter === 'all') return all
  if (state.originFilter === 'native-discovered') return nativeRows
  // 'mine' is strictly the viewer's own rows; another principal's public rows
  // are only reachable through 'all' (never claimed as the viewer's).
  return all.filter(row => row.origin === state.originFilter)
}

export function nativeObservations(state: SettingsState): readonly NativeObservation[] {
  const slice = state.native
  if (slice.status !== 'ready' || slice.data === null) return []
  return slice.data.state === 'observed' ? slice.data.observations : []
}

/** FR07: an absent observation mechanism is `unknown`, never an empty list. */
export function nativeUnknownReason(state: SettingsState): string | null {
  const slice = state.native
  if (slice.status !== 'ready' || slice.data === null) return null
  return slice.data.state === 'unknown' ? slice.data.reason : null
}

export function selectedRow(state: SettingsState): RowView | null {
  if (state.selection === null) return null
  return visibleRows(state).find(r => r.id === state.selection) ?? null
}

/** The 6 resolution layers (ruling C1); exported for the defaults renderer. */
export const DEFAULT_LAYERS = ASSIGNMENT_LAYERS
export const FACET = FACET_ID
