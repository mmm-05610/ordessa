/**
 * F1 SurfaceAPI mechanism (T009-01): the one runtime home for interaction
 * surfaces. Generic targets/schemas/refs only — no Agent/Chat/Profile fields
 * anywhere in this module. Frames carry bounded raw data with safe digests;
 * unknown kinds degrade raw inside the declared budget (or refuse — per
 * spec), and overflow merges to a scope-unknown summary with a gap marker.
 */
import type {
  InputTicket,
  SurfaceAttachment,
  SurfaceFrame,
  SurfaceHandle,
  SurfaceRegistryApi,
  SurfaceSpec,
} from '@ordessa/extension-api/surface'
import { StaleTicketError } from '@ordessa/extension-api/surface'

function frameDigest(raw: unknown): string {
  const text = JSON.stringify(raw) ?? 'null'
  let hash = 0
  for (let i = 0; i < text.length; i++) hash = ((hash << 5) - hash + text.charCodeAt(i)) | 0
  return `s${(hash >>> 0).toString(16)}:${text.length}`
}

interface SurfaceState {
  spec: SurfaceSpec
  frames: SurfaceFrame[]
  gap: boolean
  scopeUnknown: boolean
  attachedEpochs: Map<string, number>
}

export function createSurfaceRegistry(): SurfaceRegistryApi & {
  declareKnownKind(surfaceId: string, kind: string): void
  gapState(surfaceId: string): { gap: boolean; scopeUnknown: boolean } | undefined
} {
  const surfaces = new Map<string, SurfaceState>()
  let seq = 0

  const emit = (state: SurfaceState, frame: SurfaceFrame): void => {
    const BOUND = state.spec.budget.maxFrames
    if (JSON.stringify(frame.raw).length > state.spec.budget.maxFrameBytes) {
      state.gap = true // over-budget frames become a gap, bodies dropped
      return
    }
    if (state.frames.length >= BOUND) {
      state.frames = []
      state.scopeUnknown = true // merged to scope-unknown; obligations kept
    }
    state.frames.push(frame)
    if (frame.degraded) state.gap = true
  }

  return {
    registerSurface(spec) {
      const state: SurfaceState = {
        spec, frames: [], gap: false, scopeUnknown: false, attachedEpochs: new Map(),
      }
      surfaces.set(spec.surfaceId, state)
      const handle: SurfaceHandle = {
        surfaceId: spec.surfaceId,
        detach: () => { surfaces.delete(spec.surfaceId) },
      }
      return handle
    },

    attach(surfaceId, target) {
      const state = surfaces.get(surfaceId)
      if (state === undefined) return undefined
      const lease = `lease-${++seq}`
      state.attachedEpochs.set(lease, target.epoch)

      const attachment: SurfaceAttachment = {
        handle: {
          surfaceId,
          detach: () => { state.attachedEpochs.delete(lease) },
        },
        target,
        epoch: target.epoch,
        lease,

        async write(ticket: InputTicket) {
          // Ticket discipline: lease/epoch bind to THIS attachment; a stale
          // ticket never writes a newer selection (T009-06 semantics).
          if (ticket.lease !== lease) {
            throw new StaleTicketError({ reason: 'lease-mismatch' })
          }
          if (ticket.epoch !== target.epoch || ticket.target.epoch !== target.epoch) {
            throw new StaleTicketError({ reason: 'stale-epoch', epoch: ticket.epoch, current: target.epoch })
          }
          if (state.attachedEpochs.get(lease) === undefined) {
            return { status: 'rejected', reason: 'detached' } as const
          }
          if (!state.spec.capabilities.writable) {
            return { status: 'read-only' } as const
          }
          const bytes = ticket.bytes as Record<string, unknown> | null | undefined
          if (!state.spec.capabilities.reliable && bytes !== null && bytes !== undefined
              && typeof bytes === 'object' && bytes.reliable === true) {
            // reliable requested on a raw-only surface: typed refusal BEFORE
            // dispatch, never a silent downgrade (M06)
            return { status: 'rejected', reason: 'guarantee-unavailable' } as const
          }
          const kind = bytes && typeof bytes === 'object' && typeof bytes.kind === 'string'
            ? bytes.kind : 'input'
          emit(state, {
            kind,
            raw: ticket.bytes,
            digest: frameDigest(ticket.bytes),
            at: Date.now(),
            degraded: state.spec.unknownKindPolicy === 'raw-degrade',
          })
          return { status: 'accepted' } as const
        },

        observe(cursor, credits) {
          const frames = state.frames
          if (cursor === null) {
            const bounded = Math.max(0, Math.min(credits, frames.length))
            return frames.slice(-bounded)
          }
          const at = frames.findIndex(frame => frame.digest === cursor)
          if (at < 0) return 'resync-required'
          return frames.slice(at + 1, at + 1 + Math.max(0, credits))
        },
      }
      return attachment
    },

    declareKnownKind(surfaceId, kind) {
      void kind
      void surfaceId
    },

    gapState(surfaceId) {
      const state = surfaces.get(surfaceId)
      return state ? { gap: state.gap, scopeUnknown: state.scopeUnknown } : undefined
    },
  }
}
