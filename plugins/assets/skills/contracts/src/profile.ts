/**
 * Profile-editor Skill section DTOs (T10 / G15, ux.md §Profile 编辑器).
 *
 * Two sources, kept apart by type (this is the whole point of the section's
 * wording):
 *
 * * the **Profile-layer choice** (本区选择/草稿) lives with the Profile host —
 *   contracts.md §Profile / Workspace / Settings: the facet `assets.skills`
 *   stores `inherit | enable(revision) | disable` per Skill and Profile-only
 *   content stores *references only*; the Skills wire family has no such
 *   method (`skills.assignmentsUpsert` scopeKind is user_global|project only,
 *   wire.py `_scope_kind`) — so it travels over the injected `ProfileHost`
 *   port below, never over `skills.*`;
 * * the **final result** (最终结果 + deciding scope + fixed revision) is the
 *   SAME `EffectiveView` the Settings page renders from
 *   `skills.resolve`/`skills.previewEffective` — no second model is forked.
 *
 * While §G3 (api-requests.md) is open the backend port is
 * `NotConfiguredProfileLayerPort`, which refuses with the typed code
 * `PROFILE_LAYER_UNAVAILABLE` instead of answering "empty = all disabled".
 * The desktop mirror of that fact is the `undetermined` choice below: the UI
 * may show 继承 as *not yet known*, never as a silent disable (G06/G09 edge).
 */
import type { Decision, EffectiveView, OriginScope, ResolvedSkill, RevisionDiff } from './skills'
// The shared model stays in `./skills`: this file only *adds* the profile-side
// rows and ports on top of it (no re-export, so `index.ts` never sees two
// sources for one name).

/** The typed refusal code of `profile_facet.py` (mirror of
 * `PROFILE_LAYER_UNAVAILABLE`). Keep in sync with
 * `src/ordessa_skills/profile_facet.py`. */
export const PROFILE_LAYER_UNAVAILABLE = 'PROFILE_LAYER_UNAVAILABLE'

/** True when `failure` is (or carries) the typed profile-layer refusal. The
 * host's real seam may reject with the code on the object or, before §G1
 * lands, only inside the re-raised `WireError` text (wire.py module
 * docstring), so both spellings are recognised and nothing else is. */
export function isProfileLayerUnavailable(failure: unknown): boolean {
  if (typeof failure === 'object' && failure !== null
    && (failure as { code?: unknown }).code === PROFILE_LAYER_UNAVAILABLE) return true
  return String(failure).includes(PROFILE_LAYER_UNAVAILABLE)
}

/** The choice as the section displays it. `undetermined` is strictly weaker
 * than `inherit`: the layer could not be read at all. */
export type ProfileLayerChoice = Decision | 'undetermined'

/** One stored/drafted row of the Profile facet `assets.skills`. */
export interface ProfileSkillRelation {
  assetId: string
  decision: Decision
  /** Required (and approved) when `decision === 'enable'`; null otherwise. */
  revision: number | null
  /** True when this Profile imported the content in place (G15 origin badge).
   * The badge survives a cancelled Profile: cancelling removes the
   * relationship, never the already-imported content
   * (G15 counter-example 「取消删除已导入资产」). */
  importedForProfile: boolean
}

/** What the injected profile host reports about the Profile being edited. */
export interface ProfileDraftState {
  profileId: string
  /** The Profile's fixed harness (Profile 的 harnessId 固定; a cross-harness
   * reference is a backend `PROFILE_HARNESS_MISMATCH` refusal). */
  harnessId: string
  /** An archived Profile is read-only here (US3: 归档不直接删除内容). */
  archived: boolean
  relations: readonly ProfileSkillRelation[]
  /** CAS token — the profile revision identity requested in §G3(c); a stale
   * save conflicts instead of overwriting, and the draft survives. */
  configRevision: number
}

export type ProfileDraftWriteResult =
  | { kind: 'applied'; configRevision: number }
  | { kind: 'conflict'; message: string; serverConfigRevision: number }

/** How the profile layer reads right now. `unavailable` is the §G3 state and
 * is said out loud, never filtered into an empty list. */
export type ProfileLayerStatus = 'loading' | 'ready' | 'unavailable' | 'error'

/**
 * The injected profile host (Z1 seam, api-requests.md §G3/§G6). The section
 * is self-contained against THIS port plus `ProfileSkillsGateway`: when the
 * real editor slot publishes its host, the product passes it in; until then
 * tests inject a fake. `cancelEditing` discards relationship state only —
 * no port method exists to delete content, by design.
 */
export interface ProfileHost {
  current(): Promise<ProfileDraftState>
  saveRelations(
    relations: readonly ProfileSkillRelation[],
    options: { expectedVersion: number; operationKey: string },
  ): Promise<ProfileDraftWriteResult>
  cancelEditing(): Promise<void>
}

