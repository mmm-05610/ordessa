import { randomUUID } from 'node:crypto'
import type { ServerTarget } from './target'

export const WIRE_VERSION = 'wire/1'

/** The Server's closed error family; anything outside it arrives as UNAVAILABLE. */
const ERROR_CODES = new Set(['UNAVAILABLE', 'UNAUTHENTICATED', 'FORBIDDEN', 'NOT_FOUND', 'CONFLICT_VERSION',
  'CONFLICT_REFERENCE', 'CONFLICT_REQUEST', 'INVALID_REQUEST', 'CAPABILITY_UNSUPPORTED', 'OUTCOME_UNKNOWN',
  'WORKER_UNREACHABLE', 'APPROVAL_INVALID'])

export class WireError extends Error {
  constructor(readonly code: string, message: string, readonly current?: unknown, readonly internalCode?: string) {
    super(message)
  }
}

/** The Server's typed reason, kept only as a gate input: it is never joined into a message the renderer
 * could display, and anything that is not code-shaped is dropped rather than passed through. */
const typedReason = (value: unknown): string | undefined =>
  typeof value === 'string' && /^[A-Z][A-Z0-9_]{0,63}$/.test(value) ? value : undefined

export interface EventFrame {
  eventId: string
  sessionId: string
  seq: number
  cursor: string
  emittedAt: string
  event: { kind: string } & Record<string, unknown>
}

interface Envelope<Result> {
  id?: string | number | null
  result?: Result
  error?: { code?: unknown; message?: unknown; details?: { internalCode?: unknown }; current?: unknown }
}

const statusRefusal = (status: number): string =>
  status === 401 ? 'UNAUTHENTICATED' : status === 403 ? 'FORBIDDEN' : status === 400 ? 'INVALID_REQUEST' : 'UNAVAILABLE'

/**
 * One JSON-RPC call per HTTP POST: the wire surface has no request channel on the socket.
 * A protocol-level rejection is delivered as HTTP 200 with an error envelope.
 */
export class WireClient {
  private sequence = 0
  constructor(private readonly target: ServerTarget) {}

  /** Mutating wire methods require an id of at least 8 characters; the Server dedupes only the sessions.send scope. */
  newRequestId(purpose: string): string {
    return `${purpose}_${randomUUID()}`
  }

  async call<Result>(method: string, params: Record<string, unknown>): Promise<Result> {
    const id = `w${++this.sequence}`
    let response: Response
    try {
      response = await fetch(`${this.target.origin}/wire/v1/${method}`, {
        method: 'POST',
        // A redirect can replay the JSON body elsewhere, and a same-origin redirect
        // can replay the bearer too. The Server wire has no redirect contract.
        redirect: 'error',
        headers: { 'content-type': 'application/json', authorization: `Bearer ${this.target.token}` },
        body: JSON.stringify({ jsonrpc: '2.0', id, method, params }),
      })
    } catch {
      // Never name the token or its locator here; the origin is already known to the caller.
      throw new WireError('UNAVAILABLE', `${method} did not reach the Server at ${this.target.origin}`)
    }
    const envelope = await response.json().catch(() => undefined) as Envelope<Result> | undefined
    const refusal = typeof envelope?.error?.message === 'string' && envelope.error.message ? envelope.error.message : undefined
    if (!response.ok) {
      throw new WireError(statusRefusal(response.status), refusal ?? `${method} was refused with HTTP ${response.status}`)
    }
    if (!envelope || (envelope.id != null && envelope.id !== id)) throw new WireError('UNAVAILABLE', `${method} returned an unmatched response`)
    if (envelope.error) {
      const code = typeof envelope.error.code === 'string' && ERROR_CODES.has(envelope.error.code) ? envelope.error.code : 'UNAVAILABLE'
      throw new WireError(code, refusal ?? `${method} failed`, envelope.error.current, typedReason(envelope.error.details?.internalCode))
    }
    return envelope.result as Result
  }
}

export interface StreamHandle { close(): void }

/** Subscription is the socket itself: one session per connection, resuming from a `history.snapshot`
 * cursor. Node sends no Origin header here, which the Server's loopback policy accepts. */
/** Only Node's WebSocket honours a header-bearing options object; the DOM lib types the second argument as protocols. */
type NodeWebSocket = new (url: string, options: { headers: Record<string, string> }) => WebSocket
const connectEventSocket = WebSocket as unknown as NodeWebSocket

export function openEventStream(target: ServerTarget, sessionId: string, cursor: string | undefined,
  handlers: { frame(frame: EventFrame): void; down(reason: string): void }): StreamHandle {
  const query = new URLSearchParams({ sessionId })
  if (cursor) query.set('cursor', cursor)
  const socket = new connectEventSocket(`${target.socket}/wire/v1/event-stream?${query}`, {
    headers: { authorization: `Bearer ${target.token}` },
  })
  // One terminal statement per subscription: a failing socket reports error and close back to back,
  // and a deliberate close is not a down reason the renderer should ever see.
  let finished = false
  const settle = (reason: string) => { if (finished) return; finished = true; handlers.down(reason) }
  socket.addEventListener('message', message => {
    if (finished) return
    try {
      handlers.frame(JSON.parse(String(message.data)) as EventFrame)
    } catch {
      settle('malformed event frame')
    }
  })
  socket.addEventListener('error', () => settle('event stream unavailable'))
  socket.addEventListener('close', event => settle(`event stream closed (${String((event as CloseEvent).reason ?? (event as CloseEvent).code)})`))
  return {
    close() {
      if (finished) return
      finished = true
      try { socket.close() } catch {}
    },
  }
}
