/**
 * The DOM-free controller that owns the port calls for the definition library.
 *
 * Every request captures the *current* target stamp and echoes it back on the
 * result; the reducer in `model.ts` then drops a response whose stamp is no
 * longer the current target (§C2, G15 "另一服务晚响应覆盖"). Nothing here touches
 * a socket, a file, a CLI or a timer of its own — the port is injected, and when
 * it is absent the store renders an explained absence instead of faking data.
 */
import type {
  AssignmentView, DefinitionDetail, DefinitionSummary, ListQuery, RevisionInput, ServiceResult,
  SubagentDefinitionServicePort, TargetStamp,
} from './contract'
import type { Action, BuiltIntent, Draft, DraftField, SettingsState } from './model'
import {
  archiveEffectText, archiveIntent, assignmentIntent, cloneIntent, importApprovalPaths, initialState, nativeDisableIntent,
  reduce, revisionDiff, revisionInput, revisionNonMovementText, saveRevisionIntent, selectedRow,
} from './model'
import type { ViewAttrs } from './view'

export interface SettingsStore {
  getState(): SettingsState
  subscribe(listener: () => void): () => void
  dispatch(action: Action): void
  /** The single entry point the renderer binds to `data-action` attributes. */
  activate(action: string, attrs: ViewAttrs): void
  reload(): void
}

export interface StoreDependencies {
  readonly port: SubagentDefinitionServicePort | null
  readonly target: TargetStamp
  readonly viewerPrincipal: string
  /** Injectable nonce so operation keys are deterministic in tests. */
  readonly newNonce?: () => string
}