/** One revision choice in the 启用时指定已批准版本 picker. `approved` comes
 * from `skills.revisions` (approvalRecord present), never from the client. */
export interface ProfileRevisionOption {
  revision: number
  treeDigest: string
  approved: boolean
  approvedAt: string | null
}

/** The 本层 row the section renders: both columns side by side, from their
 * own sources (same two-column discipline as the Settings page, ux.md
 * §Settings). */
export interface ProfileSkillRow {
  assetId: string
  nativeName: string
  /** Backend ownership read (`profile:<id>` source encoding), the resolver's
   * own origin field, or, for content this Profile imported in place, the
   * host-supplied badge. `null` = no source has proven ownership to this
   * surface yet — the row says 归属未证明 instead of guessing public. */
  originScope: OriginScope | null
  importedForProfile: boolean
  /** Profile-layer choice (stored relation, this section's unsaved draft, or
   * `undetermined` while the layer is unreadable). */
  profileChoice: ProfileLayerChoice
  /** The revision the Profile layer pins when enabled (draft first). */
  profileRevision: number | null
  /** This section's unsaved edit, if any. */
  draft: { decision: Decision; revision: number | null } | null
  /** 最终结果: the resolver's own row from the shared `EffectiveView`,
   * including deciding scope and fixed revision. */
  effective: ResolvedSkill | null
}

/** The flat param shape of `skills.diff` (wire.py row
 * `skills.diff` — `{assetId, fromRevision, toRevision, path?}`); named here
 * so the gateway signature says what the wire accepts. */
export interface ProfileVersionDiffRequest {
  assetId: string
  fromRevision: number
  toRevision: number
  path?: string | null
}

/** The flat param shape of `skills.approveRevision`. Approval publishes the
 * use-permission; it never moves a binding (FR07) — the repoint is the
 * explicit second act through `ProfileHost.saveRelations`. */
export interface ProfileRevisionApproval {
  assetId: string
  revision: number
  approvedBy?: string
  expectedDigest?: string | null
}

/** One library row the section lists (mirror of the backend `asset_view`:
 * assetId/name/description/latestRevision/digest/source; no host path, no
 * secret — records.py `asset_view` has none either). */
export interface ProfileLibraryRow {
  assetId: string
  nativeName: string
  description: string | null
  source: string
  latestInstalledRevision: number
  treeDigest: string
}

/** The preview of a staged transfer for the profile import (`skills.importPreview`
 * → ImportService.prepare). Files are package-relative rows; script rows carry
 * no text by construction. */
export interface ProfileImportPreview {
  name: string
  description: string
  files: readonly { path: string; bytes: number; script: boolean }[]
  scripts: readonly string[]
  treeDigest: string
}

/** The profile-side slice of the `skills.*` family this section may call —
 * exact method names as published in
 * `src/ordessa_skills/wire.py` `SKILLS_METHOD_IDS` (no `assets.*`, no
 * invented names; asserted per name in tests/profileGateway.test.ts). */
export interface ProfileSkillsGateway {
  /** `skills.list` — the content library rows the section offers for choice. */
  listSkills(): Promise<ProfileLibraryRow[]>
  /** `skills.revisions` — every installed revision with its approval fact. */
  revisions(assetId: string): Promise<ProfileRevisionOption[]>
  /** `skills.diff` — file/line diff between two revisions before a switch. */
  diff(request: ProfileVersionDiffRequest): Promise<RevisionDiff>
  /** `skills.approveRevision` — the approval act; moves no binding (FR07). */
  approveRevision(approval: ProfileRevisionApproval): Promise<{ approvedRevision: number; effect: 'stored' }>
  /** `skills.resolve` for this Profile's fixed harness; refuses with the
   * typed `PROFILE_LAYER_UNAVAILABLE` while §G3 is open. */
  resolveProfile(target: { profileId: string; harnessId: string; projectId?: string | null }): Promise<EffectiveView>
  /** `skills.importBegin` */
  importBegin(files: readonly { path: string; bytes: number; sha256: string }[], totalBytes: number): Promise<{ importId: string }>
  /** `skills.importChunk` (one declared file per bounded chunk; bytes travel,
   * never a path). */
  importChunk(importId: string, index: number, payload: Uint8Array, sha256: string): Promise<void>
  /** `skills.importPreview` — the bounded local transfer source. */
  importPreview(importId: string): Promise<ProfileImportPreview>
  /** `skills.importCommit` — the only publish point; effect is `stored`. */
  importCommit(importId: string, assetId: string, revision: number): Promise<{ assetId: string; revision: number; effect: 'stored' }>
  /** `skills.importCancel` — drops the staging area, never published content. */
  importCancel(importId: string): Promise<void>
}
