/**
 * Profile service operations (contracts.md §3, names camelCased).
 *
 * Interface-only: the wire transport is the host's business.  Error codes
 * mirror the stable Python codes (`ordessa_profile.errors`); absence of the
 * Profile backend surfaces as a rejected call, never as fake success.
 */
import type {
  Applicability,
  FacetCatalogEntry,
  ItemPatch,
  JournalEntryDto,
  MechanismPolicyDto,
  MechanismPolicyPatch,
  PolicyImpactPreview,
  ProfileCatalogGroup,
  ProfileSummary,
  ResolvedItem,
  SessionEvidence,
  SessionRef,
  SettingsPatch,
  Violation,
} from './contract'

/** Stable error codes of the Profile backend (ordessa_profile.errors). */
export type ProfileServiceErrorCode =
  | 'PROFILE_NOT_FOUND'
  | 'PROFILE_VERSION_CONFLICT'
  | 'PROFILE_ARCHIVED'
  | 'PROFILE_VALUE_INVALID'
  | 'HARNESS_UNKNOWN'
  | 'SESSION_NOT_FOUND'
  | 'SESSION_PROFILE_MISMATCH'
  | 'SESSION_NEEDS_RECOVERY'
  | 'NAME_CONFLICT'
  | 'FACET_UNKNOWN'
  | 'FACET_VALUE_INVALID'
  | 'FACET_NOT_APPLICABLE'
  | 'FACET_DISABLED'
  | 'FACET_ID_CONFLICT'
  | 'FACET_INVALID_PROVIDER'
  | 'FACET_GENERATION_STALE'
  | 'OVERRIDE_WRITES_FORBIDDEN'
  | 'APPLICATION_PORT_ABSENT'
  | 'APPLICATION_UNKNOWN'
  | 'OPERATION_KEY_REUSED'
  | 'NATIVE_KEY_CONFLICT'
  | 'POLICY_REVISION_CONFLICT'
  | 'LEGACY_RECEIPT_UNVERIFIED'
  | 'SECRET_FIELD_FORBIDDEN'
  | 'IDEMPOTENCY_KEY_REUSED'
  | 'REQUEST_TOO_LARGE'

export class ProfileServiceError extends Error {
  readonly code: ProfileServiceErrorCode
  readonly status: number
  /** Locate-able, non-secret evidence (blockers/conflicts/item). */
  readonly blockers?: readonly Violation[]
  readonly itemId?: string

  constructor(code: ProfileServiceErrorCode, message: string, status = 409,
              evidence?: { blockers?: readonly Violation[]; itemId?: string }) {
    super(`${code}: ${message}`)
    this.code = code
    this.status = status
    this.blockers = evidence?.blockers
    this.itemId = evidence?.itemId
  }
}

export interface ProfileIdentityDto {
  readonly profileId: string
  readonly version: number
  readonly displayName: string
  readonly harnessId: string
  readonly currentRevision: number
  readonly archivedAt: string | null
  readonly createdAt: string
  readonly updatedAt: string
  readonly realm: string
}

export interface SaveOutcomeDto {
  readonly profile: ProfileIdentityDto
}

export interface SelectionOutcomeDto {
  readonly sessionRef: SessionRef
  readonly pendingProfileId: string
  readonly pendingSeq: number
  /** Always 'pending' — selection is registration, never application. */
  readonly switchState: 'pending'
}

export interface SessionConfigDto {
  readonly sessionRef: SessionRef
  readonly switchState: string
  readonly current: { readonly profileId: string; readonly displayName: string; readonly revision: number }
  readonly pending: { readonly profileId: string; readonly revision: number; readonly seq: number } | null
  readonly items: readonly ResolvedItem[]
  readonly unavailable: readonly { readonly facetId: string; readonly itemId: string; readonly reason: string }[]
  readonly blockers: readonly { readonly reason: string }[] | null
  readonly evidence: SessionEvidence
}

export interface ResolvePreviewDto {
  readonly profileId: string
  readonly harnessId: string
  readonly revision: number
  readonly items: readonly ResolvedItem[]
  readonly unavailable: readonly { readonly facetId: string; readonly itemId: string; readonly reason: string }[]
  readonly conflicts: readonly Violation[]
  readonly digest: string
}

