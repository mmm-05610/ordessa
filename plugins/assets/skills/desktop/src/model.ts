/**
 * The Skills settings model: content library, the two assignment layers, and
 * native discovery, with the unsaved draft kept strictly apart from stored
 * rows.
 *
 * Rules this file is responsible for (ux.md §Settings, verification.md G14):
 *
 * * 本层设置 comes from the layer's own stored row (or its draft), 最终结果
 *   comes from `resolve` — two different fields on a row, so no single master
 *   switch can stand in for the other;
 * * a request failure sets an error and leaves the draft untouched;
 * * a CAS conflict is a *value*, not an exception: the draft survives, the
 *   server revision is remembered, and the surface offers a re-read instead of
 *   overwriting;
 * * a missing or unauthorized project stops editing (no write is issued at all)
 *   while stored rows stay displayed, because 已存记录 must survive until the
 *   project returns or the user cleans it up explicitly;
 * * native observations never enter the draft map — they are not manageable.
 */
import type { AssignmentQuery, ProjectEntry, SkillsGateway, WorkspaceListPort } from '../../contracts/src/gateway'
import type {
  AssignmentDraft, AssignmentLayer, AssignmentRow, AssignmentViewRow, Decision, EffectiveView,
  ImportPreview, NativeDiscoveryItem, OriginScope, PickedFile, PreviewContent, ResolveTarget,
  RevisionDiff, SkillRecordView, SkillRevisionRow, SourceRow, WriteResult,
} from '../../contracts/src/skills'
import { sha256Hex } from './sha256'

export type LayerKey = 'global' | 'project'
export type AreaState = 'unknown' | 'loading' | 'ready' | 'error'

export interface DraftEntry { draft: AssignmentDraft; operationKey: string }

export interface ImportOwner { originScope: OriginScope; originOwner: string | null }

export type ImportPhase =
  | { kind: 'idle' }
  | { kind: 'transferring'; importId: string; sent: number; total: number }
  | { kind: 'prepared'; importId: string; preview: ImportPreview; owner: ImportOwner }
  | { kind: 'committed'; assetId: string; revision: number }
  | { kind: 'failed'; message: string }

export interface Area<T> { state: AreaState; error: string | null; items: T | null }

export interface LibraryDetail {
  assetId: string
  state: AreaState
  error: string | null
  revisions: SkillRevisionRow[] | null
  diff: RevisionDiff | null
  preview: PreviewContent | null
  loadingPreview: boolean
}

export interface LayerState {
  key: LayerKey
  /** null = "所有 Harness". */
  harnessId: string | null
  projectId: string | null
  state: AreaState
  error: string | null
  storedRows: readonly AssignmentRow[]
  effective: EffectiveView | null
  rows: AssignmentViewRow[]
  assignmentRevision: number
  draft: Record<string, DraftEntry>
  conflict: { message: string; serverRevision: number } | null
  saving: boolean
  /** Editing is refused here (project gone/unauthorized); reads stay live. */
  editable: boolean
  stopReason: string | null
  /** Draft-only preview from `previewEffective`; never a stored fact. */
  preview: EffectiveView | null
}

export interface SkillsSnapshot {
  status: 'idle' | 'loading' | 'ready' | 'error'
  error: string | null
  library: Area<SkillRecordView[] | null>
  sources: Area<SourceRow[]>
  projects: Area<ProjectEntry[]>
  native: Area<NativeDiscoveryItem[]>
  selectedAssetId: string | null
  detail: LibraryDetail | null
  global: LayerState
  project: LayerState
  importPhase: ImportPhase
}

export interface SkillsModel {
  subscribe(listener: () => void): () => void
  getSnapshot(): SkillsSnapshot
  refresh(): Promise<void>
  // —— 内容库 ——
  selectAsset(assetId: string | null): void
  loadPreview(assetId: string, revision: number, path: string): Promise<void>
  checkUpdate(assetId: string): Promise<void>
  approveRevision(assetId: string, revision: number): Promise<void>
  importPicked(files: PickedFile[], origin: string, owner: ImportOwner): Promise<void>
  confirmImport(): Promise<void>
  cancelImport(): Promise<void>
  // —— 默认启用 / 项目启用 ——
  setHarness(key: LayerKey, harnessId: string | null): Promise<void>
  setProject(projectId: string | null): Promise<void>
  edit(key: LayerKey, assetId: string, decision: Decision, revision?: number | null): void
  discard(key: LayerKey, assetId?: string): void
  save(key: LayerKey): Promise<void>
  reRead(key: LayerKey): Promise<void>
  previewDraft(key: LayerKey): Promise<void>
  loadNative(harnessId: string, runtimeVersion: string, projectId: string | null): Promise<void>
}

