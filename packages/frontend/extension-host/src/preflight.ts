/**
 * F2 preflight gate (R7/M14 `oe-f5/1`, T008-08; lifecycle-evidence §前端停用原子门).
 *
 * One admission fence freezes, for a disabling owner, ALL THREE together:
 * new dispatch, required-borrow, and batch publish. The gate records the
 * dependency revision and the committed-work set before deciding drain.
 * Cross-await races are barred: after a "no pending" judgement, a new
 * required relation must NOT be able to slip in (the barrier token is
 * checked on every admission). Refusal or timeout restores the original
 * contributions and admission — never a half-disabled UI that still lets
 * new operations through.
 *
 * U-layer (real windows) verification stays at T008-07; this is the S/I
 * mechanism with directed counterexamples.
 */
import { f5 } from '@extensions/ordessa.contracts/contract.js'

const StaleGenerationError = f5.StaleGenerationError

export type AdmissionKind = 'dispatch' | 'required-borrow' | 'batch-publish'

export interface PreflightRecord {
  readonly owner: string
  readonly dependencyRevision: string
  readonly committedWork: ReadonlyArray<string>
  readonly frozenAt: number
}

export type PreflightOutcome =
  | { kind: 'drained'; record: PreflightRecord }
  | { kind: 'refused'; reason: string; restored: true }
  | { kind: 'timeout'; restored: true }

export interface PreflightGateOptions {
  /** Barrier token generator; increments on freeze and on restore. */
  now?: () => number
  timeoutMs?: number
}

export class PreflightGate {
  private frozen = new Map<string, { record: PreflightRecord; barrier: number }>()
  private barrier = 0
  private admitted = new Set<string>() // `${owner}|${kind}` counters while live

  constructor(private readonly options: PreflightGateOptions = {}) {}

  /** Admission check used by dispatch / borrow / publish faces alike. */
  admit(owner: string, kind: AdmissionKind): void {
    const entry = this.frozen.get(owner)
    if (entry !== undefined) {
      throw new StaleGenerationError(
        `owner ${owner} is frozen for drain: new ${kind} admissions are cut`)
    }
    this.admitted.add(`${owner}|${kind}`)
  }

  releaseAdmission(owner: string, kind: AdmissionKind): void {
    this.admitted.delete(`${owner}|${kind}`)
  }

  /**
   * Start the atomic preflight freeze. Returns the recorded snapshot and a
   * barrier token; every later admission for this owner is refused, and a
   * late "required" relation arriving after the no-pending judgement is
   * barred by the same token (cross-await race case).
   */
  freeze(owner: string, dependencyRevision: string, committedWork: readonly string[]): {
    record: PreflightRecord
    barrier: number
    /** Completes the drain: releases the owner's frozen state for good. */
    drain(): PreflightOutcome
    /** Refuses/timeout path: restores admission and contributions exactly. */
    restore(reason: string): PreflightOutcome
  } {
    if (this.frozen.has(owner)) {
      throw new StaleGenerationError(`owner ${owner} is already frozen`)
    }
    this.barrier += 1
    const record: PreflightRecord = {
      owner,
      dependencyRevision,
      committedWork: Object.freeze([...committedWork]),
      frozenAt: this.options.now?.() ?? Date.now(),
    }
    this.frozen.set(owner, { record, barrier: this.barrier })
    return {
      record,
      barrier: this.barrier,
      drain: () => {
        this.frozen.delete(owner)
        return { kind: 'drained', record }
      },
      restore: (reason: string) => {
        this.frozen.delete(owner)
        return reason === 'timeout'
          ? { kind: 'timeout', restored: true }
          : { kind: 'refused', reason, restored: true }
      },
    }
  }

  /** True while the owner is frozen — used by the cross-await barrier. */
  isFrozen(owner: string): boolean {
    return this.frozen.has(owner)
  }

  /** The no-pending judgement must be re-checked against the barrier token:
   *  a required relation registered AFTER the judgement throws. */
  requireRelation(owner: string, barrier: number, relation: string): void {
    const entry = this.frozen.get(owner)
    if (entry === undefined || entry.barrier !== barrier) {
      throw new StaleGenerationError(
        `required relation ${relation} arrived after the no-pending judgement ` +
        '(cross-await race): refused, the freeze cannot reopen')
    }
  }
}