export interface UpdatePolicyOutcomeDto {
  readonly policy: MechanismPolicyDto
  readonly impact: PolicyImpactPreview
}

/**
 * Typed client for the Profile backend operations.  Implementations bind to
 * a real transport in the host; `DelegatingProfileServiceClient` below maps
 * the methods onto an injected transport function for that purpose.
 *
 * Guarantees the caller may rely on (and implementations must keep):
 * - `selectForSession` NEVER reports applied — it returns the pending
 *   registration (contracts.md §3).
 * - Mutations carry the caller's idempotency `operationKey`; reusing a key
 *   with a different payload is refused (`OPERATION_KEY_REUSED`).
 * - Every CAS mutation carries the expected revision/version.
 */
export interface ProfileServiceClient {
  listProfiles(realm: string | undefined, includeArchived: boolean): Promise<readonly ProfileIdentityDto[]>
  getProfile(profileId: string): Promise<ProfileIdentityDto>
  createProfile(operationKey: string, input: { realm: string; harnessId: string; displayName: string }): Promise<ProfileIdentityDto>
  cloneProfile(operationKey: string, input: { profileId: string; displayName: string }): Promise<ProfileIdentityDto>
  renameProfile(operationKey: string, input: { profileId: string; expectedVersion: number; displayName: string }): Promise<ProfileIdentityDto>
  saveProfile(operationKey: string, input: { profileId: string; expectedVersion: number; patches: readonly ItemPatch[] }): Promise<SaveOutcomeDto>
  archiveProfile(operationKey: string, input: { profileId: string; expectedVersion: number }): Promise<ProfileIdentityDto>
  restoreProfile(operationKey: string, input: { profileId: string; expectedVersion: number }): Promise<ProfileIdentityDto>

  describeFacets(harnessId: string | null): Promise<readonly FacetCatalogEntry[]>
  resolvePreview(profileId: string, sessionUid?: string): Promise<ResolvePreviewDto>

  getMechanismPolicy(realm: string): Promise<MechanismPolicyDto>
  updateMechanismPolicy(operationKey: string, input: {
    realm: string
    expectedRevision: number
    patch: MechanismPolicyPatch
    caller: string
  }): Promise<UpdatePolicyOutcomeDto>
  /** Dry run: same response shape (impact preview included), CAS-checked,
   * but nothing mutates and no idempotency key is consumed (PS05). */
  previewMechanismPolicy(operationKey: string, input: {
    realm: string
    expectedRevision: number
    patch: MechanismPolicyPatch
    caller: string
  }): Promise<UpdatePolicyOutcomeDto & { preview: boolean }>

  selectForSession(operationKey: string, input: {
    sessionRef: SessionRef
    profileId: string
  }): Promise<SelectionOutcomeDto>
  setSessionOverride(operationKey: string, input: {
    sessionRef: SessionRef
    facetId: string
    itemId: string
    value: unknown
  }): Promise<SessionConfigDto>
  clearSessionOverride(operationKey: string, input: {
    sessionRef: SessionRef
    facetId: string
    itemId: string
  }): Promise<SessionConfigDto>
  inspectSessionConfig(sessionRef: SessionRef): Promise<SessionConfigDto>
  beginTurnApplication(operationKey: string, sessionRef: SessionRef): Promise<{
    turnId: string
    appliedSwitch: boolean
    receipt?: SessionEvidence['receipt']
  }>
  reconcile(operationKey: string, sessionRef: SessionRef): Promise<{
    operationId: string
    state: 'confirmed-current' | 'rejected-unchanged' | 'unknown'
    receipt?: SessionEvidence['receipt']
    reason?: string
  }>

  profileCatalog(realm: string): Promise<readonly ProfileCatalogGroup[]>
  journalForSession(sessionRef: SessionRef): Promise<JournalEntryDto | null>
}

export type ProfileTransport = (operation: string, payload: unknown) => Promise<unknown>

/**
 * Maps the typed surface onto an injected transport.  The transport decides
 * auth, realm binding and wire format; this class adds none of those.
 */
export class DelegatingProfileServiceClient implements ProfileServiceClient {
  private readonly transport: ProfileTransport

  constructor(transport: ProfileTransport) {
    this.transport = transport
  }

  private call<T>(operation: string, payload: unknown): Promise<T> {
    return this.transport(operation, payload) as Promise<T>
  }

