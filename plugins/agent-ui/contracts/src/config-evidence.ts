/**
 * Native ConfigEvidence chain (T010-05): the ordered intake of Harness
 * observation frames for one target. Frames are `snapshot` (complete: they
 * establish the whole field set and supersede the out-of-order cache) or
 * `patch` (partial: they chain onto the established snapshot). Semantics
 * locked here:
 * - known/unset/unknown per field; a patch only ever touches its listed fields;
 * - out-of-order frames are buffered in a BOUNDED cache and applied in order
 *   when the gap fills (overflow refuses the newcomer, never evicts);
 * - two different frames at one revision are a CONFLICT: captures at that
 *   revision are blocked (fail-closed), the chain state is untouched;
 * - an identical re-observation is a duplicate no-op — it NEVER unlocks a
 *   pending unknown (only a NEW observation may change a field);
 * - a complete new snapshot clears the out-of-order cache (buffered frames
 *   are obsolete).
 */
import type { FieldState } from './config-owner' // single definition (A1 vocabulary)

export type ObservedState = 'native' | 'unset' | 'unknown'

export interface EvidenceFrame {
  readonly kind: 'snapshot' | 'patch'
  readonly revision: number
  readonly observed?: ObservedState
  readonly fields?: Readonly<Record<string, FieldState>>
}

export type EvidenceIntake =
  | { status: 'applied'; revision: number }
  | { status: 'buffered'; revision: number; buffered: number }
  | { status: 'duplicate'; revision: number }
  | { status: 'conflict'; revision: number }
  | { status: 'obsolete'; revision: number }
  | { status: 'rejected'; reason: string }

export type CaptureVerdict = 'settled' | 'conflicting' | 'unobserved'

const FIELD_STATES: readonly FieldState[] = ['known', 'unset', 'unknown']
const OBSERVED_STATES: readonly ObservedState[] = ['native', 'unset', 'unknown']

function digestOf(frame: EvidenceFrame): string {
  const fields = Object.entries(frame.fields ?? {}).sort(([a], [b]) => a.localeCompare(b))
  return JSON.stringify([frame.kind, frame.observed ?? null, fields])
}

export class ConfigEvidenceChain {
  private base = 0
  private observed: ObservedState = 'unset'
  private fields: Record<string, FieldState> = {}
  private readonly buffer = new Map<number, EvidenceFrame>()
  private readonly digests = new Map<number, string>()
  private readonly conflicts = new Set<number>()
  private readonly maxBuffered: number

  constructor(options: { maxBuffered?: number } = {}) {
    this.maxBuffered = options.maxBuffered ?? 8
  }

  intake(frame: EvidenceFrame): EvidenceIntake {
    if (!Number.isSafeInteger(frame.revision) || frame.revision < 1)
      return { status: 'rejected', reason: 'bad revision' }
    if (frame.kind !== 'snapshot' && frame.kind !== 'patch')
      return { status: 'rejected', reason: 'bad frame kind' }
    if (frame.observed !== undefined && !OBSERVED_STATES.includes(frame.observed))
      return { status: 'rejected', reason: 'bad observed state' }
    for (const state of Object.values(frame.fields ?? {})) {
      if (!FIELD_STATES.includes(state)) return { status: 'rejected', reason: 'bad field state' }
    }
    const digest = digestOf(frame)
    const known = this.digests.get(frame.revision)
    if (known !== undefined || this.buffer.has(frame.revision)) {
      const previous = known ?? digestOf(this.buffer.get(frame.revision)!)
      if (previous === digest) return { status: 'duplicate', revision: frame.revision }
      this.conflicts.add(frame.revision) // same revision, different content
      return { status: 'conflict', revision: frame.revision }
    }
    if (frame.revision <= this.base) return { status: 'obsolete', revision: frame.revision }
    if (frame.revision === this.base + 1 || frame.kind === 'snapshot') {
      // an in-order frame applies; a COMPLETE snapshot also applies across a
      // gap (it is self-sufficient) and clears the cache in apply()
      this.apply(frame, digest)
      while (this.buffer.has(this.base + 1)) {
        const next = this.buffer.get(this.base + 1)!
        this.buffer.delete(this.base + 1)
        this.apply(next, digestOf(next))
      }
      return { status: 'applied', revision: frame.revision }
    }
    if (this.buffer.size >= this.maxBuffered) {
      // bounded: refuse the newcomer (re-sent later), never evict into a gap
      return { status: 'rejected', reason: 'buffer-full' }
    }
    this.buffer.set(frame.revision, frame)
    return { status: 'buffered', revision: frame.revision, buffered: this.buffer.size }
  }

  private apply(frame: EvidenceFrame, digest: string): void {
    this.digests.set(frame.revision, digest)
    if (this.digests.size > 32) {
      const oldest = this.digests.keys().next().value
      if (oldest !== undefined && oldest < this.base - 16) this.digests.delete(oldest)
    }
    if (frame.kind === 'snapshot') {
      // complete: the whole field set is re-established and the out-of-order
      // cache is obsolete (T010-05: a complete new snapshot clears the cache)
      this.fields = { ...(frame.fields ?? {}) }
      this.observed = frame.observed ?? this.observed
      this.buffer.clear()
    } else {
      this.fields = { ...this.fields, ...(frame.fields ?? {}) }
      if (frame.observed !== undefined) this.observed = frame.observed
    }
    this.base = frame.revision
  }

  /** The settled field states (the chain's projection). */
  getFields(): Readonly<Record<string, FieldState>> {
    return { ...this.fields }
  }

  getObserved(): ObservedState {
    return this.observed
  }

  get revision(): number {
    return this.base
  }

  /** A capture may bind only to a SETTLED revision; a conflicted revision is
   * blocked forever (fail-closed), an unobserved one is not yet safe. */
  captureVerdictAt(revision: number): CaptureVerdict {
    if (this.conflicts.has(revision)) return 'conflicting'
    return revision <= this.base ? 'settled' : 'unobserved'
  }
}
