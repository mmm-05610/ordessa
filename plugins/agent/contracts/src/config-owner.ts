/**
 * A1 — Agent domain public contract (spec 026/002 freeze).
 *
 * The five owners (SessionOwner, SessionConfigOwner, SubmissionOwner,
 * RunOwner, InteractionOwner) are internal modules of ONE Agent domain; this
 * file freezes the PUBLIC read/observe/dispatch surface every consumer
 * (Chat, Profile, Model-provider, independent views) programs against. The
 * platform never re-exports these; the backend owner lands in order 010.
 *
 * Wire discipline: types that cross the wire mirror the field names frozen
 * in `ordessa_environment_api` (spec 026 order 002), so a ConfigSnapshot
 * serialized by the backend owner decodes here without a second vocabulary.
 */
import type { Availability } from './agent'

/** Field-level knowledge — never a boolean "configured". */
export type FieldState = 'known' | 'unset' | 'unknown'

/**
 * The one authoritative config state chain per AgentTarget. `confirmed` is
 * the trusted-native-evidence projection, `intents` the ordered operations
 * not yet confirmed applied; `resolved` is DERIVED, never a second store
 * (A1 §公开读写与观察).
 */
export interface ConfigSnapshot {
  ownerRef: string
  revision: number
  observedEvidence: 'native' | 'unset' | 'unknown'
  operations: ReadonlyArray<ConfigOperationSummary>
  resolved: Readonly<Record<string, unknown>>
  fields: Readonly<Record<string, FieldState>>
}

export interface ConfigOperationSummary {
  operationId: string
  patchKinds: ReadonlyArray<'present' | 'unset'>
  sourceRef: string
  submittedAtOrder: number
  state: 'pending' | 'applied' | 'unknown' | 'conflict'
}

export interface ConfigOperationReceipt {
  operationId: string
  accepted: boolean
  conflictReason?: 'revision-conflict' | 'authority-conflict' | 'binding-stale'
}

/**
 * A submitted input with its frozen capture. Success consumes exactly the
 * captured draft revision; late edits never clear a draft by text equality
 * (C1/A1 §提交与生命周期).
 */
export interface SubmissionReceipt {
  submissionId: string
  consumedDraftRevision: number
  outcome: 'accepted' | 'known-rejected' | 'unknown'
  /** Present only when outcome === 'unknown': the stable id to QUERY, never resend. */
  queryRequestKey?: string
}

/** Public capability descriptors (per A1 §Harness专属接入). */
export interface AgentDomainCapabilities {
  configOperations: Availability
  submissions: Availability
  /** Reliable submissions require the Harness-declared evidence chain (C1). */
  reliableSubmissions: Availability
  historyRead: Availability
}

/**
 * Counterexample gates frozen with the type (enforced by the owner, asserted
 * by tests in order 010):
 *  - two controls dispatching to the same target see ONE owner revision
 *    chain — there is no `setCurrentConfig` on this surface;
 *  - `SubmissionReceipt.outcome === 'unknown'` never carries a resend token;
 *  - `ConfigSnapshot.revision` comes from the owner, never from a UI clock.
 */
