/**
 * F5 projection adapter (R7/M14 `oe-f5/1`, T008-14) — the frozen
 * `AuthorizedProjection`/`ProjectionFrame` seam.
 *
 * Deliberately thin: the observation mechanics are the E3
 * `readAndSubscribe` contract owned by the Environment (003/004 backend);
 * the Desktop bridge feeds that into a client-side observable. This module
 * adapts ANY such observable into the frozen frame vocabulary and enforces
 * two honesty rules: gaps become `resync-required` (never silently dropped),
 * and a revoked authorization stops delivery (no pretend-continuity). No
 * second subscription broker is defined here.
 */
import type {
  AuthorizedProjection,
  ProjectionFrame,
} from '../../../contracts/foundation/src/open-environment/f5/types'

export interface ObservableSource<T> {
  /** Pull-based adapter input: the source pushes frames through the sink. */
  attach(sink: {
    snapshot(revision: string, value: T): void
    delta(revision: string, patch: unknown): void
    gap(reason: 'gap' | 'overflow' | 'reconnect'): void
    revoked(): void
  }): { detach(): void }
}

export interface ProjectionAdapterOptions {
  scope: string
  generation: number
  /** History buffer bound for late subscribers; exceeded => resync-required. */
  bufferLimit?: number
}

export function projectionFromObservable<T>(
  source: ObservableSource<T>,
  options: ProjectionAdapterOptions,
): AuthorizedProjection<T> & { close(): void } {
  const bufferLimit = options.bufferLimit ?? 32
  let revoked = false
  let frames: ReadonlyArray<ProjectionFrame<T>> = []
  let cursorSeq = 0
  let detached = false
  let detach: () => void = () => undefined

  const attach = source.attach({
    snapshot(revision, value) {
      if (revoked) return
      push({ kind: 'snapshot', revision, value, cursor: `c-${++cursorSeq}` })
    },
    delta(revision, patch) {
      if (revoked) return
      push({ kind: 'delta', revision, patch, cursor: `c-${++cursorSeq}` })
    },
    gap(reason) {
      if (revoked) return
      push({ kind: 'resync-required', reason })
    },
    revoked() {
      revoked = true
      push({ kind: 'revoked' })
      detach()
    },
  })
  detach = attach.detach

  function push(frame: ProjectionFrame<T>): void {
    frames = [...frames, frame].slice(-bufferLimit)
    if (frames.length > bufferLimit) {
      // overflow: the tail is bounded; consumers must resync.
      frames = [...frames.slice(-bufferLimit), { kind: 'resync-required', reason: 'overflow' }]
    }
  }

  return {
    authorization: { scope: options.scope, generation: options.generation },

    observe(cursor: string | null, credits: number): ProjectionFrame<T> {
      if (revoked) return { kind: 'revoked' }
      const bounded = Math.max(0, Math.min(credits, bufferLimit))
      if (cursor === null) {
        const latest = frames.filter(f => f.kind === 'snapshot').at(-1)
        return latest ?? { kind: 'resync-required', reason: 'reconnect' }
      }
      const at = frames.findIndex(
        f => (f.kind === 'snapshot' || f.kind === 'delta') && f.cursor === cursor)
      if (at < 0) {
        // The requested cursor fell out of the bounded window: honest gap.
        return { kind: 'resync-required', reason: 'gap' }
      }
      const next = frames.slice(at + 1, at + 1 + bounded)
      return next[0] ?? frames[at]
    },

    close(): void {
      if (detached) return
      detached = true
      detach()
    },
  }
}
