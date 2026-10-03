/**
 * Frozen open-environment contract types — TypeScript mirror of
 * `ordessa_environment_api` (spec 026 order 002).
 *
 * Interfaces carry the same field names as the Python dataclasses so the
 * canonical wire form is field-identical; validators enforce the same
 * identity rules (realm/namespace/entity patterns, frozen enums, full
 * owner+generation object identity).
 */

export const PATTERNS = {
  realm: /^[a-z][a-z0-9-]{0,31}$/,
  namespace: /^[a-z][a-z0-9._-]{0,95}$/,
  entity: /^[A-Za-z0-9][A-Za-z0-9._:-]{0,191}$/,
  authorityKind: /^[a-z][a-z0-9.-]{0,63}$/,
  localId: /^[a-z][a-z0-9._-]{0,63}$/,
  principalScope: /^[a-z][a-z0-9._:-]{0,127}$/,
  digest64: /^[0-9a-f]{64}$/,
  operation: /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/,
  revision: /^[A-Za-z0-9][A-Za-z0-9._:+-]{0,127}$/,
} as const

export class ContractValidationError extends Error {
  readonly code = 'CONTRACT_VALIDATION'
}

function check(pattern: RegExp, value: string, what: string): string {
  if (typeof value !== 'string' || !pattern.test(value)) {
    throw new ContractValidationError(`${what} is malformed: ${String(value)}`)
  }
  return value
}

// ---------------------------------------------------------------------------
// identity (E1 / C2)
// ---------------------------------------------------------------------------

export interface RequestKey {
  environment_namespace: string
  principal_scope: string
  request_id: string
  comparison?: Record<string, string>
}

export function validateRequestKey(key: RequestKey): RequestKey {
  check(PATTERNS.localId, key.environment_namespace, 'RequestKey.environment_namespace')
  check(PATTERNS.principalScope, key.principal_scope, 'RequestKey.principal_scope')
  check(PATTERNS.localId, key.request_id, 'RequestKey.request_id')
  return key
}

export interface ObjectRef {
  environment: string
  owner_instance_id: string
  owner_generation: number
  object_id: string
}

/** A-01: full owner identity — never a bare object id. */
export function validateObjectRef(ref: ObjectRef): ObjectRef {
  check(PATTERNS.localId, ref.environment, 'ObjectRef.environment')
  check(PATTERNS.localId, ref.owner_instance_id, 'ObjectRef.owner_instance_id')
  check(PATTERNS.localId, ref.object_id, 'ObjectRef.object_id')
  if (!Number.isInteger(ref.owner_generation) || ref.owner_generation < 0) {
    throw new ContractValidationError('ObjectRef.owner_generation must be a non-negative int')
  }
  return ref
}

// ---------------------------------------------------------------------------
// targets / authority (025 §14.1, E3 §3)
// ---------------------------------------------------------------------------

export interface CanonicalFactTarget {
  realm: string
  identity_namespace: string
  stable_entity_id: string
}

export function validateCanonicalFactTarget(target: CanonicalFactTarget): CanonicalFactTarget {
  check(PATTERNS.realm, target.realm, 'CanonicalFactTarget.realm')
  check(PATTERNS.namespace, target.identity_namespace, 'CanonicalFactTarget.identity_namespace')
  check(PATTERNS.entity, target.stable_entity_id, 'CanonicalFactTarget.stable_entity_id')
  return target
}

export interface AuthorityKey {
  authority_kind: string
  target: CanonicalFactTarget
}

export function validateAuthorityKey(key: AuthorityKey): AuthorityKey {
  check(PATTERNS.authorityKind, key.authority_kind, 'AuthorityKey.authority_kind')
  validateCanonicalFactTarget(key.target)
  return key
}

// ---------------------------------------------------------------------------
// guarantee (C1 / C2 / M06)
// ---------------------------------------------------------------------------

export type GuaranteeLevel = 'raw' | 'reliable'

export const GUARANTEE_LEVELS: readonly GuaranteeLevel[] = ['raw', 'reliable']

export interface FingerprintDescriptor {
  algorithm: string
  key_id: string
  comparison_scope: string
}

export interface InputCapture {
  content_digest: string
  attachment_digests?: string[]
  config_operation_ids?: string[]
  base_revision?: string | null
  handles?: Record<string, string>
}

export function validateInputCapture(capture: InputCapture): InputCapture {
  if (!PATTERNS.digest64.test(capture.content_digest)) {
    throw new ContractValidationError('InputCapture.content_digest must be a lowercase sha256 hex')
  }
  for (const digest of capture.attachment_digests ?? []) {
    if (!PATTERNS.digest64.test(digest)) {
      throw new ContractValidationError('InputCapture.attachment_digests entries must be sha256 hex')
    }
  }
  return capture
}

// ---------------------------------------------------------------------------
// E5 persistent references
// ---------------------------------------------------------------------------

export type ReferenceStatus = 'prepared' | 'published' | 'withdrawn' | 'unverified'

export interface RevisionSelector {
  op: 'exact' | 'floor' | 'any'
  revision?: string | null
}

export function validateRevisionSelector(selector: RevisionSelector): RevisionSelector {
  if (!['exact', 'floor', 'any'].includes(selector.op)) {
    throw new ContractValidationError(`RevisionSelector.op ${selector.op} is not frozen`)
  }
  if (selector.op === 'any') {
    if (selector.revision != null) {
      throw new ContractValidationError('RevisionSelector.revision must be null when op=any')
    }
  } else if (typeof selector.revision !== 'string' || !PATTERNS.revision.test(selector.revision)) {
    throw new ContractValidationError('RevisionSelector.revision is required unless op=any')
  }
  return selector
}

export interface PersistentReference {
  relation_id: string
  source_key: CanonicalFactTarget
  source_revision: string
  target_key: CanonicalFactTarget
  revision_selector: RevisionSelector
  declaring_owner_domain: string
  policy_contract_id: string
  policy_contract_version: number
  operation_id: string
  source_commit_evidence: string
  status: ReferenceStatus
  coverage_epoch: number
}

// ---------------------------------------------------------------------------
// E4 services
// ---------------------------------------------------------------------------

export type SecretAvailability = 'available' | 'locked' | 'unavailable' | 'unknown'

export interface SecretRef {
  ref: string
  revision: string
  owner_namespace: string
  access_purpose: string
}

export type HostDialogStatus =
  'selected' | 'confirmed' | 'cancelled' | 'revoked' | 'unavailable' | 'failed' | 'unknown'

export interface HostDialogRequest {
  operation_id: string
  caller_activation: string
  caller_generation: number
  scope: string
  purpose: string
  options?: string[]
}

export interface HostDialogResult {
  operation_id: string
  status: HostDialogStatus
  selected_handle?: string | null
  confirmed_option?: string | null
}

export function validateHostDialogResult(result: HostDialogResult): HostDialogResult {
  check(PATTERNS.operation, result.operation_id, 'HostDialogResult.operation_id')
  if (result.status === 'selected' && !result.selected_handle) {
    throw new ContractValidationError('selected results must carry a handle to release or register')
  }
  if (result.status === 'confirmed' && !result.confirmed_option) {
    throw new ContractValidationError('confirmed results must name the confirmed option')
  }
  if ((result.status === 'cancelled' || result.status === 'revoked') &&
      (result.selected_handle != null || result.confirmed_option != null)) {
    throw new ContractValidationError('cancelled/revoked results must be write-free')
  }
  return result
}
