/** Shared fakes for the Profile-section tests (same discipline as fakes.ts:
 * the fake implements the WHOLE interface, so an unwired or renamed method is
 * a compile error, never an `undefined` a view mistakes for "no data"). */
import type {
  ProfileDraftState, ProfileDraftWriteResult, ProfileHost, ProfileImportPreview, ProfileLibraryRow,
  ProfileRevisionOption, ProfileSkillsGateway, ProfileSkillRelation,
} from '../../contracts/src/profile'
import type { EffectiveView, RevisionDiff } from '../../contracts/src/skills'
import { demoEffective, demoResolved } from './fakes'

export const PROFILE_DIGEST_A = 'sha256:' + 'a'.repeat(64)
export const PROFILE_DIGEST_B = 'sha256:' + 'b'.repeat(64)

export type ProfileCalls = { method: string; params: unknown[] }[]

export function profileLibraryRow(overrides: Partial<ProfileLibraryRow> = {}): ProfileLibraryRow {
  return {
    assetId: 'demo', nativeName: 'demo', description: 'A demo.', source: 'local:import',
    latestInstalledRevision: 2, treeDigest: PROFILE_DIGEST_A, ...overrides,
  }
}

export function profileRevisionOption(revision: number, approved = true): ProfileRevisionOption {
  return { revision, treeDigest: PROFILE_DIGEST_A, approved, approvedAt: approved ? '2026-09-01T00:00:00Z' : null }
}

export function profileRelation(assetId: string, overrides: Partial<ProfileSkillRelation> = {}): ProfileSkillRelation {
  return { assetId, decision: 'enable', revision: 1, importedForProfile: false, ...overrides }
}

export interface HostOptions {
  profileId?: string
  harnessId?: string
  archived?: boolean
  relations?: ProfileSkillRelation[]
  configRevision?: number
  /** The §G3 face: the host itself cannot read the profile layer. */
  unavailable?: boolean
  saveResult?: ProfileDraftWriteResult | ((relations: readonly ProfileSkillRelation[]) => ProfileDraftWriteResult)
}

export function fakeProfileHost(options: HostOptions = {}): { host: ProfileHost; calls: ProfileCalls; state: ProfileDraftState } {
  const calls: ProfileCalls = []
  const state: ProfileDraftState = {
    profileId: options.profileId ?? 'p1',
    harnessId: options.harnessId ?? 'pi',
    archived: options.archived ?? false,
    relations: [...(options.relations ?? [])],
    configRevision: options.configRevision ?? 5,
  }
  const host: ProfileHost = {
    async current() {
      calls.push({ method: 'current', params: [] })
      if (options.unavailable) {
        throw Object.assign(
          Error('NotConfiguredProfileLayerPort: PROFILE_LAYER_UNAVAILABLE for p1'),
          { code: 'PROFILE_LAYER_UNAVAILABLE' },
        )
      }
      return structuredClone(state)
    },
    async saveRelations(relations, opts) {
      calls.push({ method: 'saveRelations', params: [relations, opts] })
      const given = options.saveResult
      const result = typeof given === 'function' ? given(relations) : given
      if (result !== undefined && result.kind === 'conflict') return result
      state.relations = relations.map(row => ({ ...row }))
      state.configRevision = (result?.kind === 'applied' ? result.configRevision : state.configRevision + 1)
      return result ?? { kind: 'applied', configRevision: state.configRevision }
    },
    async cancelEditing() {
      calls.push({ method: 'cancelEditing', params: [] })
    },
  }
  return { host, calls, state }
}

export interface ProfileGatewayOptions {
  library?: ProfileLibraryRow[]
  revisions?: ProfileRevisionOption[]
  diff?: RevisionDiff
  effective?: EffectiveView
  /** Reject skills.resolve with the typed §G3 refusal. */
  resolveUnavailable?: boolean
  approveFails?: boolean
  importPreviewResult?: ProfileImportPreview
  fail?: Partial<Record<keyof ProfileSkillsGateway, string>>
}

export function fakeProfileSkillsGateway(options: ProfileGatewayOptions = {}): { gateway: ProfileSkillsGateway; calls: ProfileCalls } {
  const calls: ProfileCalls = []
  const record = <K extends keyof ProfileSkillsGateway>(method: K, params: unknown[]) => {
    calls.push({ method: String(method), params })
    if (options.fail && method in options.fail) throw Error(String(options.fail[method]))
  }
  let library = [...(options.library ?? [profileLibraryRow()])]
  const gateway: ProfileSkillsGateway = {
    async listSkills() { record('listSkills', []); return library.map(row => ({ ...row })) },
    async revisions(assetId) { record('revisions', [assetId]); return options.revisions ?? [profileRevisionOption(1), profileRevisionOption(2)] },
    async diff(request) {
      record('diff', [request])
      return options.diff ?? {
        assetId: request.assetId, fromRevision: request.fromRevision, toRevision: request.toRevision,
        added: ['notes.md'], removed: [], changed: ['SKILL.md'], hunks: [],
      }
    },
    async approveRevision(approval) {
      record('approveRevision', [approval])
      if (options.approveFails) throw Error('APPROVAL_REFUSED')
      return { approvedRevision: approval.revision, effect: 'stored' }
    },
    async resolveProfile(target) {
      record('resolveProfile', [target])
      if (options.resolveUnavailable) {
        throw Error('WireError UNAVAILABLE internalCode=PROFILE_LAYER_UNAVAILABLE')
      }
      return options.effective ?? demoEffective([demoResolved('demo', {
        revision: 1,
        selectedBy: { layer: 'profile', scopeId: 'p1', harnessId: 'pi', revision: 1 },
      })])
    },
    async importBegin(files, totalBytes) { record('importBegin', [files, totalBytes]); return { importId: 'import_1' } },
    async importChunk(importId, index, payload, sha256) { record('importChunk', [importId, index, payload.byteLength, sha256]) },
    async importPreview(importId) {
      record('importPreview', [importId])
      return options.importPreviewResult ?? {
        name: 'demo', description: 'A demo.',
        files: [{ path: 'SKILL.md', bytes: 40, script: false }, { path: 'scripts/run.sh', bytes: 20, script: true }],
        scripts: ['scripts/run.sh'], treeDigest: PROFILE_DIGEST_B,
      }
    },
    async importCommit(importId, assetId, revision) {
      record('importCommit', [importId, assetId, revision])
      library = [profileLibraryRow({ assetId, latestInstalledRevision: revision, treeDigest: PROFILE_DIGEST_B })]
      return { assetId, revision, effect: 'stored' }
    },
    async importCancel(importId) { record('importCancel', [importId]) },
  }
  return { gateway, calls }
}
