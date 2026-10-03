/**
 * The controlled wire adapter for the Profile-editor Skill section.
 *
 * Every method id below is copied VERBATIM from the published table in
 * `src/ordessa_skills/wire.py` (`SKILLS_METHOD_IDS`): `skills.list`,
 * `skills.revisions`, `skills.diff`, `skills.approveRevision`,
 * `skills.resolve`, the `skills.import*` family. The dotted spellings the
 * legacy page used (`skills.import.begin`, `skills.assignments.list`, …) do
 * not exist on that table and are not repeated here; `assets.*` and the
 * never-published `assets.profileFacets` are refused by construction because
 * no call site can name anything outside `PROFILE_WIRE_METHODS` (the local
 * type closes the string set — a typo is a compile error).
 *
 * Params are FLAT and value-shaped exactly as `wire.py` validates them
 * (`profileId`/`harnessId`/`fromRevision`/`chunkIndex`/`payloadBase64`, …);
 * responses are normalised from the backend's own view dicts
 * (`service.py`/`resolver.py`/`records.py`) onto the shared contract DTOs, so
 * the section renders the SAME `EffectiveView` the Settings page uses.
 * The Profile-layer relationship never goes through this file at all —
 * `skills.assignmentsUpsert` only serves `user_global|project` scopes
 * (wire.py `_scope_kind`), so profile choices travel on the injected
 * `ProfileHost` port (contracts/src/profile.ts).
 */
import type { EffectiveView, EvidenceLevel, ResolvedSkill, RevisionDiff, ScopeRef } from '../../contracts/src/skills'
import type { LayerKind } from '../../contracts/src/skills'
import type {
  ProfileImportPreview, ProfileLibraryRow, ProfileRevisionApproval, ProfileRevisionOption,
  ProfileSkillsGateway, ProfileVersionDiffRequest,
} from '../../contracts/src/profile'
import type { WireCaller } from './gateway'

/** The exact subset of `SKILLS_METHOD_IDS` this section may call. */
export const PROFILE_WIRE_METHODS = [
  'skills.list', 'skills.revisions', 'skills.diff', 'skills.approveRevision', 'skills.resolve',
  'skills.importBegin', 'skills.importChunk', 'skills.importPreview', 'skills.importCommit', 'skills.importCancel',
] as const
export type ProfileWireMethod = typeof PROFILE_WIRE_METHODS[number]

function result<T>(value: unknown): T {
  if (value === null || value === undefined) throw Error('empty wire response')
  return value as T
}

