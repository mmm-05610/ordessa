/**
 * Public wire/DTO surface of the Q3 native-subagent definition library, as the
 * Settings UI consumes it.
 *
 * Field naming follows `specs/011-q3-subagents/tasks.md` ruling L2: the wire and
 * these public UI-facing DTOs are camelCase, the Python dataclasses are
 * snake_case, and exactly one decoder maps between them. Nothing here is
 * invented as a production transport — `docs/design/native-subagents/contracts.md`
 * §C1 is the frozen method list and the server-side wire belongs to C0's
 * `foundation` checkpoint (SR-7). This module declares the *port* the UI codes
 * against; the UI never talks to a socket, a file or a CLI.
 */
import { Token } from '@ordessa/extension-api'

// ---------------------------------------------------------------------------
// §C5 error codes — the full documented set, no local inventions
// ---------------------------------------------------------------------------

export const ERROR_CODES = [
  'DEFINITION_INVALID',
  'REVISION_STALE',
  'ASSIGNMENT_CONFLICT',
  'REFERENCE_UNRESOLVED',
  'PERMISSION_EXCEEDS_CEILING',
  'NATIVE_VERSION_UNKNOWN',
  'NATIVE_ENTRY_UNAVAILABLE',
  'NATIVE_NAME_CONFLICT',
  'NATIVE_DISCOVERY_UNCONTROLLED',
  'ADAPTER_MISSING',
  'TARGET_CONFLICT',
  'LOAD_UNVERIFIED',
  'OPERATION_UNKNOWN',
  'PROVIDER_BUSY',
] as const

export type ErrorCode = (typeof ERROR_CODES)[number]

export function isErrorCode(value: unknown): value is ErrorCode {
  return typeof value === 'string' && (ERROR_CODES as readonly string[]).includes(value)
}

// ---------------------------------------------------------------------------
// FR07 / data-model §状态和迁移 — facts that must never be conflated
// ---------------------------------------------------------------------------

/**
 * `stored` (saved) · `selected` (resolved effective) · `projected` (managed
 * native target generated) · `loaded` (target's native loader confirmed) ·
 * `invokable` (call entry confirmed) · `used` (independent call event).
 * These are six different facts; a file digest or a model narration upgrades
 * none of them, so `unknown` is a seventh, separate value per fact.
 */
export const CAPABILITY_FACTS = ['stored', 'selected', 'projected', 'loaded', 'invokable', 'used'] as const
export type CapabilityFact = (typeof CAPABILITY_FACTS)[number]

/** `true` observed, `false` observed-absent, `'unknown'` = no observation mechanism. */
export type FactValue = true | false | 'unknown'

export type CapabilityFactMap = Readonly<Partial<Record<CapabilityFact, FactValue>>>

/** FR07: native · extension-backed · unsupported · unknown, kept apart. */
export const BRAND_SUPPORTS = ['native', 'extension-backed', 'unsupported', 'unknown'] as const
export type BrandSupport = (typeof BRAND_SUPPORTS)[number]

/** One brand/version cell of the capability matrix for a definition. */
export interface BrandCapability {
  readonly harnessId: string
  readonly targetVersion?: string | undefined
  readonly support: BrandSupport
  readonly facts: CapabilityFactMap
  /** Raw evidence reference (a document path or probe id), never a claim. */
  readonly evidence?: readonly string[] | undefined
}

// ---------------------------------------------------------------------------
// §C2 target stamping — a late response must never land on another target
// ---------------------------------------------------------------------------

/**
 * The identity of "the thing an async result is about". Every request carries
 * it and every response must echo it; the reducer drops a result whose stamp is
 * not the current target (`verification.md` G15 negative column).
 */
export interface TargetStamp {
  readonly serverId: string
  readonly projectId: string | null
  readonly profileId: string | null
  readonly sessionId: string | null
  /** Target-side revision counter: bumped by any target switch or pin change. */
  readonly revision: number
  /** Provider (adapter) generation; a stale generation must not be applied. */
  readonly providerGeneration: string
}

export function sameStamp(a: TargetStamp, b: TargetStamp): boolean {
  return a.serverId === b.serverId
    && a.projectId === b.projectId
    && a.profileId === b.profileId
    && a.sessionId === b.sessionId
    && a.revision === b.revision
    && a.providerGeneration === b.providerGeneration
}

// ---------------------------------------------------------------------------
// Service result shapes
// ---------------------------------------------------------------------------

/** Item-level refusal: reported, never thrown away (§C5 "item-level 原因"). */
export interface Refusal {
  readonly code: ErrorCode
  readonly itemId: string
  readonly detail: string
}

export interface ServiceFailure {
  readonly code: ErrorCode
  readonly detail: string
  /** Item-level refusals backing the aggregate failure, when there are any. */
  readonly refusals?: readonly Refusal[] | undefined
}

export type ServiceResult<T> =
  | { readonly ok: true; readonly stamp: TargetStamp; readonly data: T }
  | { readonly ok: false; readonly stamp: TargetStamp; readonly error: ServiceFailure }