  listProfiles(realm: string | undefined, includeArchived: boolean) {
    return this.call<readonly ProfileIdentityDto[]>('listProfiles', { realm, includeArchived })
  }
  getProfile(profileId: string) {
    return this.call<ProfileIdentityDto>('getProfile', { profileId })
  }
  createProfile(operationKey: string, input: { realm: string; harnessId: string; displayName: string }) {
    return this.call<ProfileIdentityDto>('createProfile', { operationKey, ...input })
  }
  cloneProfile(operationKey: string, input: { profileId: string; displayName: string }) {
    return this.call<ProfileIdentityDto>('cloneProfile', { operationKey, ...input })
  }
  renameProfile(operationKey: string, input: { profileId: string; expectedVersion: number; displayName: string }) {
    return this.call<ProfileIdentityDto>('renameProfile', { operationKey, ...input })
  }
  saveProfile(operationKey: string, input: { profileId: string; expectedVersion: number; patches: readonly ItemPatch[] }) {
    return this.call<SaveOutcomeDto>('saveProfile', { operationKey, ...input })
  }
  archiveProfile(operationKey: string, input: { profileId: string; expectedVersion: number }) {
    return this.call<ProfileIdentityDto>('archiveProfile', { operationKey, ...input })
  }
  restoreProfile(operationKey: string, input: { profileId: string; expectedVersion: number }) {
    return this.call<ProfileIdentityDto>('restoreProfile', { operationKey, ...input })
  }
  describeFacets(harnessId: string | null) {
    return this.call<readonly (FacetCatalogEntry & { applicability: Applicability })[]>('describeFacets', { harnessId })
  }
  resolvePreview(profileId: string, sessionUid?: string) {
    return this.call<ResolvePreviewDto>('resolvePreview', { profileId, sessionUid })
  }
  getMechanismPolicy(realm: string) {
    return this.call<MechanismPolicyDto>('getMechanismPolicy', { realm })
  }
  updateMechanismPolicy(operationKey: string, input: {
    realm: string; expectedRevision: number; patch: MechanismPolicyPatch; caller: string
  }) {
    return this.call<UpdatePolicyOutcomeDto>('updateMechanismPolicy', { operationKey, ...input })
  }
  previewMechanismPolicy(operationKey: string, input: {
    realm: string; expectedRevision: number; patch: MechanismPolicyPatch; caller: string
  }) {
    return this.call<UpdatePolicyOutcomeDto & { preview: boolean }>('previewMechanismPolicy', { operationKey, ...input })
  }
  selectForSession(operationKey: string, input: { sessionRef: SessionRef; profileId: string }) {
    return this.call<SelectionOutcomeDto>('selectForSession', { operationKey, ...input })
  }
  setSessionOverride(operationKey: string, input: {
    sessionRef: SessionRef; facetId: string; itemId: string; value: unknown
  }) {
    return this.call<SessionConfigDto>('setSessionOverride', { operationKey, ...input })
  }
  clearSessionOverride(operationKey: string, input: {
    sessionRef: SessionRef; facetId: string; itemId: string
  }) {
    return this.call<SessionConfigDto>('clearSessionOverride', { operationKey, ...input })
  }
  inspectSessionConfig(sessionRef: SessionRef) {
    return this.call<SessionConfigDto>('inspectSessionConfig', { sessionRef })
  }
  beginTurnApplication(operationKey: string, sessionRef: SessionRef) {
    return this.call<{
      turnId: string; appliedSwitch: boolean
      receipt?: SessionEvidence['receipt']
      violations?: readonly Violation[]
    }>('beginTurnApplication', { operationKey, sessionRef })
  }
  reconcile(operationKey: string, sessionRef: SessionRef) {
    return this.call<{
      operationId: string
      state: 'confirmed-current' | 'rejected-unchanged' | 'unknown'
      receipt?: SessionEvidence['receipt']
      reason?: string
    }>('reconcile', { operationKey, sessionRef })
  }
  profileCatalog(realm: string) {
    return this.call<readonly ProfileCatalogGroup[]>('profileCatalog', { realm })
  }
  journalForSession(sessionRef: SessionRef) {
    return this.call<JournalEntryDto | null>('journalForSession', { sessionRef })
  }
}