export function createSettingsStore(deps: StoreDependencies): SettingsStore {
  let state = initialState({
    target: deps.target,
    viewerPrincipal: deps.viewerPrincipal,
    serviceAvailable: deps.port !== null,
  })
  const listeners = new Set<() => void>()
  let nonceCounter = 0
  const nonce = () => deps.newNonce?.() ?? `n${(++nonceCounter)}`

  const publish = (): void => { for (const l of [...listeners]) l() }

  const dispatch = (action: Action): void => {
    const next = reduce(state, action)
    if (next === state) return
    state = next
    publish()
  }

  /**
   * Issue one port call. The stamp is captured *before* the await; whatever the
   * port returns is dispatched under that same stamp, so a target switch in the
   * meantime makes the reducer drop it rather than land it on the new target.
   */
  async function call<T>(
    request: (port: SubagentDefinitionServicePort) => Promise<ServiceResult<T>>,
    toAction: (stamp: TargetStamp, result: ServiceResult<T>) => Action,
  ): Promise<void> {
    const port = deps.port
    if (port === null) return
    const stamp = state.target
    try {
      dispatch(toAction(stamp, await request(port)))
    } catch {
      // A transport-level surprise is an OPERATION_UNKNOWN, never a silent success.
      dispatch(toAction(stamp, { ok: false, stamp, error: { code: 'OPERATION_UNKNOWN', detail: '服务调用未完成；未回退为静默成功' } }))
    }
  }

  const listQueryOf = (s: SettingsState): ListQuery => ({
    includeArchived: s.showArchived,
    // The native filter is a UI-side view; the service still lists managed rows.
    originFilter: s.originFilter === 'native-discovered' ? 'all' : s.originFilter,
  })

  const loadList = (): void => {
    const stamp = state.target
    const query = listQueryOf(state)
    dispatch({ type: 'list/request' })
    void call(port => port.listDefinitions(stamp, query), (s, result) => ({ type: 'list/result', stamp: s, result }))
  }

  const loadDetail = (definitionId: string): void => {
    const stamp = state.target
    dispatch({ type: 'detail/request', definitionId })
    void call(port => port.getDefinition(stamp, definitionId), (s, result) => ({ type: 'detail/result', definitionId, stamp: s, result }))
  }

  const loadNative = (): void => {
    const stamp = state.target
    dispatch({ type: 'native/request' })
    void call(port => port.inspectNative(stamp), (s, result) => ({ type: 'native/result', stamp: s, result }))
  }

  const loadEffective = (): void => {
    const stamp = state.target
    const pins: readonly (readonly [string, number])[] = (state.detail.data?.pinnedAssignments ?? [])
      .filter(a => a.revision !== null && a.revision !== undefined)
      .map(a => [a.definitionId, a.revision as number] as const)
    dispatch({ type: 'effective/request' })
    void call(port => port.resolvePreview(stamp, pins), (s, result) => ({ type: 'effective/result', stamp: s, result }))
  }

  const loadAssignments = (layer: 'user-global' | 'project'): void => {
    const stamp = state.target
    dispatch({ type: 'assignments/request', layer })
    void call(
      port => port.listAssignments(stamp, { projectId: layer === 'project' ? stamp.projectId : null }),
      (s, result) => ({ type: 'assignments/result', layer, stamp: s, result }),
    )
  }

  const reload = (): void => {
    if (deps.port === null) {
      // Service absence is an explained state, not an endless loading spinner.
      state = initialState({ target: state.target, viewerPrincipal: state.viewerPrincipal, serviceAvailable: false })
      publish()
      return
    }
    loadList()
    loadNative()
    loadAssignments('user-global')
    loadAssignments('project')
  }

  const runIntent = (
    built: BuiltIntent,
    execute: (port: SubagentDefinitionServicePort, intent: BuiltIntent['intent'], input: RevisionInput | null) => Promise<ServiceResult<DefinitionSummary>>,
  ): void => {
    dispatch({ type: 'mutation/request', intent: built.intent, refusal: built.refusal })
    if (built.refusal !== null || deps.port === null) return
    const input = state.draft === null ? null : revisionInput(state.draft)
    void call(
      port => execute(port, built.intent, input),
      (s, result) => ({ type: 'mutation/result', operationKey: built.intent.operationKey, kind: built.intent.kind, stamp: s, result }),
    )
  }

  const runAssignmentIntent = (built: BuiltIntent): void => {
    dispatch({ type: 'mutation/request', intent: built.intent, refusal: built.refusal })
    if (built.refusal !== null || deps.port === null || built.intent.assignment === null) return
    const assignment = built.intent.assignment
    void call(
      port => port.approveAssignmentUpdate({ stamp: built.intent.stamp, assignment, expectedRowVersion: assignment.rowVersion, operationKey: built.intent.operationKey }),
      (s, result) => ({ type: 'assignment-mutation/result', operationKey: built.intent.operationKey, stamp: s, result }),
    )
  }

  const managedSelected = (): DefinitionSummary | null => {
    const row = selectedRow(state)
    if (row === null || row.kind !== 'managed') return null
    return (state.list.data ?? []).find(d => d.definitionId === row.id) ?? null
  }

  const pinnedOf = (): readonly AssignmentView[] => state.detail.data?.pinnedAssignments ?? []

  function activate(action: string, attrs: ViewAttrs): void {
    switch (action) {
      case 'reload':
      case 'retry':
        reload()
        return
      case 'filter-origin': {
        const filter = attrs['data-origin-filter'] as ListQuery['originFilter'] | undefined
        if (filter) dispatch({ type: 'filter/origin', filter })
        return
      }
      case 'toggle-archived':
        dispatch({ type: 'filter/archived', show: !state.showArchived })
        return
      case 'select-row': {
        const id = String(attrs['data-row-id'] ?? '')
        if (id === '') return
        dispatch({ type: 'detail/select', definitionId: id })
        if (!id.startsWith('native:')) loadDetail(id)
        return
      }
      case 'inspect-native':
        loadNative()
        return
      case 'resolve-preview':
        loadEffective()
        return
      case 'load-assignments':
        loadAssignments(attrs['data-layer'] === 'project' ? 'project' : 'user-global')
        return
      case 'draft-new':
        dispatch({ type: 'draft/start', definitionId: null })
        return
      case 'draft-open': {
        const target = managedSelected()
        if (target === null) return
        dispatch({ type: 'draft/start', definitionId: target.definitionId })
        return
      }
      case 'draft-edit': {
        const field = String(attrs['data-field'] ?? '') as DraftField
        dispatch({ type: 'draft/edit', field, value: String(attrs['data-value'] ?? '') })
        return
      }
      case 'discard-draft':
        dispatch({ type: 'draft/discard' })
        return
      case 'open-archive': {
        const target = managedSelected()
        if (target === null) return
        dispatch({ type: 'dialog/open', dialog: { kind: 'archive', definitionId: target.definitionId, effectText: archiveEffectText(target, pinnedOf()), pinned: pinnedOf() } })
        return
      }
      case 'open-publish': {
        const target = managedSelected()
        if (target === null) return
        dispatch({ type: 'dialog/open', dialog: { kind: 'publish-revision', definitionId: target.definitionId, nonMovementText: revisionNonMovementText(target, pinnedOf()), pinned: pinnedOf() } })
        return
      }
      case 'open-clone': {
        const target = managedSelected()
        if (target === null) return
        dispatch({ type: 'dialog/open', dialog: { kind: 'clone', definitionId: target.definitionId, revision: target.latestRevision } })
        return
      }
      case 'open-restore': {
        const target = managedSelected()
        if (target === null) return
        dispatch({ type: 'dialog/open', dialog: { kind: 'restore', definitionId: target.definitionId } })
        return
      }
      case 'open-diff': {
        const d = state.detail.data
        if (d === null || d.revisions.length < 2) return
        const to = d.revisions[d.revisions.length - 1]
        const from = d.revisions[d.revisions.length - 2]
        if (!from || !to) return
        dispatch({ type: 'dialog/open', dialog: { kind: 'revision-diff', definitionId: d.definitionId, from: from.revision, to: to.revision, lines: revisionDiff(from, to) } })
        return
      }
      case 'close-dialog':
        // Abandoning the dialog keeps the draft; the reducer guarantees it.
        dispatch({ type: 'dialog/close' })
        return
      case 'confirm-archive': {
        const target = state.detail.data ?? managedSelected()
        if (target === null) return
        runIntent(archiveIntent(target, state.target, nonce()), (port, intent) =>
          port.archive({ stamp: intent.stamp, definitionId: target.definitionId, expectedRowVersion: target.rowVersion, operationKey: intent.operationKey }))
        return
      }
      case 'confirm-restore': {
        const target = state.detail.data ?? managedSelected()
        if (target === null) return
        runIntent(restoreIntentChecked(target, state.target, nonce()), (port, intent) =>
          port.restore({ stamp: intent.stamp, definitionId: target.definitionId, expectedRowVersion: target.rowVersion, operationKey: intent.operationKey }))
        return
      }
      case 'confirm-clone': {
        const target = state.detail.data ?? managedSelected()
        if (target === null) return
        runIntent(cloneIntent(target, target.latestRevision, state.target, nonce()), (port, intent) =>
          port.clone({ stamp: intent.stamp, definitionId: target.definitionId, revision: target.latestRevision, expectedRowVersion: target.rowVersion, operationKey: intent.operationKey }))
        return
      }
      case 'confirm-publish': {
        const draft: Draft | null = state.draft
        if (draft === null) return
        const content = revisionInput(draft)
        const built = saveRevisionIntent(draft, content, state.target, nonce())
        runIntent(built, (port, intent, input) => {
          const seed = input ?? content
          return intent.definitionId === null
            ? port.createDefinition({ stamp: intent.stamp, seed, operationKey: intent.operationKey })
            : port.saveRevision({ stamp: intent.stamp, revision: seed, operationKey: intent.operationKey })
        })
        return
      }
      case 'assign': {
        const target = managedSelected()
        if (target === null) return
        const layer = attrs['data-layer'] === 'project' ? 'project' : 'user-global'
        const raw = attrs['data-decision']
        const decision = raw === 'enable' ? 'enable' : raw === 'disable' ? 'disable' : 'inherit'
        const existing: readonly AssignmentView[] = (layer === 'project' ? state.defaults['project'].data : state.defaults['user-global'].data) ?? []
        const row = existing.find(a => a.definitionId === target.definitionId && a.scopeKind.startsWith(layer))
        runAssignmentIntent(assignmentIntent({
          definition: target, layer, decision,
          revision: decision === 'enable' ? target.latestRevision : null,
          target: state.target, nonce: nonce(), rowVersion: row?.rowVersion ?? 0,
        }))
        return
      }
      case 'native-disable': {
        const row = selectedRow(state)
        if (row?.native) runAssignmentIntent(nativeDisableIntent(row.native, state.target, nonce()))
        return
      }
      case 'import-source':
        dispatch({ type: 'import/source', sourceRef: String(attrs['data-value'] ?? '') })
        return
      case 'import-preview': {
        const stamp = state.target
        const sourceRef = state.importFlow.sourceRef
        dispatch({ type: 'import/preview-request' })
        void call(port => port.importPreview({ stamp, sourceRef }), (s, result) => ({ type: 'import/preview-result', stamp: s, result }))
        return
      }
      case 'toggle-import-path':
        dispatch({ type: 'import/toggle-path', relativePath: String(attrs['data-path'] ?? '') })
        return
      case 'import-approve': {
        const preview = state.importFlow.preview
        const paths = importApprovalPaths(state.importFlow)
        const operationKey = `import:${preview?.previewId ?? 'none'}:${paths.join('|')}:${nonce()}`
        dispatch({ type: 'import/approve-request', operationKey })
        if (preview === null || paths.length === 0) return
        const stamp = state.target
        const previewId = preview.previewId
        void call(port => port.approveImport({ stamp, previewId, selectPaths: paths, operationKey }),
          (s, result) => ({ type: 'import/approve-result', operationKey, stamp: s, result }))
        return
      }
      case 'dismiss-notice': {
        const key = attrs['data-notice-key']
        if (typeof key === 'string') dispatch({ type: 'notice/dismiss', id: key })
        return
      }
      default:
        return
    }
  }

  return {
    getState: () => state,
    subscribe: listener => { listeners.add(listener); return () => { listeners.delete(listener) } },
    dispatch,
    activate,
    reload,
  }
}

/** A restore is only ever issued for an archived row; the refusal text is explicit. */
export function restoreIntentChecked(definition: DefinitionSummary | DefinitionDetail, target: TargetStamp, nonce: string): BuiltIntent {
  const operationKey = `restore:${definition.definitionId}:${definition.rowVersion}:${nonce}`
  if (!definition.archived) {
    return { intent: { operationKey, kind: 'restore', stamp: target, definitionId: definition.definitionId, assignment: null }, refusal: '该定义未归档，恢复动作不适用；未写入任何状态。' }
  }
  return { intent: { operationKey, kind: 'restore', stamp: target, definitionId: definition.definitionId, assignment: null }, refusal: null }
}
