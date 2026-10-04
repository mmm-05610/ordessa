/**
 * F5 projection adapter (R7/M14 `oe-f5/1`, T008-14) — the frozen
 * `AuthorizedProjection`/`ProjectionFrame` seam.
 *
 * The observation mechanics are the E3 `readAndSubscribe` contract owned by
 * the Environment. This adapter retains a bounded replay window, reports any
 * lost continuity explicitly, and stops callbacks once closed or revoked.
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
  const requestedLimit = options.bufferLimit ?? 32
  const bufferLimit = Number.isFinite(requestedLimit) ? Math.max(1, Math.floor(requestedLimit)) : 32
  let closed = false
  let revoked = false
  let frames: ProjectionFrame<T>[] = []
  let cursorSeq = 0
  let overflowed = false

  let attached = false
  let detachRequested = false
  let detached = false
  let detachSource: () => void = () => undefined

  function detach(): void {
    if (detached) return
    detachRequested = true
    if (attached) {
      detached = true
      detachSource()
    }
  }

  function push(frame: ProjectionFrame<T>): void {
    if (closed || revoked) return

    if (frame.kind === 'snapshot') {
      // A full snapshot starts a new complete chain and repairs earlier gaps.
      frames = [frame]
      overflowed = false
      return
    }

    frames.push(frame)
    if (frames.length > bufferLimit) {
      frames.shift()
      overflowed = true
    }
  }

  const sink = {
    snapshot(revision: string, value: T): void {
      if (closed || revoked) return
      push({ kind: 'snapshot', revision, value, cursor: `c-${++cursorSeq}` })
    },
    delta(revision: string, patch: unknown): void {
      if (closed || revoked) return
      push({ kind: 'delta', revision, patch, cursor: `c-${++cursorSeq}` })
    },
    gap(reason: 'gap' | 'overflow' | 'reconnect'): void {
      if (closed || revoked) return
      push({ kind: 'resync-required', reason })
    },
    revoked(): void {
      if (closed || revoked) return
      revoked = true
      // Revocation makes the locally accessible projection unavailable.
      frames = []
      overflowed = false
      detach()
    },
  }

  const attachedSource = source.attach(sink)
  detachSource = attachedSource.detach
  attached = true
  // attach() may synchronously call revoked() before it returns its handle.
  if (detachRequested) {
    detached = true
    detachSource()
  }

  return {
    authorization: { scope: options.scope, generation: options.generation },

    observe(cursor: string | null, credits: number): ProjectionFrame<T> {
      if (revoked) return { kind: 'revoked' }

      const availableCredits = Number.isFinite(credits) ? Math.floor(credits) : bufferLimit
      if (availableCredits <= 0) {
        // No new frame is delivered without credit. Returning the cursor frame
        // preserves the caller's position while leaving subsequent data queued.
        if (cursor !== null) {
          const current = frames.find(
            frame => (frame.kind === 'snapshot' || frame.kind === 'delta') && frame.cursor === cursor,
          )
          if (current !== undefined) return current
        }
        return { kind: 'resync-required', reason: 'reconnect' }
      }

      if (cursor === null) {
        if (overflowed) return { kind: 'resync-required', reason: 'overflow' }
        const latestSnapshot = [...frames].reverse().find(frame => frame.kind === 'snapshot')
        return latestSnapshot ?? { kind: 'resync-required', reason: 'reconnect' }
      }

      const at = frames.findIndex(
        frame => (frame.kind === 'snapshot' || frame.kind === 'delta') && frame.cursor === cursor,
      )
      if (at < 0) {
        // The requested cursor is outside the retained contiguous window.
        return { kind: 'resync-required', reason: 'gap' }
      }

      const next = frames[at + 1]
      return next ?? frames[at]
    },

    close(): void {
      if (closed || revoked) return
      closed = true
      // Closing this local observation prevents more delivery, but does not
      // claim authorization was revoked or erase the last readable snapshot.
      detach()
    },
  }
}
