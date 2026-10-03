/**
 * F1 SurfaceAPI (T009-01; contracts/frontend.md §SurfaceAPI) — the generic
 * interaction-surface contract: registerSurface(spec)/attach(ref)/detach/
 * write(inputTicket)/observe(cursor, credit).
 *
 * Specs bind generic targets, schemas and refs — no Agent/Chat/Profile
 * fields. Unknown kinds degrade raw within bounds; a read-only surface never
 * answers control requests. Input tickets freeze target/epoch/lease so a
 * late ticket cannot write a newer selection (StaleGeneration).
 */

export interface SurfaceTarget {
  /** Generic target identity — never a window id, never a socket id. */
  readonly kind: string
  readonly ref: string
  readonly epoch: number
}

export interface SurfaceSpec {
  readonly surfaceId: string
  readonly source: string
  readonly executionDomain: 'frontend' | 'backend'
  readonly schemaVersion: string
  readonly budget: { maxFrameBytes: number; maxFrames: number }
  readonly capabilities: {
    readonly raw: boolean
    readonly reliable: boolean
    readonly writable: boolean
  }
  /** Unknown target kinds degrade raw within budget; never a verdict. */
  readonly unknownKindPolicy: 'raw-degrade' | 'refuse'
}

export interface InputTicket {
  readonly target: SurfaceTarget
  readonly lease: string
  readonly epoch: number
  readonly sequence: number
  readonly bytes: unknown
}

export interface SurfaceFrame {
  readonly kind: string
  readonly raw: unknown
  readonly digest: string
  readonly at: number
  readonly degraded: boolean
}

export interface SurfaceHandle {
  readonly surfaceId: string
  detach(): void
}

export interface SurfaceAttachment {
  readonly handle: SurfaceHandle
  /** The frozen binding a ticket must carry (T009-06 target/epoch/lease). */
  readonly target: SurfaceTarget
  readonly epoch: number
  readonly lease: string
  write(ticket: InputTicket): Promise<{ status: 'accepted' | 'rejected' | 'read-only' | 'stale'; reason?: string }>
  observe(cursor: string | null, credits: number): readonly SurfaceFrame[] | 'resync-required'
}

export interface SurfaceRegistryApi {
  registerSurface(spec: SurfaceSpec): SurfaceHandle
  attach(surfaceId: string, target: SurfaceTarget): SurfaceAttachment | undefined
}

export class StaleTicketError extends Error {
  readonly code = 'F5_STALE_GENERATION'
  constructor(readonly details: Record<string, unknown>, message = 'input ticket is stale (epoch/lease)') {
    super(message)
    this.name = 'StaleTicketError'
  }
}
