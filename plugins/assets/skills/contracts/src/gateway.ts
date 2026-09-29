/**
 * The ONE typed gateway the Skills desktop consumes.
 *
 * Method names map 1:1 onto the published `skills.*` wire family of
 * docs/design/skills-v2/contracts.md §Skills service — catalogue/list/get/
 * revisions/preview/diff, import.*, sources/checkUpdate/approveRevision,
 * assignments.*, resolve/previewEffective, discoverNative, invokeDescriptor.
 * There is deliberately no other entry point: the legacy desktop gateway also
 * exposed `assets.profileFacets`, a wire method no backend ever published, and
 * its view rendered a whole binding surface from it. Anything outside this
 * family must be refused at this interface, so an unwired call cannot come
 * back as `undefined` and be mistaken for "no data".
 */
import type {
  AssignmentDraft, AssignmentList, ImportCommitResult, ImportFileDeclaration, ImportPreview, ImportSource,
  InvokeDescriptor, NativeDiscoveryItem, PreviewContent, ResolveTarget, RevisionDiff, SkillRecordView,
  SkillRevisionRow, SourceRow, EffectiveView, WriteResult, OriginScope,
} from './skills'

export interface AssignmentQuery {
  layer: AssignmentList['layer']
  /** Restrict to one project's rows; the layer already carries the scope id. */
  projectId?: string | null
}

export interface NativeTarget {
  harnessId: string
  runtimeVersion: string
  /** Authoritative Workspace project id; null asks the user-global roots. */
  projectId: string | null
}

export interface ImportCommitOptions {
  /** Existing asset to add a revision to; null installs a new one. */
  assetId: string | null
  originScope: OriginScope
  originOwner: string | null
  /** Idempotency key: a retry of the same commit must not publish twice (G03). */
  operationKey: string
  expectedVersion: number
}

export interface WriteOptions {
  /** CAS token from the last read; a stale write conflicts instead of overwriting. */
  expectedVersion: number
  operationKey: string
}

export interface SkillsGateway {
  // —— 内容库：内容与版本 (skills.catalogue/list/get/revisions/preview/diff) ——
  /** `skills.catalogue`: the whole content library, metadata without bodies. */
  catalogue(): Promise<SkillRecordView[]>
  /** `skills.list`: the records selectable by one target (ownership filter
   * server-side; a project-only asset never shows for another project). */
  list(target: ResolveTarget): Promise<SkillRecordView[]>
  /** `skills.get`: detail row for one asset. */
  get(assetId: string): Promise<SkillRecordView>
  revisions(assetId: string): Promise<SkillRevisionRow[]>
  preview(assetId: string, revision: number, path: string): Promise<PreviewContent>
  diff(assetId: string, fromRevision: number, toRevision: number): Promise<RevisionDiff>

  // —— 导入：先预览再发布 (skills.import.*) ——
  importBegin(files: readonly ImportFileDeclaration[], totalBytes: number): Promise<{ importId: string }>
  importChunk(importId: string, index: number, payload: Uint8Array, sha256: string): Promise<void>
  importPreview(importId: string, source: ImportSource): Promise<ImportPreview>
  importCommit(importId: string, options: ImportCommitOptions): Promise<ImportCommitResult>
  importCancel(importId: string): Promise<void>

  // —— 来源与版本审批 (skills.sources/checkUpdate/approveRevision) ——
  sources(): Promise<SourceRow[]>
  checkUpdate(assetId: string): Promise<SourceRow>
  approveRevision(assetId: string, revision: number, operationKey: string): Promise<WriteResult & { approvedRevision: number }>

  // —— 分配 (skills.assignments.*) ——
  assignmentsList(query: AssignmentQuery): Promise<AssignmentList>
  assignmentsUpsert(draft: AssignmentDraft, options: WriteOptions): Promise<WriteResult>
  assignmentsRemove(assetId: string, layer: AssignmentList['layer'], options: WriteOptions): Promise<WriteResult>

  // —— 有效集合 (skills.resolve/previewEffective) ——
  resolve(target: ResolveTarget): Promise<EffectiveView>
  /** Same read-only algorithm, applied to the unsaved draft; writes nothing. */
  previewEffective(target: ResolveTarget, draft: readonly AssignmentDraft[]): Promise<EffectiveView>

  // —— 原生发现与调用 (skills.discoverNative/invokeDescriptor) ——
  discoverNative(target: NativeTarget): Promise<NativeDiscoveryItem[]>
  invokeDescriptor(target: ResolveTarget, assetId: string): Promise<InvokeDescriptor | null>
}

/** One authorized project from the Workspace surface (contracts.md
 * §Profile / Workspace / Settings: Workspace only offers the authoritative
 * projectId and its state — never a Skills field, and never a root path the
 * UI could render). */
export interface ProjectEntry {
  projectId: string
  /** Display label supplied by the Workspace owner; may be a basename, never a
   * path the Skills UI is allowed to echo. */
  displayName: string
  state: 'available' | 'missing' | 'unauthorized'
}

/** The workspace list port the project picker is fed by. The integration wave
 * satisfies it from the Workspace service; this slice only ever sees ids and
 * states, so a project that is gone or unauthorized has to be *said*, not
 * guessed. */
export interface WorkspaceListPort {
  listProjects(): Promise<ProjectEntry[]>
}