export function ok<T>(stamp: TargetStamp, data: T): ServiceResult<T> {
  return { ok: true, stamp, data }
}

export function fail(stamp: TargetStamp, error: ServiceFailure): ServiceResult<never> {
  return { ok: false, stamp, error }
}

/**
 * The *input* for a new revision. Deliberately carries no digest and no
 * revision number: those are service-owned facts (FR01 — immutable revision +
 * content digest), and a UI-computed digest would be a fake claim.
 */
export interface RevisionInput {
  readonly definitionId: string | null
  readonly displayName: string
  readonly slug: string
  readonly description: string
  readonly roleBody: string
  readonly declaredModelRef?: ResourceRef | null
  readonly toolRefs?: readonly ResourceRef[]
  readonly mcpRefs?: readonly ResourceRef[]
  readonly skillRefs?: readonly ResourceRef[]
  readonly requestedPermission?: string | null
  readonly isolation?: Readonly<Record<string, unknown>>
  readonly limits?: Readonly<Record<string, unknown>>
  readonly expectedRowVersion: number
}

// ---------------------------------------------------------------------------
// §C1 method list (camelCase mirror of docs/design/native-subagents/data-model.md)
// ---------------------------------------------------------------------------

export type OriginScope = 'public' | 'project' | 'profile'

export interface ResourceRef {
  readonly ownerId: string
  readonly revision?: string | null
}

export interface SourceApproval {
  readonly origin: string
  readonly originRef: string
  readonly contentDigest: string
  readonly approvedByPrincipal: string
  readonly approvedAt: string
}

/**
 * One requested capability and what the ceiling actually admits.
 * FR06/US3: the definition declares; the owner authorises. `granted` is never
 * inferred from `requested`, and an over-ceiling item carries its refusal.
 */
export interface CapabilityDeclaration {
  readonly kind: 'tool' | 'model' | 'mcp' | 'skill' | 'permission-mode' | 'isolation' | 'limit'
  readonly name: string
  readonly granted: FactValue
  /** Why this cannot be applied; required for the refusal rendering. */
  readonly refusal?: { readonly code: ErrorCode; readonly detail: string; readonly source: string } | undefined
}

export interface DefinitionRevisionContent {
  readonly definitionId: string
  readonly revision: number
  readonly contentDigest: string
  readonly roleBody: string
  readonly declaredModelRef?: ResourceRef | null
  readonly toolRefs?: readonly ResourceRef[]
  readonly mcpRefs?: readonly ResourceRef[]
  readonly skillRefs?: readonly ResourceRef[]
  readonly requestedPermission?: string | null
  readonly isolation?: Readonly<Record<string, unknown>>
  readonly limits?: Readonly<Record<string, unknown>>
  readonly source?: SourceApproval | null
  readonly retainedNativeFields?: Readonly<Record<string, unknown>>
  readonly capabilityDeclarations?: readonly CapabilityDeclaration[]
}

export interface DefinitionSummary {
  readonly serverScope: string
  readonly definitionId: string
  readonly slug: string
  readonly displayName: string
  readonly description: string
  readonly originScope: OriginScope
  readonly originOwner: string
  readonly latestRevision: number
  readonly archived: boolean
  readonly rowVersion: number
  /** Where the last approved content came from, or null when never approved. */
  readonly lastApprovedSource?: SourceApproval | null
  readonly capabilities?: readonly BrandCapability[]
}

export interface DefinitionDetail extends DefinitionSummary {
  readonly revisions: readonly DefinitionRevisionContent[]
  readonly latestContent: DefinitionRevisionContent | null
  /** Assignments that pin a revision of this definition (FR02 non-movement). */
  readonly pinnedAssignments?: readonly AssignmentView[]
}

export type AssignmentDecision = 'inherit' | 'enable' | 'disable'
export type AssignmentScopeKind =
  | 'user-global-generic' | 'user-global-harness'
  | 'project-generic' | 'project-harness'
  | 'profile' | 'session'

/** The 6 layers frozen by ruling C1 (data-model §范围解释), low to high. */
export const ASSIGNMENT_LAYERS: readonly AssignmentScopeKind[] = [
  'user-global-generic', 'user-global-harness',
  'project-generic', 'project-harness',
  'profile', 'session',
]

export interface AssignmentView {
  readonly serverScope: string
  readonly principal: string
  readonly scopeKind: AssignmentScopeKind
  readonly scopeId: string | null
  readonly harnessId: string
  readonly definitionId: string
  readonly decision: AssignmentDecision
  /** Pinned revision; present exactly when decision === 'enable'. */
  readonly revision?: number | null
  readonly rowVersion: number
}

export interface EffectiveDefinition {
  readonly definitionId: string
  readonly revision: number
  readonly nativeName: string
  readonly selectedBy: AssignmentScopeKind
  readonly diagnostics?: readonly string[]
}

export interface ExcludedDefinition {
  readonly definitionId: string
  readonly reasonCode: ErrorCode
  readonly detail: string
}