export function createProfileSkillsGateway(wire: WireCaller): ProfileSkillsGateway {
  // `send` refuses an empty answer ("the call said nothing" is not "there is
  // nothing"), and a rejection travels up untouched: the §G3 typed refusal
  // (`PROFILE_LAYER_UNAVAILABLE`, profile_facet.py) is classified by the
  // model via the shared `isProfileLayerUnavailable` predicate, never here.
  const send = async <T>(method: ProfileWireMethod, params: Record<string, unknown> = {}): Promise<T> =>
    result<T>(await wire.call(method, params))
  return {
    async listSkills() {
      // `skills.list` → `service.list_assets()`: {items: asset_view[], nextCursor}.
      const answer = await send<{ items: WireAssetView[] }>('skills.list', {})
      return answer.items.map(row => ({
        assetId: row.assetId,
        // records.py `asset_view` names the field `name`; the desktop model says
        // `nativeName`. This line is the rename — nowhere else.
        nativeName: row.name,
        description: row.description ?? null,
        source: row.source,
        latestInstalledRevision: row.latestRevision,
        treeDigest: row.digest,
      })) satisfies ProfileLibraryRow[]
    },
    async revisions(assetId) {
      // `skills.revisions` → {assetId, items:[{revision, treeDigest, approvalRecord}]}.
      const answer = await send<{ items: { revision: number; treeDigest: string; approvalRecord: { approvedAt: string } | null }[] }>(
        'skills.revisions', { assetId })
      return answer.items.map(row => ({
        revision: row.revision,
        treeDigest: row.treeDigest,
        // The approval fact is the backend's, not a client guess (G06: 启用未批
        // 版 is a typed refusal; the picker simply has no affordance for it).
        approved: row.approvalRecord !== null && row.approvalRecord !== undefined,
        approvedAt: row.approvalRecord?.approvedAt ?? null,
      })) satisfies ProfileRevisionOption[]
    },
    async diff(request: ProfileVersionDiffRequest) {
      const params: Record<string, unknown> = {
        assetId: request.assetId, fromRevision: request.fromRevision, toRevision: request.toRevision,
      }
      if (request.path != null) params.path = request.path
      // `skills.diff` → diff_revisions(): {assetId, fromRevision, toRevision,
      // changed[], added[], removed[]} (+ textDiff for one path when asked).
      const answer = await send<WireDiff>('skills.diff', params)
      const hunks = answer.textDiff === undefined ? [] : [{
        path: answer.textDiff.path,
        lines: answer.textDiff.unified
          .filter(line => !line.startsWith('---') && !line.startsWith('+++'))
          .map(line => ({
            kind: line.startsWith('+') ? 'add' as const : line.startsWith('-') ? 'remove' as const : 'context' as const,
            text: line,
          })),
      }]
      return {
        assetId: answer.assetId,
        fromRevision: answer.fromRevision,
        toRevision: answer.toRevision,
        added: answer.added,
        removed: answer.removed,
        changed: answer.changed,
        hunks,
      } satisfies RevisionDiff
    },
    async approveRevision(approval: ProfileRevisionApproval) {
      const params: Record<string, unknown> = { assetId: approval.assetId, revision: approval.revision }
      if (approval.approvedBy != null) params.approvedBy = approval.approvedBy
      if (approval.expectedDigest != null) params.expectedDigest = approval.expectedDigest
      // `skills.approveRevision` → {approval, effect: "stored"}; effect caps at
      // `stored` — an approval moves no binding and loads nothing (FR07).
      const answer = await send<{ approval: { revision: number }; effect: 'stored' }>('skills.approveRevision', params)
      return { approvedRevision: answer.approval.revision, effect: answer.effect }
    },
    async resolveProfile(target) {
      const params: Record<string, unknown> = { profileId: target.profileId, harnessId: target.harnessId }
      if (target.projectId != null) params.projectId = target.projectId
      // `skills.resolve` → Resolution.view(): {target, resolvedSkills[],
      // excludedSkills[], diagnostics[], assignmentRevisions{}, profileRevision}.
      // While §G3 is open this refuses with PROFILE_LAYER_UNAVAILABLE — typed,
      // never an empty list pretending "all disabled".
      const answer = await send<WireResolution>('skills.resolve', params)
      const resolved: ResolvedSkill[] = [
        ...answer.resolvedSkills.map((item): ResolvedSkill => ({
          assetId: item.assetId,
          nativeName: item.nativeName,
          revision: item.revision,
          treeDigest: item.treeDigest ?? null,
          originScope: item.originScope,
          selectedBy: scopeRefOf(item.selectedBy, item.revision),
          excludedBy: null,
          // The resolver attests `selected` only with its `assignment_decision`
          // proof (resolver.py `_capability_evidence`); the pair travels
          // together or not at all, so `attest()` downstream can re-grade it.
          // The wire field is the EvidenceLevel spelling by construction
          // (api/evidence.py); the cast is the TS mirror of that contract.
          evidence: (item.capabilityEvidence?.effect ?? 'unknown') as EvidenceLevel,
          proofs: item.capabilityEvidence?.effect === 'selected' ? ['assignment_decision'] : [],
          // The brand capability axes are not part of this answer; absence is
          // `unknown`, never an assumed ability (G10).
          capability: { loadEvidence: 'unknown', explicitInvocation: 'unknown', canMask: null },
          diagnostics: [],
        })),
        ...answer.excludedSkills.map((item): ResolvedSkill => ({
          assetId: item.assetId,
          // An excluded row carries id-level facts only on the wire; the model
          // fills the display name from the library, so this stays assetId.
          nativeName: item.assetId,
          revision: null,
          treeDigest: null,
          // The wire's excluded rows carry no origin fact; 'public' here only
          // satisfies the DTO shape — the profile model treats a non-selected
          // row's origin as unproven and badges it 归属未证明 regardless.
          originScope: 'public',
          // `excludedBy: null` + the not_enabled absence is exactly what the
          // DTO means by "无人决定" — disable and never-enabled stay distinct
          // (G06 inherit≠disable visibility).
          selectedBy: { layer: 'none', scopeId: null, harnessId: null, revision: null },
          excludedBy: item.excludedBy === null ? null : scopeRefOf(item.excludedBy, null),
          evidence: 'unknown',
          proofs: [],
          capability: { loadEvidence: 'unknown', explicitInvocation: 'unknown', canMask: null },
          diagnostics: [],
        })),
      ]
      return {
        target: {
          projectId: answer.target.projectId ?? null,
          harnessId: answer.target.harnessId ?? null,
          profileId: answer.target.profileId ?? null,
        },
        // The Profile surface's CAS token is the host's `configRevision`;
        // this view's number is the highest per-layer row version read.
        assignmentRevision: Math.max(0, ...Object.values(answer.assignmentRevisions ?? {})),
        resolved,
        // Diagnostics (`other_harness_scope`, `mandatory_policy_applied`) are
        // kinds outside the typed refusal union; they surface per row in the
        // model, never as fake refusals here.
        refusals: [],
      } satisfies EffectiveView
    },
    async importBegin(files, totalBytes) {
      return await send<{ importId: string }>('skills.importBegin', { files, totalBytes })
    },
    async importChunk(importId, index, payload, sha256) {
      // wire.py: {importId, chunkIndex, payloadBase64, sha256} — the dotted
      // legacy names (`index`/`payload`) are refused by the host shape wall.
      await send<{ importId: string }>('skills.importChunk', {
        importId, chunkIndex: index, payloadBase64: bufferToBase64(payload), sha256,
      })
    },
    async importPreview(importId) {
      // The bounded local-transfer source; `kind` is the wire.py
      // `_source_mapping` vocabulary (local|git|catalog), never the legacy
      // `type: 'local-transfer'`.
      const answer = await send<WireImportPreview>('skills.importPreview', { importId, source: { kind: 'local' } })
      return {
        name: answer.name,
        description: answer.description,
        files: (answer.files ?? []).map(file => ({
          path: file.path, bytes: file.bytes, script: file.script === true,
        })),
        scripts: answer.scripts ?? [],
        treeDigest: answer.treeDigest,
      } satisfies ProfileImportPreview
    },
    async importCommit(importId, assetId, revision) {
      // wire.py requires assetId + revision on commit (the caller's slug rule
      // is the backend's `ASSET_ID` wall; nothing invents an owner here —
      // ownership is the server-side `source` encoding, see records/authorization).
      const answer = await send<{ asset: WireAssetView; effect: 'stored' }>(
        'skills.importCommit', { importId, assetId, revision })
      return { assetId: answer.asset.assetId, revision: answer.asset.latestRevision, effect: answer.effect }
    },
    async importCancel(importId) {
      await send<{ cancelled: boolean }>('skills.importCancel', { importId })
    },
  }
}

