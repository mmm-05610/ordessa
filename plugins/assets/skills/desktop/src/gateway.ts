/** Settings adapter for ordessa_skills/wire.py: flat params, bare DTOs.
 * Missing capabilities refuse instead of returning simulated success.
 */
import type { SkillsGateway } from '../../contracts/src/gateway'
import type { AssignmentLayer, AssignmentRow, EffectiveView, ImportPreview, ResolveTarget, ResolvedSkill, ScopeRef, SkillRecordView, SkillRevisionRow } from '../../contracts/src/skills'

export interface WireCaller { call(method: string, params: Record<string, unknown>): Promise<unknown> }
export const SKILLS_WIRE_METHODS = [
  'skills.list', 'skills.get', 'skills.revisions', 'skills.preview', 'skills.diff',
  'skills.importBegin', 'skills.importChunk', 'skills.importPreview', 'skills.importCommit', 'skills.importCancel',
  'skills.sourcesCheckUpdate', 'skills.approveRevision', 'skills.assignmentsList', 'skills.assignmentsUpsert',
  'skills.assignmentsRemove', 'skills.resolve', 'skills.previewEffective', 'skills.discoverNative', 'skills.invokeDescriptor',
] as const
export type SkillsWireMethod = typeof SKILLS_WIRE_METHODS[number]
const refuse = (code: string, message: string): never => { throw Error(`${code}: ${message}`) }
function items<T>(answer: { items: T[] }): T[] {
  if (!Array.isArray(answer.items)) return refuse('INVALID_WIRE_RESPONSE', 'expected items array')
  return answer.items
}