export interface EffectiveSet {
  readonly resolved: readonly EffectiveDefinition[]
  readonly excluded: readonly ExcludedDefinition[]
}

export interface NativeObservation {
  readonly nativeName: string
  readonly scope: string
  readonly sourceCategory: string
  readonly targetGeneration?: string | null
  readonly evidence?: string | null
  /**
   * Whether the native mechanism can actually mask this item.
   * `undefined` means "not established" — US5 forbids rendering "已禁用" then.
   */
  readonly suppressible?: boolean | undefined
}

/** FR07: an absent observation mechanism is `unknown`, never an empty list. */
export type NativeInspection =
  | { readonly state: 'observed'; readonly observations: readonly NativeObservation[] }
  | { readonly state: 'unknown'; readonly reason: string }

export interface ImportFilePreview {
  readonly relativePath: string
  readonly sizeBytes: number
  readonly contentDigest: string
  readonly diagnostics: readonly string[]
  readonly selectable: boolean
  readonly declaredSlug?: string | null
  readonly declaredDescription?: string | null
}

export interface ImportPreview {
  readonly previewId: string
  readonly sourceName: string
  /** Fixed source identity: a file digest or a pinned Git revision. */
  readonly sourceRef: string
  readonly sourceDigest: string
  readonly files: readonly ImportFilePreview[]
  readonly diagnostics: readonly string[]
  /** Capabilities the imported content would ask for *in the future*. */
  readonly futurePermissions: readonly CapabilityDeclaration[]
}

export interface ImportPlanResult {
  readonly previewId: string
  readonly definitions: readonly DefinitionSummary[]
}

// ---------------------------------------------------------------------------
// The port the Settings UI is coded against
// ---------------------------------------------------------------------------

export interface ListQuery {
  readonly includeArchived: boolean
  readonly originFilter: OriginFilter
}

export type OriginFilter = 'all' | 'mine' | 'project' | 'profile-only' | 'native-discovered'

/**
 * §C1 method list, exactly. Mutation calls carry `principal`, `serverScope`,
 * `expectedRowVersion` and `operationKey`; the principal comes from the service
 * context (a client may not self-report it), so the port hands the service an
 * opaque `operationKey` + CAS version only.
 */
export interface SubagentDefinitionServicePort {
  listDefinitions(stamp: TargetStamp, query: ListQuery): Promise<ServiceResult<readonly DefinitionSummary[]>>
  getDefinition(stamp: TargetStamp, definitionId: string): Promise<ServiceResult<DefinitionDetail>>
  inspectNative(stamp: TargetStamp): Promise<ServiceResult<NativeInspection>>
  resolvePreview(stamp: TargetStamp, expectedRevisions: readonly (readonly [string, number])[]): Promise<ServiceResult<EffectiveSet>>
  listAssignments(stamp: TargetStamp, scope: { readonly projectId?: string | null }): Promise<ServiceResult<readonly AssignmentView[]>>
  createDefinition(input: { readonly stamp: TargetStamp; readonly seed: RevisionInput; readonly operationKey: string }): Promise<ServiceResult<DefinitionSummary>>
  saveRevision(input: { readonly stamp: TargetStamp; readonly revision: RevisionInput; readonly operationKey: string }): Promise<ServiceResult<DefinitionSummary>>
  archive(input: {
    readonly stamp: TargetStamp; readonly definitionId: string; readonly expectedRowVersion: number; readonly operationKey: string
  }): Promise<ServiceResult<DefinitionSummary>>
  restore(input: {
    readonly stamp: TargetStamp; readonly definitionId: string; readonly expectedRowVersion: number; readonly operationKey: string
  }): Promise<ServiceResult<DefinitionSummary>>
  clone(input: {
    readonly stamp: TargetStamp; readonly definitionId: string; readonly revision: number; readonly expectedRowVersion: number; readonly operationKey: string
  }): Promise<ServiceResult<DefinitionSummary>>
  importPreview(input: { readonly stamp: TargetStamp; readonly sourceRef: string }): Promise<ServiceResult<ImportPreview>>
  approveImport(input: {
    readonly stamp: TargetStamp; readonly previewId: string; readonly selectPaths: readonly string[]; readonly operationKey: string
  }): Promise<ServiceResult<ImportPlanResult>>
  approveAssignmentUpdate(input: {
    readonly stamp: TargetStamp; readonly assignment: AssignmentView; readonly expectedRowVersion: number; readonly operationKey: string
  }): Promise<ServiceResult<AssignmentView>>
}

/**
 * Registration token a future provider may serve the port under. Declared here
 * (consumer side) so the provider can register against a stable name; today no
 * provider exists — see the report's integration items (SR-7).
 */
export const SubagentDefinitionServiceToken = new Token<SubagentDefinitionServicePort>('ordessa.assets.native-subagents.service.v1')

/** The facet id frozen by ruling L1; never rename it. */
export const FACET_ID = 'assets.native-subagents'
