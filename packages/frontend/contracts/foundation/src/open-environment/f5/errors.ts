/**
 * F5 typed error family (R7/M14, contract freeze `oe-f5/1`).
 *
 * These errors are the platform-infrastructure refusals. They never
 * reinterpret wire `Refused`/`Unknown` results (those stay transport facts)
 * and never carry business verdicts. Each error has exactly one
 * counterexample case pinned in the freeze tests.
 */
export class F5Error extends Error {
  readonly code: string = 'F5_ERROR'
  constructor(message: string, readonly details: Record<string, unknown> = {}) {
    super(message)
    this.name = new.target.name
  }
}

/** A consumer attempted to write a snapshot or store (owner-only write face). */
export class WriteAccessDeniedError extends F5Error {
  override readonly code: string = 'F5_WRITE_ACCESS_DENIED'
}

/** A published (immutable) snapshot was mutated after publication. */
export class SnapshotMutatedError extends F5Error {
  override readonly code: string = 'F5_SNAPSHOT_MUTATED'
}

/** A late result addressed a stale target/activation generation. */
export class StaleGenerationError extends F5Error {
  override readonly code: string = 'F5_STALE_GENERATION'
}

/** A query facade was asked to carry a non-idempotent effect. */
export class QueryEffectMismatchError extends F5Error {
  override readonly code: string = 'F5_QUERY_EFFECT_MISMATCH'
}

/** Edit-session conflict, including the ABA case (late success ≠ new draft). */
export class EditConflictError extends F5Error {
  override readonly code: string = 'F5_EDIT_CONFLICT'
}

/** UI-storage refused a record with an unknown schema version. */
export class UiSchemaUnknownError extends F5Error {
  override readonly code: string = 'F5_UI_SCHEMA_UNKNOWN'
}

/** An interaction handle outlived its scope (late callback target). */
export class InteractionScopeRevokedError extends F5Error {
  override readonly code: string = 'F5_INTERACTION_SCOPE_REVOKED'
}
