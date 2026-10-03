/** Shared fakes for the Skills desktop tests.
 *
 * `fakeSkillsGateway` implements the whole `SkillsGateway` interface, so an
 * unwired or renamed method is a compile error here rather than a `undefined`
 * that a view mistakes for "no data" — the legacy `assets.profileFacets`
 * defect. Every call is recorded with its params for the assertions.
 */
import type { ProjectEntry, SkillsGateway, WorkspaceListPort } from '../../contracts/src/gateway'
import type {
  AssignmentDraft, AssignmentList, AssignmentRow, EffectiveView, ImportPreview, NativeDiscoveryItem,
  ResolveRefusal, ResolvedSkill, RevisionDiff, SkillRecordView, SkillRevisionRow, SourceRow, WriteResult,
} from '../../contracts/src/skills'

export const DIGEST_A = 'sha256:' + 'a'.repeat(64)
export const DIGEST_B = 'sha256:' + 'b'.repeat(64)

export type Calls = { method: string; params: unknown[] }[]

export function demoRecord(overrides: Partial<SkillRecordView> = {}): SkillRecordView {
  return {
    serverScope: 'server:demo', assetId: 'demo', nativeName: 'demo', description: 'A demo.',
    originScope: 'public', originOwner: null, source: 'local:import',
    latestInstalledRevision: 2, approvedRevision: 1, updateCandidateRevision: 2, archived: false,
    treeDigest: DIGEST_A,
    fileManifest: [
      { path: 'SKILL.md', bytes: 40, script: false, digest: DIGEST_A },
      { path: 'scripts/run.sh', bytes: 20, script: true, digest: DIGEST_B },
    ],
    scripts: ['scripts/run.sh'],
    ...overrides,
  }
}

export function demoRevision(assetId = 'demo', revision = 1): SkillRevisionRow {
  return {
    assetId, revision, treeDigest: DIGEST_A, approved: true,
    approvalRecord: { approvedAt: '2026-09-01T00:00:00Z', approvedBy: 'user' },
    sourceCommit: null,
    fileManifest: [{ path: 'SKILL.md', bytes: 40, script: false, digest: DIGEST_A }],
    scripts: [], declaredMetadata: { name: 'demo', description: 'A demo.' },
  }
}

export function demoResolved(assetId: string, overrides: Partial<ResolvedSkill> = {}): ResolvedSkill {
  return {
    assetId, nativeName: assetId, revision: 1, treeDigest: DIGEST_A, originScope: 'public',
    selectedBy: { layer: 'user-global', scopeId: null, harnessId: null, revision: 1 },
    excludedBy: null, evidence: 'selected', proofs: ['assignment_decision'],
    capability: { loadEvidence: 'supported', explicitInvocation: 'unknown', canMask: true },
    diagnostics: [],
    ...overrides,
  }
}

export function demoRow(assetId: string, overrides: Partial<AssignmentRow> = {}): AssignmentRow {
  return {
    serverScope: 'server:demo', layer: { kind: 'user-global', scopeId: null, harnessId: null },
    assetId, decision: 'enable', revision: 1, rowVersion: 1, ...overrides,
  }
}

export function demoEffective(resolved: ResolvedSkill[], refusals: ResolveRefusal[] = []): EffectiveView {
  return { target: { projectId: null, harnessId: null, profileId: null }, assignmentRevision: 7, resolved, refusals }
}

export interface FakeOptions {
  catalogue?: SkillRecordView[]
  list?: SkillRecordView[]
  revisions?: SkillRevisionRow[]
  rows?: AssignmentRow[]
  assignmentRevision?: number
  effective?: EffectiveView
  draftEffective?: EffectiveView
  diff?: RevisionDiff | null
  preview?: { path: string; text: string | null; script: boolean; truncated: boolean }
  sources?: SourceRow[]
  native?: NativeDiscoveryItem[]
  projects?: ProjectEntry[]
  write?: WriteResult | ((draft: unknown) => WriteResult)
  importPreviewResult?: ImportPreview
  fail?: Partial<Record<keyof SkillsGateway, string>>
}

