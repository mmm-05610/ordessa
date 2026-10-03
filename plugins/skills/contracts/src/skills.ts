/**
 * Skills wire view models (docs/design/skills-v2/data-model.md).
 *
 * These are the desktop-side mirrors of the `skills.*` service views. Field
 * names follow the backend's public JSON shape (`assetId`, `treeDigest`,
 * `selectedBy`, `excludedBy`, `originScope`, …) so the integration wave is a
 * transport wiring, not a rename exercise. Nothing here may carry a host
 * filesystem path, a secret, or script body text: the shapes have no such
 * field, which is what lets the views promise "never renders a native absolute
 * path" (ux.md §原生发现和错误) structurally rather than by scrubbing.
 */
import type { EvidenceLevel } from './evidence'

export type { EvidenceLevel }

/** Server-side domain the row belongs to; the principal is injected by auth,
 * never self-reported by the client (FR09). */
export type ServerScope = string

/** Content ownership, independent of assignment scope (FR03). */
export type OriginScope = 'public' | 'project' | 'profile'

/** Which layer of the resolution order decided something (data-model.md
 * §解析顺序): user-global any → user-global harness → project any → project
 * harness → profile → session override. `none` means no layer decided it, so
 * nothing is in the effective set — it is not a hidden "disabled by someone".
 * `mandatory` is the resolver's non-overridable policy layer
 * (`assignments/model.py` `LAYER_MANDATORY = "mandatory_policy"`); it names
 * itself in 最终结果 instead of masquerading as a user scope. */
export type LayerKind = 'none' | 'user-global' | 'project' | 'profile' | 'session' | 'mandatory'

/** One layer of an assignment scope: `harnessId: null` is the "所有 Harness"
 * layer, a brand id is the brand-specific layer above it. */
export interface ScopeRef {
  layer: LayerKind
  /** null for user-global; the authoritative Workspace projectId for project. */
  scopeId: string | null
  /** null means "所有 Harness". */
  harnessId: string | null
  /** The revision the layer pinned; null for `disable`/`inherit`. */
  revision: number | null
}

/** The editing layer the "本层设置" column reads. */
export interface AssignmentLayer {
  kind: Extract<LayerKind, 'user-global' | 'project'>
  scopeId: string | null
  harnessId: string | null
}

/** One published Skill in the content library (data-model.md `SkillRecord`). */
export interface SkillRecordView {
  serverScope: ServerScope
  assetId: string
  nativeName: string
  description: string | null
  originScope: OriginScope
  /** The owning project/profile id for a non-public record; null for public. */
  originOwner: string | null
  /** Source description as text ("git:<repo>@<commit>", "local:import");
   * never a local path. */
  source: string
  latestInstalledRevision: number
  /** Highest revision approved for use; assignments may only pin this or lower. */
  approvedRevision: number | null
  /** A newer installed revision awaiting explicit approval (FR07); null when
   * there is no update candidate. */
  updateCandidateRevision: number | null
  archived: boolean
  treeDigest: string
  /** Attachment/script manifest of the revision the record currently points at
   * (FR01); script entries carry path + bytes only, never content. */
  fileManifest: readonly SkillFileManifestEntry[]
  scripts: readonly string[]
}

/** One file of a revision package: path is package-relative. */
export interface SkillFileManifestEntry {
  path: string
  bytes: number
  script: boolean
  digest: string | null
}

/** `SkillRevision` as the desktop sees it. */
export interface SkillRevisionRow {
  assetId: string
  revision: number
  treeDigest: string
  /** An approval record is required before any scope may pin this revision. */
  approved: boolean
  approvalRecord: { approvedAt: string; approvedBy: string } | null
  sourceCommit: string | null
  fileManifest: readonly SkillFileManifestEntry[]
  scripts: readonly string[]
  declaredMetadata: Readonly<Record<string, string>>
}

/** A fixed remote source and its update state (contracts.md `sources`). */
export interface SourceRow {
  assetId: string
  kind: 'local' | 'git'
  /** Pinned reference: a commit, never a floating branch. */
  reference: string
  lastChecked: string | null
  candidateRevision: number | null
  archived: boolean
}

/** Bounded preview content. A script file has `text: null` by contract: the
 * service never ships script bodies to the desktop, so no view can render or
 * execute them (FR02, G02). */
export interface PreviewContent {
  path: string
  text: string | null
  script: boolean
  truncated: boolean
}

export interface RevisionDiff {
  assetId: string
  fromRevision: number
  toRevision: number
  added: readonly string[]
  removed: readonly string[]
  changed: readonly string[]
  /** Line-level diff of text files only; script files appear in `files` with
   * no hunks, so a diff view can show "脚本内容不展示". */
  hunks: readonly { path: string; lines: readonly { kind: 'add' | 'remove' | 'context'; text: string }[] }[]
}

/** The tri-state a user sets per Skill per layer (FR04/FR05). */
export type Decision = 'enable' | 'disable' | 'inherit'

/** A stored assignment row (`SkillAssignment`); absence of a row is `inherit`. */
export interface AssignmentRow {
  serverScope: ServerScope
  layer: AssignmentLayer
  assetId: string
  decision: Exclude<Decision, 'inherit'>
  /** Pinned, already-approved revision; required for `enable`. */
  revision: number | null
  rowVersion: number
}

/** The draft cell the UI edits before a save: a decision plus the revision it
 * would pin. `inherit` removes the row. */