export function createSkillsGateway(wire: WireCaller): SkillsGateway {
  const send = async <T>(method: SkillsWireMethod, params: Record<string, unknown> = {}): Promise<T> => {
    const answer = await wire.call(method, { ...params, requestId: globalThis.crypto.randomUUID() })
    if (answer === null || answer === undefined) throw Error('empty wire response')
    return answer as T
  }
  const prepared = new Map<string, ImportPreview>()
  const revisions = async (assetId: string): Promise<SkillRevisionRow[]> => {
    const answer = await send<{ items: WireRevision[] }>('skills.revisions', { assetId })
    return items(answer).map(row => ({
      assetId, revision: row.revision, treeDigest: row.treeDigest,
      approved: row.approvalRecord != null, approvalRecord: row.approvalRecord ?? null,
      sourceCommit: null, fileManifest: [], scripts: [], declaredMetadata: {},
    }))
  }
  const record = async (row: WireAsset): Promise<SkillRecordView> => {
    const installed = await revisions(row.assetId)
    const approvedRevision = Math.max(0, ...installed.filter(item => item.approved).map(item => item.revision)) || null
    const [originScope, originOwner] = originOf(row.source)
    return {
      // list/get do not publish serverScope or a file manifest. Blank scope
      // denotes unproven identity and is never sent back to the server.
      serverScope: '', assetId: row.assetId, nativeName: row.name, description: row.description ?? null,
      originScope, originOwner, source: row.source ?? '', latestInstalledRevision: row.latestRevision,
      approvedRevision, updateCandidateRevision: approvedRevision !== null && row.latestRevision > approvedRevision ? row.latestRevision : null,
      archived: false, treeDigest: row.digest, fileManifest: [], scripts: row.latestRevisionDetail?.scripts ?? [],
    }
  }
  const catalogue = async () => {
    const answer = await send<{ items: WireAsset[] }>('skills.list')
    return Promise.all(items(answer).map(record))
  }
  const resolve = async (target: ResolveTarget, method: 'skills.resolve' | 'skills.previewEffective' = 'skills.resolve'): Promise<EffectiveView> => {
    const answer = await send<WireResolution>(method, targetParams(target))
    if (!Array.isArray(answer.resolvedSkills) || !Array.isArray(answer.excludedSkills)) {
      return refuse('INVALID_WIRE_RESPONSE', 'expected resolution sets')
    }
    const diagnostics = (answer.diagnostics ?? []).map(item => ({ code: item.kind, message: item.note ?? item.kind, assetId: item.assetId ?? null }))
    const common = (assetId: string) => ({
      capability: { loadEvidence: 'unknown' as const, explicitInvocation: 'unknown' as const, canMask: null },
      diagnostics: diagnostics.filter(item => item.assetId === null || item.assetId === assetId),
    })
    const resolved: ResolvedSkill[] = [
      ...answer.resolvedSkills.map(item => ({
        ...common(item.assetId), assetId: item.assetId, nativeName: item.nativeName,
        revision: item.revision, treeDigest: item.treeDigest, originScope: item.originScope,
        selectedBy: scopeRef(item.selectedBy, item.revision), excludedBy: null,
        evidence: item.capabilityEvidence?.effect === 'selected' ? 'selected' as const : 'unknown' as const,
        proofs: item.capabilityEvidence?.effect === 'selected' ? ['assignment_decision'] : [],
      })),
      ...answer.excludedSkills.map(item => ({
        ...common(item.assetId), assetId: item.assetId, nativeName: item.assetId,
        revision: null, treeDigest: null, originScope: 'public' as const,
        selectedBy: scopeRef({ layer: 'none' }, null), excludedBy: item.excludedBy === null ? null : scopeRef(item.excludedBy, null),
        evidence: 'unknown' as const, proofs: [],
      })),
    ]
    return { target: answer.target, assignmentRevision: Math.max(0, ...Object.values(answer.assignmentRevisions ?? {})), resolved, refusals: [] }
  }
  return {
    catalogue,
    async list(target) {
      // skills.list accepts no target. Mirror server source ownership for
      // selection; resolver and assignment writes remain authoritative.
      return (await catalogue()).filter(row => row.originScope === 'public'
        || row.originScope === 'project' && row.originOwner === target.projectId
        || row.originScope === 'profile' && row.originOwner === target.profileId)
    },
    async get(assetId) { return record(await send<WireAsset>('skills.get', { assetId })) },
    revisions,
    async preview(assetId, revision, path) {
      const answer = await send<{ path: string; text: string | null; script: boolean }>('skills.preview', { assetId, revision, path })
      // Backend currently returns script text: strip it before any UI sees it.
      return { path: answer.path, text: answer.script ? null : answer.text, script: answer.script, truncated: false }
    },
    async diff(assetId, fromRevision, toRevision) {
      const answer = await send<{ assetId: string; fromRevision: number; toRevision: number; added: string[]; removed: string[]; changed: string[] }>(
        'skills.diff', { assetId, fromRevision, toRevision })
      return { ...answer, hunks: [] }
    },
    async importBegin(files, totalBytes) { return send<{ importId: string }>('skills.importBegin', { files, totalBytes }) },
    async importChunk(importId, index, payload, sha256) {
      await send('skills.importChunk', { importId, chunkIndex: index, payloadBase64: bufferToBase64(payload), sha256 })
    },
    async importPreview(importId, source) {
      const wireSource = source.type === 'local-transfer' ? { kind: 'local' }
        : { kind: 'git', repository: source.repository, commit: source.commit, ...(source.subpath ? { subpath: source.subpath } : {}) }
      const answer = await send<ImportPreview>('skills.importPreview', { importId, source: wireSource })
      const preview: ImportPreview = {
        name: answer.name, description: answer.description, metadata: answer.metadata,
        files: answer.files.map(file => ({ path: file.path, bytes: file.bytes, script: file.script === true, digest: null })),
        scripts: answer.scripts, treeDigest: answer.treeDigest, warnings: answer.warnings ?? [],
      }
      prepared.set(importId, preview)
      return preview
    },
    async importCommit(importId, options) {
      if (options.originScope !== 'public' || options.originOwner !== null) {
        return refuse('IMPORT_OWNERSHIP_UNAVAILABLE', 'published commit cannot preserve project/profile ownership')
      }
      const assetId = options.assetId ?? prepared.get(importId)?.name
      if (!assetId || !/^[a-z0-9][a-z0-9._-]{0,63}$/.test(assetId)) return refuse('IMPORT_ID_REQUIRED', 'prepared name must be a valid asset slug')
      // Commit has revision but no CAS/operation-key params. Updating an
      // existing revision cannot fulfill this UI contract's guarded write.
      if (options.assetId !== null || options.expectedVersion !== 0) return refuse('IMPORT_CAS_UNAVAILABLE', 'existing updates need a published guarded commit')
      const answer = await send<{ asset: WireAsset; effect: 'stored' }>('skills.importCommit', { importId, assetId, revision: 1 })
      if (answer.effect !== 'stored') return refuse('INVALID_WIRE_RESPONSE', 'commit must attest stored')
      prepared.delete(importId)
      return { effect: answer.effect, assetId: answer.asset.assetId, revision: answer.asset.latestRevision, treeDigest: answer.asset.digest }
    },
    async importCancel(importId) { await send('skills.importCancel', { importId }); prepared.delete(importId) },
    async sources() { return refuse('SOURCES_UNAVAILABLE', 'backend publishes no source listing method') },
    async checkUpdate() { return refuse('SOURCE_ID_UNAVAILABLE', 'assetId is not a catalogue sourceId; no authoritative mapping is published') },
    async approveRevision(assetId, revision) {
      const answer = await send<{ approval: { revision: number }; effect: 'stored' }>('skills.approveRevision', { assetId, revision })
      if (answer.effect !== 'stored') return refuse('INVALID_WIRE_RESPONSE', 'approval must attest stored')
      return { kind: 'applied', approvedRevision: answer.approval.revision, rows: [], assignmentRevision: 0 }
    },
    async assignmentsList(query) {
      const answer = await send<{ items: WireAssignment[] }>('skills.assignmentsList', layerParams(query.layer))
      // Null harnessId means unfiltered in AssignmentStore.list.
      const rows = items(answer).map(assignment).filter(row => row.layer.harnessId === query.layer.harnessId)
      return { layer: query.layer, rows, assignmentRevision: Math.max(0, ...rows.map(row => row.rowVersion)) }
    },
    async assignmentsUpsert(draft, options) {
      if (draft.decision === 'inherit') return refuse('INVALID_REQUEST', 'inherit requires assignmentsRemove')
      const answer = await send<{ assignment: WireAssignment; effect: 'stored' }>('skills.assignmentsUpsert', {
        ...layerParams(draft.layer), assetId: draft.assetId, decision: draft.decision, revision: draft.revision, ...options,
      })
      if (answer.effect !== 'stored') return refuse('INVALID_WIRE_RESPONSE', 'assignment must attest stored')
      const row = assignment(answer.assignment)
      return { kind: 'applied', rows: [row], assignmentRevision: row.rowVersion }
    },
    async assignmentsRemove(assetId, layer, options) {
      const answer = await send<{ removed: { removed: boolean; previousRowVersion: number }; effect: 'stored' }>(
        'skills.assignmentsRemove', { assetId, ...layerParams(layer), ...options })
      if (!answer.removed.removed || answer.effect !== 'stored') return refuse('INVALID_WIRE_RESPONSE', 'removal was not stored')
      return { kind: 'applied', rows: [], assignmentRevision: answer.removed.previousRowVersion }
    },
    resolve,
    async previewEffective(target, draft) {
      if (draft.length) return refuse('DRAFT_PREVIEW_UNAVAILABLE', 'session overrides cannot simulate assignment-layer edits/removals')
      return resolve(target, 'skills.previewEffective')
    },
    async discoverNative(target) {
      await send('skills.discoverNative', { harnessId: target.harnessId })
      return refuse('INVALID_WIRE_RESPONSE', 'no native observation DTO is published')
    },
    async invokeDescriptor(target) {
      if (target.harnessId === null) return refuse('HARNESS_REQUIRED', 'invocation evidence requires a specific harness')
      const answer = await send<{ invocation: string; browseOnly: boolean }>('skills.invokeDescriptor', { harnessId: target.harnessId })
      if (answer.invocation === 'unknown' && answer.browseOnly === true) return null
      return refuse('INVOKE_DESCRIPTOR_UNKNOWN', 'no verified asset invocation route is published')
    },
  }
}
interface WireAsset { assetId: string; name: string; description: string | null; latestRevision: number; digest: string; source: string | null; latestRevisionDetail?: { scripts?: string[] } }
interface WireRevision { revision: number; treeDigest: string; approvalRecord: SkillRevisionRow['approvalRecord'] }
interface WireAssignment { serverScope: string; scopeKind: 'user_global' | 'project'; scopeId: string; harnessId: string | null; assetId: string; decision: 'enable' | 'disable'; revision: number | null; rowVersion: number }
interface WireScope { layer: string; scopeId?: string | null; harnessId?: string | null }
interface WireResolution {
  target: ResolveTarget
  resolvedSkills: { assetId: string; nativeName: string; revision: number; treeDigest: string; originScope: SkillRecordView['originScope']; selectedBy: WireScope; capabilityEvidence?: { effect: string } }[]
  excludedSkills: { assetId: string; excludedBy: WireScope | null }[]
  assignmentRevisions: Record<string, number>
  diagnostics?: { kind: string; assetId?: string; note?: string }[]
}
function layerParams(layer: AssignmentLayer): Record<string, unknown> {
  return { scopeKind: layer.kind === 'user-global' ? 'user_global' : 'project', scopeId: layer.scopeId, harnessId: layer.harnessId }
}
function targetParams(target: ResolveTarget): Record<string, unknown> {
  return { projectId: target.projectId, harnessId: target.harnessId, profileId: target.profileId ?? null }
}
function assignment(row: WireAssignment): AssignmentRow {
  return { serverScope: row.serverScope, assetId: row.assetId, decision: row.decision, revision: row.revision, rowVersion: row.rowVersion,
    layer: { kind: row.scopeKind === 'user_global' ? 'user-global' : 'project', scopeId: row.scopeKind === 'user_global' ? null : row.scopeId, harnessId: row.harnessId } }
}
function originOf(source: string | null): [SkillRecordView['originScope'], string | null] {
  for (const kind of ['project', 'profile'] as const) if (source?.startsWith(`${kind}:`)) return [kind, source.slice(kind.length + 1).split('|')[0] || null]
  return ['public', null]
}
function scopeRef(scope: WireScope, revision: number | null): ScopeRef {
  const layer = scope.layer.startsWith('user_global') ? 'user-global' : scope.layer.startsWith('project') ? 'project'
    : scope.layer === 'profile' ? 'profile' : scope.layer === 'session_override' ? 'session' : scope.layer === 'mandatory_policy' ? 'mandatory' : 'none'
  return { layer, scopeId: layer === 'user-global' ? null : scope.scopeId ?? null, harnessId: scope.harnessId ?? null, revision }
}
function bufferToBase64(payload: Uint8Array): string {
  let binary = ''
  for (let index = 0; index < payload.length; index++) binary += String.fromCharCode(payload[index])
  return btoa(binary)
}