export function fakeSkillsGateway(options: FakeOptions = {}): { gateway: SkillsGateway; calls: Calls } {
  const calls: Calls = []
  const record = <K extends keyof SkillsGateway>(method: K, params: unknown[]) => {
    calls.push({ method: String(method), params })
    if (options.fail && method in options.fail) throw Error(String(options.fail[method]))
  }
  // Stored rows are stateful: an applied write changes what the next read
  // returns, so "saved" can be told apart from "the fake never moved".
  const rows: AssignmentRow[] = [...(options.rows ?? [])]
  const applyToRows = (draft: AssignmentDraft | null, assetId: string) => {
    const at = rows.findIndex(row => row.assetId === assetId)
    if (draft === null || draft.decision === 'inherit') { if (at >= 0) rows.splice(at, 1); return }
    const row: AssignmentRow = {
      serverScope: 'server:demo', layer: draft.layer, assetId, decision: draft.decision,
      revision: draft.revision, rowVersion: (at >= 0 ? rows[at].rowVersion : 0) + 1,
    }
    if (at >= 0) rows.splice(at, 1, row); else rows.push(row)
  }
  const gateway: SkillsGateway = {
    async catalogue() { record('catalogue', []); return options.catalogue ?? [demoRecord()] },
    async list(target) { record('list', [target]); return options.list ?? options.catalogue ?? [demoRecord()] },
    async get(assetId) { record('get', [assetId]); return demoRecord({ assetId }) },
    async revisions(assetId) { record('revisions', [assetId]); return options.revisions ?? [demoRevision(assetId)] },
    async preview(assetId, revision, path) {
      record('preview', [assetId, revision, path])
      return options.preview ?? { path, text: '---\nname: demo\n---\nbody', script: false, truncated: false }
    },
    async diff(assetId, from, to) {
      record('diff', [assetId, from, to])
      return options.diff ?? {
        assetId, fromRevision: from, toRevision: to, added: ['notes.md'], removed: [], changed: ['SKILL.md'],
        hunks: [{ path: 'SKILL.md', lines: [{ kind: 'remove', text: 'old' }, { kind: 'add', text: 'new' }] }],
      }
    },
    async importBegin(files, totalBytes) { record('importBegin', [files, totalBytes]); return { importId: 'import_1' } },
    async importChunk(importId, index, payload, sha256) { record('importChunk', [importId, index, payload.byteLength, sha256]) },
    async importPreview(importId, source) {
      record('importPreview', [importId, source])
      return options.importPreviewResult ?? {
        name: 'demo', description: 'A demo.', metadata: {}, treeDigest: DIGEST_B, scripts: ['scripts/run.sh'],
        warnings: [],
        files: [{ path: 'SKILL.md', bytes: 40, script: false, digest: null },
          { path: 'scripts/run.sh', bytes: 20, script: true, digest: null }],
      }
    },
    async importCommit(importId, opts) {
      record('importCommit', [importId, opts])
      return { effect: 'stored', assetId: opts.assetId ?? 'demo', revision: 2, treeDigest: DIGEST_B }
    },
    async importCancel(importId) { record('importCancel', [importId]) },
    async sources() {
      record('sources', [])
      return options.sources ?? [{ assetId: 'demo', kind: 'git', reference: 'deadbeef', lastChecked: null, candidateRevision: 2, archived: false }]
    },
    async checkUpdate(assetId) {
      record('checkUpdate', [assetId])
      return { assetId, kind: 'git', reference: 'deadbeef', lastChecked: '2026-09-02', candidateRevision: 2, archived: false }
    },
    async approveRevision(assetId, revision, operationKey) {
      record('approveRevision', [assetId, revision, operationKey])
      return { kind: 'applied', rows, assignmentRevision: 8, approvedRevision: revision }
    },
    async assignmentsList(query) {
      record('assignmentsList', [query])
      const list: AssignmentList = { layer: query.layer, rows, assignmentRevision: options.assignmentRevision ?? 7 }
      return list
    },
    async assignmentsUpsert(draft, opts) {
      record('assignmentsUpsert', [draft, opts])
      const given = options.write
      const result = typeof given === 'function' ? given(draft) : given
      if (result) return result
      applyToRows(draft, draft.assetId)
      return { kind: 'applied', rows, assignmentRevision: 8 }
    },
    async assignmentsRemove(assetId, layer, opts) {
      record('assignmentsRemove', [assetId, layer, opts])
      const given = options.write
      const result = typeof given === 'function' ? given({ assetId, layer }) : given
      if (result) return result
      applyToRows(null, assetId)
      return { kind: 'applied', rows: [], assignmentRevision: 8 }
    },
    async resolve(target) {
      record('resolve', [target])
      return options.effective ?? demoEffective((options.catalogue ?? [demoRecord()]).map(item => demoResolved(item.assetId)))
    },
    async previewEffective(target, draft) {
      record('previewEffective', [target, draft])
      return options.draftEffective ?? options.effective ?? demoEffective([])
    },
    async discoverNative(target) { record('discoverNative', [target]); return options.native ?? [] },
    async invokeDescriptor(target, assetId) { record('invokeDescriptor', [target, assetId]); return null },
  }
  return { gateway, calls }
}

export function fakeWorkspaces(items: ProjectEntry[] | Error | (() => Promise<ProjectEntry[]>)): { port: WorkspaceListPort; calls: number[] } {
  const calls: number[] = []
  return {
    calls,
    port: {
      async listProjects() {
        calls.push(calls.length)
        if (items instanceof Error) throw items
        if (typeof items === 'function') return items()
        return items
      },
    },
  }
}

export const AVAILABLE_PROJECT: ProjectEntry = { projectId: 'ordessa', displayName: 'ordessa', state: 'available' }
export const MISSING_PROJECT: ProjectEntry = { projectId: 'ordessa', displayName: 'ordessa', state: 'missing' }