// —————————————————————————— raw wire shapes (service.py outputs)

interface WireAssetView {
  assetId: string
  kind: string
  name: string
  description: string | null
  latestRevision: number
  digest: string
  source: string
}

interface WireScope {
  layer: string
  scopeKind?: string | null
  scopeId?: string | null
  harnessId?: string | null
  rowVersion?: number | null
}

interface WireDiff {
  assetId: string
  fromRevision: number
  toRevision: number
  added: string[]
  removed: string[]
  changed: string[]
  textDiff?: { path: string; unified: string[]; truncated: boolean }
}

interface WireImportPreview {
  name: string
  description: string
  files?: { path: string; bytes: number; script?: boolean }[]
  scripts?: string[]
  treeDigest: string
}

interface WireResolution {
  target: { projectId?: string | null; harnessId?: string | null; profileId?: string | null }
  resolvedSkills: {
    assetId: string
    nativeName: string
    revision: number
    treeDigest: string | null
    originScope: 'public' | 'project' | 'profile'
    selectedBy: WireScope
    capabilityEvidence?: { effect?: string }
  }[]
  excludedSkills: { assetId: string; excludedBy: WireScope | null }[]
  assignmentRevisions?: Record<string, number>
}

/** resolver.py `LAYER_*` → contracts `LayerKind`. */
function layerKindOf(raw: string): LayerKind {
  if (raw.startsWith('user_global')) return 'user-global'
  if (raw.startsWith('project')) return 'project'
  if (raw === 'profile') return 'profile'
  if (raw === 'session_override') return 'session'
  if (raw === 'mandatory_policy') return 'mandatory'
  return 'none'
}

function scopeRefOf(scope: WireScope, revision: number | null): ScopeRef {
  return {
    layer: layerKindOf(scope.layer),
    // user-global carries no scope id on the wire; anything else passes the
    // authoritative id through untouched.
    scopeId: scope.scopeId ?? null,
    harnessId: scope.harnessId ?? null,
    revision,
  }
}

function bufferToBase64(payload: Uint8Array): string {
  let binary = ''
  for (let index = 0; index < payload.length; index++) binary += String.fromCharCode(payload[index])
  return btoa(binary)
}
