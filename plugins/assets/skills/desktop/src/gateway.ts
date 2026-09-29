/**
 * The controlled wire adapter for the `skills.*` family.
 *
 * Every method name below maps to a published method of
 * docs/design/skills-v2/contracts.md §Skills service. The legacy desktop
 * adapter (`plugins/assets/desktop/src/wireGateway.ts` at 752f148b1b) called
 * `assets.profileFacets`, a method no backend ever published, and its view
 * rendered an entire binding surface from whatever came back — that is the
 * defect this file must not repeat, so the mapping table is asserted by name
 * in tests/gateway.test.ts and there is no generic escape hatch.
 *
 * Nothing here ever sends a desktop path: only bytes and digests cross the
 * wire, and the project identity is the authoritative Workspace id.
 */
import type { SkillsGateway } from '../../contracts/src/gateway'
import type {
  AssignmentDraft, AssignmentLayer, AssignmentList, EffectiveView, ImportCommitResult, ImportPreview,
  ImportSource, NativeDiscoveryItem, ResolveTarget, RevisionDiff, SkillRecordView, SkillRevisionRow,
  SourceRow, WriteResult,
} from '../../contracts/src/skills'

/** Satisfied by the Server connector in the integration wave. */
export interface WireCaller {
  call(method: string, params: Record<string, unknown>): Promise<unknown>
}

/** The complete, closed set of wire methods this extension may call. */
export const SKILLS_WIRE_METHODS = [
  'skills.catalogue', 'skills.list', 'skills.get', 'skills.revisions', 'skills.preview', 'skills.diff',
  'skills.import.begin', 'skills.import.chunk', 'skills.import.preview', 'skills.import.commit', 'skills.import.cancel',
  'skills.sources', 'skills.checkUpdate', 'skills.approveRevision',
  'skills.assignments.list', 'skills.assignments.upsert', 'skills.assignments.remove',
  'skills.resolve', 'skills.previewEffective', 'skills.discoverNative', 'skills.invokeDescriptor',
] as const
export type SkillsWireMethod = typeof SKILLS_WIRE_METHODS[number]

function result<T>(value: unknown): T {
  if (value === null || value === undefined) throw Error('empty wire response')
  return value as T
}

export function createSkillsGateway(wire: WireCaller): SkillsGateway {
  // A typo here is a compile error, which is the point of the local type.
  // `send` refuses an empty response instead of letting `.skills` read a null
  // apart: "the call answered nothing" is not "there is nothing".
  const send = async <T>(method: SkillsWireMethod, params: Record<string, unknown> = {}): Promise<T> =>
    result<T>(await wire.call(method, params))
  /** Calls whose answer carries no value: the wire's own settlement is enough. */
  const fire = (method: SkillsWireMethod, params: Record<string, unknown> = {}): Promise<void> =>
    wire.call(method, params).then(() => undefined)
  return {
    async catalogue() {
      return (await send<{ skills: SkillRecordView[] }>('skills.catalogue')).skills
    },
    async list(target: ResolveTarget) {
      return (await send<{ skills: SkillRecordView[] }>('skills.list', { target })).skills
    },
    async get(assetId) {
      return (await send<{ skill: SkillRecordView }>('skills.get', { assetId })).skill
    },
    async revisions(assetId) {
      return (await send<{ revisions: SkillRevisionRow[] }>('skills.revisions', { assetId })).revisions
    },
    /** The service only ever returns text for non-script files; `script: true`
     * rows come back with `text: null` and stay that way (G02). */
    async preview(assetId, revision, path) {
      return (await send<{ preview: { path: string; text: string | null; script: boolean; truncated: boolean } }>(
        'skills.preview', { assetId, revision, path })).preview
    },
    async diff(assetId, fromRevision, toRevision) {
      return (await send<{ diff: RevisionDiff }>('skills.diff', { assetId, fromRevision, toRevision })).diff
    },
    async importBegin(files, totalBytes) {
      return (await send<{ import: { importId: string } }>('skills.import.begin', { files, totalBytes })).import
    },
    async importChunk(importId, index, payload, sha256) {
      await fire('skills.import.chunk', { importId, index, payload: bufferToBase64(payload), sha256 })
    },
    async importPreview(importId, source: ImportSource) {
      return (await send<{ preview: ImportPreview }>('skills.import.preview', { importId, source })).preview
    },
    async importCommit(importId, options) {
      return (await send<{ commit: ImportCommitResult }>('skills.import.commit', { importId, ...options })).commit
    },
    async importCancel(importId) {
      await fire('skills.import.cancel', { importId })
    },
    async sources() {
      return (await send<{ sources: SourceRow[] }>('skills.sources')).sources
    },
    async checkUpdate(assetId) {
      return (await send<{ source: SourceRow }>('skills.checkUpdate', { assetId })).source
    },
    async approveRevision(assetId, revision, operationKey) {
      return await send<WriteResult & { approvedRevision: number }>('skills.approveRevision', { assetId, revision, operationKey })
    },
    async assignmentsList(query) {
      return (await send<{ assignments: AssignmentList }>('skills.assignments.list', { ...query })).assignments
    },
    async assignmentsUpsert(draft: AssignmentDraft, options) {
      return (await send<{ write: WriteResult }>('skills.assignments.upsert', { draft, ...options })).write
    },
    async assignmentsRemove(assetId: string, layer: AssignmentLayer, options) {
      return (await send<{ write: WriteResult }>('skills.assignments.remove', { assetId, layer, ...options })).write
    },
    async resolve(target: ResolveTarget) {
      return (await send<{ effective: EffectiveView }>('skills.resolve', { target })).effective
    },
    async previewEffective(target: ResolveTarget, draft: readonly AssignmentDraft[]) {
      return (await send<{ effective: EffectiveView }>('skills.previewEffective', { target, draft })).effective
    },
    async discoverNative(target) {
      return (await send<{ discovered: NativeDiscoveryItem[] }>('skills.discoverNative', { target })).discovered
    },
    async invokeDescriptor(target, assetId) {
      const view = await send<{ descriptor?: { kind: 'invoke' | 'browse-only'; revision: number } | null }>(
        'skills.invokeDescriptor', { target, assetId })
      // The route is answered per asset; the id is put back so a caller can
      // never attach a descriptor to the wrong Skill.
      return view.descriptor === undefined || view.descriptor === null
        ? null
        : { assetId, ...view.descriptor }
    },
  }
}

function bufferToBase64(payload: Uint8Array): string {
  let binary = ''
  for (let index = 0; index < payload.length; index++) binary += String.fromCharCode(payload[index])
  return btoa(binary)
}