export interface AssignmentDraft {
  assetId: string
  layer: AssignmentLayer
  decision: Decision
  revision: number | null
}

/** The list result for one layer, with the CAS token the next write must
 * carry. */
export interface AssignmentList {
  layer: AssignmentLayer
  rows: readonly AssignmentRow[]
  /** Monotonic per-scope revision; `expectedVersion` of the next write. */
  assignmentRevision: number
}

/** `ResolvedSkill` (data-model.md): the effective set plus who decided it.
 * `selectedBy`/`excludedBy` names are the backend's resolver field names; the
 * row's "最终结果" column renders only from here, never from a projection
 * field. */
export interface ResolvedSkill {
  assetId: string
  nativeName: string
  revision: number | null
  treeDigest: string | null
  originScope: OriginScope
  /** The layer that switched this Skill on. */
  selectedBy: ScopeRef
  /** The layer that switched it off again; null when nothing excluded it. */
  excludedBy: ScopeRef | null
  /** Highest level the backend can prove for this target, plus the proofs it
   * holds. Views grade these through `attest()` before wording them. */
  evidence: EvidenceLevel
  proofs: readonly string[]
  /** What the target harness can prove at all: absence of a capability is
   * `unknown`, never assumed (G10/G16). */
  capability: {
    loadEvidence: 'supported' | 'unsupported' | 'unknown'
    explicitInvocation: 'supported' | 'unsupported' | 'unknown'
    canMask: boolean | null
  }
  diagnostics: readonly ResolveDiagnostic[]
}

export interface ResolveDiagnostic {
  code: string
  message: string
  assetId: string | null
}

/** A typed refusal: unavailability is reported, never silently filtered
 * (contracts.md §Skills service). */
export interface ResolveRefusal {
  code: 'missing-asset' | 'name-conflict' | 'revision-not-approved' | 'unauthorized' | 'project-missing' | 'capability-unsupported'
  message: string
  assetId: string | null
  projectId: string | null
}

export interface ResolveTarget {
  /** null = the user-global default set, no project layer. The Server injects
   * the authenticated principal/server scope; the client never self-reports it
   * (FR09), which is why there is no such field here. */
  projectId: string | null
  /** null = "所有 Harness". */
  harnessId: string | null
  profileId?: string | null
}

/** `resolve`/`previewEffective` output: the effective view model both the
 * read-only preview and the draft preview render from. */
export interface EffectiveView {
  target: ResolveTarget
  assignmentRevision: number
  resolved: readonly ResolvedSkill[]
  refusals: readonly ResolveRefusal[]
}

/** One row of the assignment table: 本层设置 (the layer's own decision) and
 * 最终结果 (the resolver's decision + revision), side by side, so a single
 * master switch can never mislead (ux.md §Settings). */
export interface AssignmentViewRow {
  assetId: string
  nativeName: string
  originScope: OriginScope
  archived: boolean
  /** This layer's own stored row; null means "继承" at this layer. */
  layerRow: AssignmentRow | null
  /** This layer's unsaved edit, if any. */
  draft: AssignmentDraft | null
  effective: ResolvedSkill | null
  /** Highest revision the backend has approved for this content. */
  approvedRevision: number | null
}

/** `NativeDiscovery` (data-model.md): a read-only observation, not a
 * SkillRecord. There is deliberately no path field — only a location
 * category — so an absolute native path cannot reach the DOM. */
export interface NativeDiscoveryItem {
  harnessId: string
  runtimeVersion: string
  nativeName: string
  /** Bounded category, never the discovered root itself. */
  locationCategory: 'project' | 'user-global' | 'harness-builtin' | 'unknown'
  sourceEvidence: string
  /** null means the harness never told us, which is not "yes". */
  canBeMasked: boolean | null
  conflictsWith: string | null
}

export interface ImportFileDeclaration {
  path: string
  bytes: number
  sha256: string
}

export type ImportSource =
  | { type: 'local-transfer'; origin: string }
  | { type: 'git'; repository: string; commit: string; subpath?: string }

export interface ImportPreview {
  name: string
  description: string
  metadata: Readonly<Record<string, string>>
  files: readonly SkillFileManifestEntry[]
  scripts: readonly string[]
  treeDigest: string
  warnings: readonly string[]
}

/** The commit is the only publish point, and its effect is `stored` — never a
 * load claim (G03). */
export interface ImportCommitResult {
  effect: 'stored'
  assetId: string
  revision: number
  treeDigest: string
}

/** Files picked on the desktop; bytes travel, never a local path. */
export interface PickedFile { path: string; bytes: Uint8Array }

/** CAS-guarded write result. A conflict is a value, not an exception, so the
 * UI can keep the user's draft and offer a re-read (ux.md §Settings). */
export type WriteResult =
  | { kind: 'applied'; rows: readonly AssignmentRow[]; assignmentRevision: number }
  | { kind: 'conflict'; code: 'cas-conflict' | 'unauthorized' | 'project-missing'; message: string; serverRevision: number }

export interface ApproveRevisionResult {
  assetId: string
  revision: number
  approvedRevision: number
  /** Approval never moves an existing binding (FR07). */
  bindingsChanged: false
}

export interface InvokeDescriptor {
  assetId: string
  revision: number
  /** Only a verified explicit-invocation route is offered; otherwise the item
   * is browse-only (FR13/US6). */
  kind: 'invoke' | 'browse-only'
}