const emptyLayer = (key: LayerKey): LayerState => ({
  key, harnessId: null, projectId: null, state: 'unknown', error: null,
  storedRows: [], effective: null, rows: [], assignmentRevision: 0, draft: {},
  conflict: null, saving: false, editable: true, stopReason: null, preview: null,
})

const layerOf = (state: LayerState): AssignmentLayer =>
  state.key === 'global'
    ? { kind: 'user-global', scopeId: null, harnessId: state.harnessId }
    : { kind: 'project', scopeId: state.projectId, harnessId: state.harnessId }

const targetOf = (state: LayerState): ResolveTarget => ({
  projectId: state.key === 'project' ? state.projectId : null,
  harnessId: state.harnessId,
  profileId: null,
})

export function createSkillsModel(gateway: SkillsGateway, workspaces: WorkspaceListPort): SkillsModel {
  let snapshot: SkillsSnapshot = {
    status: 'idle', error: null,
    library: { state: 'unknown', error: null, items: null },
    sources: { state: 'unknown', error: null, items: null },
    projects: { state: 'unknown', error: null, items: null },
    native: { state: 'unknown', error: null, items: null },
    selectedAssetId: null, detail: null,
    global: emptyLayer('global'), project: emptyLayer('project'),
    importPhase: { kind: 'idle' },
  }
  const listeners = new Set<() => void>()
  const publish = () => { for (const listener of listeners) listener() }
  const patch = (part: Partial<SkillsSnapshot>) => { snapshot = { ...snapshot, ...part }; publish() }
  const patchLayer = (key: LayerKey, part: Partial<LayerState>) => {
    snapshot = { ...snapshot, [key]: { ...snapshot[key], ...part } }
    publish()
  }
  const layer = (key: LayerKey) => snapshot[key]

  /** Records visible to one layer, keyed by assetId. `skills.list` applied the
   * ownership rule server-side (G07); the client never filters by name. */
  const visible = new Map<LayerKey, Map<string, SkillRecordView>>()

  const approvedRevisionOf = (assetId: string) =>
    (snapshot.library.items ?? []).find(item => item.assetId === assetId)?.approvedRevision ?? null

  const rebuild = (key: LayerKey) => {
    const state = layer(key)
    const seen = visible.get(key) ?? new Map<string, SkillRecordView>()
    const ids = [...new Set([
      ...seen.keys(), ...state.storedRows.map(row => row.assetId), ...Object.keys(state.draft),
    ])]
    const byAsset = new Map(state.storedRows.map(row => [row.assetId, row]))
    const rows: AssignmentViewRow[] = ids.map(assetId => {
      const record = seen.get(assetId) ?? null
      const resolved = state.effective?.resolved.find(item => item.assetId === assetId) ?? null
      return {
        assetId,
        nativeName: record?.nativeName ?? resolved?.nativeName ?? assetId,
        originScope: record?.originScope ?? resolved?.originScope ?? 'public',
        archived: record?.archived ?? false,
        layerRow: byAsset.get(assetId) ?? null,
        draft: state.draft[assetId]?.draft ?? null,
        effective: resolved,
        approvedRevision: record?.approvedRevision ?? null,
      }
    })
    // Stable order (name, then id) so a re-read never shuffles the keyboard
    // cursor out from under the focused row.
    rows.sort((a, b) => a.nativeName.localeCompare(b.nativeName) || a.assetId.localeCompare(b.assetId))
    patchLayer(key, { rows })
  }

  /** Whether the layer may be written right now, with the reason it may not. */
  const editability = (state: LayerState): { editable: boolean; stopReason: string | null } => {
    if (state.key !== 'project') return { editable: true, stopReason: null }
    if (state.projectId === null) return { editable: false, stopReason: '尚未选择项目' }
    if (snapshot.projects.items === null) {
      return { editable: false, stopReason: 'Workspace 项目状态未确认：暂停编辑，已存分配保留' }
    }
    const entry = snapshot.projects.items.find(item => item.projectId === state.projectId)
    if (entry?.state === 'available') return { editable: true, stopReason: null }
    return {
      editable: false,
      stopReason: entry === undefined ? '项目不再获授权：停止编辑，已存分配保留' : '项目已缺失：停止编辑，已存分配保留',
    }
  }

  const refreshLayer = async (key: LayerKey) => {
    const current = layer(key)
    const gate = editability(current)
    if (key === 'project' && current.projectId === null) {
      patchLayer(key, { state: 'ready', error: null, ...gate, rows: [] })
      return
    }
    patchLayer(key, { state: 'loading', error: null })
    const query: AssignmentQuery = { layer: layerOf(current) }
    try {
      const [assignmentList, effective, listable] = await Promise.all([
        gateway.assignmentsList(query), gateway.resolve(targetOf(current)), gateway.list(targetOf(current)),
      ])
      visible.set(key, new Map(listable.map(record => [record.assetId, record])))
      // The draft is deliberately NOT re-read from the server: it stays while
      // stored rows refresh around it.
      patchLayer(key, {
        state: 'ready', error: null,
        storedRows: assignmentList.rows, effective,
        assignmentRevision: assignmentList.assignmentRevision,
        ...gate,
      })
      rebuild(key)
    } catch (failure) {
      // Last good rows plus the draft survive an error; only the banner moves.
      patchLayer(key, { state: 'error', error: String(failure), ...editability(layer(key)) })
    }
  }

  const refreshLibrary = async () => {
    patch({ library: { ...snapshot.library, state: 'loading', error: null } })
    try {
      patch({ library: { state: 'ready', error: null, items: await gateway.catalogue() } })
    } catch (failure) {
      patch({ library: { ...snapshot.library, state: 'error', error: String(failure) } })
    }
  }

  const refreshSources = async () => {
    patch({ sources: { ...snapshot.sources, state: 'loading', error: null } })
    try {
      patch({ sources: { state: 'ready', error: null, items: await gateway.sources() } })
    } catch (failure) {
      patch({ sources: { ...snapshot.sources, state: 'error', error: String(failure) } })
    }
  }

  const refreshProjects = async () => {
    patch({ projects: { ...snapshot.projects, state: 'loading', error: null } })
    try {
      const items = await workspaces.listProjects()
      snapshot = { ...snapshot, projects: { state: 'ready', error: null, items } }
      // A project that disappeared mid-edit flips its layer to read-only, and
      // nothing else changes: stored rows and drafts both stay.
      for (const key of ['global', 'project'] as const) patchLayer(key, editability(layer(key)))
    } catch (failure) {
      patch({ projects: { ...snapshot.projects, state: 'error', error: String(failure) } })
    }
  }

  const newDetail = (assetId: string): LibraryDetail =>
    ({ assetId, state: 'loading', error: null, revisions: null, diff: null, preview: null, loadingPreview: false })

  const loadDiffIfCandidate = async (assetId: string): Promise<RevisionDiff | null> => {
    const record = (snapshot.library.items ?? []).find(item => item.assetId === assetId)
    if (record === undefined || record.updateCandidateRevision === null) return null
    return gateway.diff(assetId, record.approvedRevision ?? record.latestInstalledRevision, record.updateCandidateRevision)
  }

  const model: SkillsModel = {
    subscribe(listener) { listeners.add(listener); return () => { listeners.delete(listener) } },
    getSnapshot: () => snapshot,

    async refresh() {
      patch({ status: 'loading', error: null })
      await Promise.all([refreshLibrary(), refreshSources(), refreshProjects()])
      await Promise.all([refreshLayer('global'), refreshLayer('project')])
      patch({ status: 'ready' })
    },

    selectAsset(assetId) {
      patch({
        selectedAssetId: assetId,
        detail: assetId === null ? null : newDetail(assetId),
      })
      if (assetId === null) return
      void (async () => {
        try {
          const [revisions, diff] = await Promise.all([gateway.revisions(assetId), loadDiffIfCandidate(assetId)])
          if (snapshot.detail?.assetId !== assetId) return
          snapshot = { ...snapshot, detail: { ...snapshot.detail, state: 'ready', revisions, diff } }
        } catch (failure) {
          if (snapshot.detail?.assetId !== assetId) return
          snapshot = { ...snapshot, detail: { ...snapshot.detail, state: 'error', error: String(failure) } }
        }
        publish()
      })()
    },

    async loadPreview(assetId, revision, path) {
      if (snapshot.detail?.assetId !== assetId) return
      snapshot = { ...snapshot, detail: { ...snapshot.detail, loadingPreview: true, error: null } }
      publish()
      try {
        const preview = await gateway.preview(assetId, revision, path)
        if (snapshot.detail?.assetId !== assetId) return
        snapshot = { ...snapshot, detail: { ...snapshot.detail, preview, loadingPreview: false } }
      } catch (failure) {
        if (snapshot.detail?.assetId !== assetId) return
        snapshot = { ...snapshot, detail: { ...snapshot.detail, loadingPreview: false, error: String(failure) } }
      }
      publish()
    },

    async checkUpdate(assetId) {
      patch({ sources: { ...snapshot.sources, state: 'loading', error: null } })
      try {
        const refreshed = await gateway.checkUpdate(assetId)
        const items = (snapshot.sources.items ?? []).map(row => row.assetId === refreshed.assetId ? refreshed : row)
        patch({ sources: { state: 'ready', error: null, items } })
        await refreshLibrary()
      } catch (failure) {
        patch({ sources: { ...snapshot.sources, state: 'error', error: String(failure) } })
      }
    },

    async approveRevision(assetId, revision) {
      // Approval publishes a revision; it must not move any binding (FR07), so
      // only the library surfaces are re-read — never the assignment layers.
      try {
        const result = await gateway.approveRevision(assetId, revision, `approve:${assetId}:${revision}`)
        if (result.kind === 'conflict') { patch({ error: `审批未生效：${result.message}` }); return }
        await refreshLibrary()
      } catch (failure) {
        patch({ error: String(failure) })
      }
    },

    async importPicked(files, origin, owner) {
      const declared = await Promise.all([...files].map(async file =>
        ({ path: file.path, bytes: file.bytes.byteLength, sha256: sha256Hex(file.bytes) })))
      const total = declared.reduce((sum, file) => sum + file.bytes, 0)
      const byPath = new Map(declared.map(entry => [entry.path, entry]))
      let opened: { importId: string }
      try {
        opened = await gateway.importBegin(declared, total)
      } catch (failure) {
        patch({ importPhase: { kind: 'failed', message: String(failure) } })
        return
      }
      const importId = opened.importId
      patch({ importPhase: { kind: 'transferring', importId, sent: 0, total: declared.length } })
      const ordered = [...files].sort((a, b) => a.path < b.path ? -1 : 1)
      try {
        for (let index = 0; index < ordered.length; index++) {
          await gateway.importChunk(importId, index, ordered[index].bytes, byPath.get(ordered[index].path)!.sha256)
          patch({ importPhase: { kind: 'transferring', importId, sent: index + 1, total: ordered.length } })
        }
        const preview = await gateway.importPreview(importId, { type: 'local-transfer', origin })
        patch({ importPhase: { kind: 'prepared', importId, preview, owner } })
      } catch (refusal) {
        // A failed staging cancels its transfer and touches neither the
        // library nor any binding.
        await gateway.importCancel(importId).catch(() => undefined)
        patch({ importPhase: { kind: 'failed', message: String(refusal) } })
      }
    },

    async confirmImport() {
      const phase = snapshot.importPhase
      if (phase.kind !== 'prepared') return
      const existing = (snapshot.library.items ?? []).find(item => item.nativeName === phase.preview.name) ?? null
      try {
        const committed = await gateway.importCommit(phase.importId, {
          assetId: existing?.assetId ?? null,
          originScope: phase.owner.originScope,
          originOwner: phase.owner.originOwner,
          // One operation key per staged transfer: a retry cannot publish twice.
          operationKey: `import:${phase.importId}`,
          expectedVersion: existing?.latestInstalledRevision ?? 0,
        })
        // The only honest sentence available here: publishing proved storage.
        patch({ importPhase: { kind: 'committed', assetId: committed.assetId, revision: committed.revision } })
        await refreshLibrary()
      } catch (refusal) {
        patch({ importPhase: { kind: 'failed', message: String(refusal) } })
      }
    },

    async cancelImport() {
      const phase = snapshot.importPhase
      if (phase.kind === 'prepared' || phase.kind === 'transferring') {
        await gateway.importCancel(phase.importId).catch(() => undefined)
      }
      patch({ importPhase: { kind: 'idle' } })
    },

    async setHarness(key, harnessId) {
      // A scope switch keeps this layer's draft (unsaved choices belong to the
      // user) and never touches the other layer.
      patchLayer(key, { harnessId })
      await refreshLayer(key)
    },

    async setProject(projectId) {
      patchLayer('project', { projectId, state: 'unknown' })
      await refreshLayer('project')
    },

    edit(key, assetId, decision, revision = null) {
      const state = layer(key)
      if (!state.editable) {
        // New choices are refused while the layer is read-only — said in the
        // error slot, never accepted into a draft the user then trusts.
        patchLayer(key, { error: state.stopReason ?? '本层当前不可编辑' })
        return
      }
      const draft: AssignmentDraft = {
        assetId, layer: layerOf(state), decision,
        revision: decision === 'enable' ? (revision ?? approvedRevisionOf(assetId)) : null,
      }
      // The key is minted once per logical edit and reused by every retry of
      // the same save, so a repeated submit cannot double-apply (G03).
      const operationKey = state.draft[assetId]?.operationKey
        ?? `${key}:${assetId}:${decision}:${draft.revision ?? '-'}`
      patchLayer(key, { draft: { ...state.draft, [assetId]: { draft, operationKey } } })
      rebuild(key)
    },

    discard(key, assetId) {
      const state = layer(key)
      const draft = { ...state.draft }
      if (assetId === undefined) for (const id of Object.keys(draft)) delete draft[id]
      else delete draft[assetId]
      patchLayer(key, { draft, conflict: null })
      rebuild(key)
    },

    async save(key) {
      const state = layer(key)
      const entries = Object.values(state.draft)
      if (entries.length === 0) return
      if (!state.editable) {
        // The hard rule: while the project is missing/unauthorized nothing is
        // sent at all — and the draft is still there when it comes back.
        patchLayer(key, { conflict: { message: '本层当前不可编辑：修改保留在草稿中，未发送任何请求', serverRevision: state.assignmentRevision } })
        return
      }
      patchLayer(key, { saving: true, conflict: null, error: null })
      let expectedVersion = state.assignmentRevision
      try {
        for (const entry of entries) {
          const write: WriteResult = entry.draft.decision === 'inherit'
            ? await gateway.assignmentsRemove(entry.draft.assetId, layerOf(state), { expectedVersion, operationKey: entry.operationKey })
            : await gateway.assignmentsUpsert(entry.draft, { expectedVersion, operationKey: entry.operationKey })
          if (write.kind === 'conflict') {
            // Every draft cell stays; the server revision is surfaced and a
            // re-read is offered. Nothing here re-sends or overwrites.
            patchLayer(key, { saving: false, conflict: { message: write.message, serverRevision: write.serverRevision } })
            return
          }
          expectedVersion = write.assignmentRevision
        }
        patchLayer(key, { saving: false, draft: {}, conflict: null })
        await refreshLayer(key)
      } catch (failure) {
        // A transport failure is not a lost draft either.
        patchLayer(key, {
          saving: false, error: String(failure),
          conflict: { message: `保存失败：${String(failure)}（修改已保留）`, serverRevision: expectedVersion },
        })
      }
    },

    async reRead(key) {
      await refreshLayer(key)
      patchLayer(key, { conflict: null })
    },

    async previewDraft(key) {
      const state = layer(key)
      const drafts = Object.values(state.draft).map(entry => entry.draft)
      try {
        patchLayer(key, { preview: await gateway.previewEffective(targetOf(state), drafts), error: null })
      } catch (failure) {
        patchLayer(key, { error: String(failure) })
      }
    },

    async loadNative(harnessId, runtimeVersion, projectId) {
      patch({ native: { ...snapshot.native, state: 'loading', error: null } })
      try {
        patch({ native: { state: 'ready', error: null, items: await gateway.discoverNative({ harnessId, runtimeVersion, projectId }) } })
      } catch (failure) {
        patch({ native: { ...snapshot.native, state: 'error', error: String(failure) } })
      }
    },
  }

  return model
}
