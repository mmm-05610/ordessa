import type { WirePort, WireReason, WireResult } from '@ordessa/interface-contracts'
/** A method name is data, not code: anything that could escape the path segment is refused. */
const METHOD_NAME = /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/

/** One request id per call, so a caller can correlate its own retry by hand. */
function requestId(): string {
  return `req_${Math.random().toString(16).slice(2)}${Date.now().toString(16)}`
}

/** Every result is frozen: a consumer cannot mutate a fact it was handed. */
function frozen<T extends object>(value: T): T {
  return Object.freeze(value)
}

export interface HttpWirePortOptions {
  readonly origin: string
  readonly wirePathPrefix: string
  readonly scope: string | null
  /**
   * Reads the bearer. The CALLER supplies this, and the caller is the main
   * process. The port never stores the token as a field, so there is nothing
   * for a plugin to reach through `port.token` — the property does not
   * exist, at the type level and at runtime.
   */
  readonly readToken: () => Promise<string | null>
  /** Injected for tests; defaults to global `fetch`. */
  readonly fetchImpl?: typeof fetch
  /** Per-call budget. */
  readonly timeoutMs?: number
}

/**
 * The production port: `POST /wire/v1/{method}` with a Bearer injected here
 * and nowhere else.
 */
export class HttpWirePort implements WirePort {
  readonly #options: HttpWirePortOptions
  #unavailable: WireReason | null = null

  constructor(options: HttpWirePortOptions) {
    this.#options = options
  }

  get ready(): boolean {
    return this.#unavailable === null
  }

  get scope(): string | null {
    return this.#options.scope
  }

  async call(
    method: string,
    params: Readonly<Record<string, unknown>>,
  ): Promise<WireResult> {
    const id = requestId()
    if (this.#unavailable !== null) {
      return frozen({ kind: 'Unknown', requestId: id, reason: this.#unavailable })
    }
    if (typeof method !== 'string' || !METHOD_NAME.test(method)) {
      return frozen({ kind: 'Unknown', requestId: id, reason: 'invalid-method' })
    }

    // A token that cannot be read is `transport-unreachable`, not a thrown
    // error: from the caller's side the Server is simply not addressable.
    let token: string | null
    try {
      token = await this.#options.readToken()
    } catch {
      token = null
    }
    if (token === null || token.length === 0) {
      return frozen({ kind: 'Unknown', requestId: id, reason: 'transport-unreachable' })
    }

    const doFetch = this.#options.fetchImpl ?? fetch
    const url = `${this.#options.origin}${this.#options.wirePathPrefix}${method}`
    let response: Response
    try {
      response = await doFetch(url, {
        method: 'POST',
        headers: {
          // The ONLY place the token is ever written. It goes into a request
          // header inside this function and into nothing else.
          Authorization: `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
        // wire/1 speaks JSON-RPC 2.0 and validates it strictly
        // (`ordessa_server/wire/envelope.py:decode_request`): the envelope must
        // carry exactly `jsonrpc`/`id`/`method`/`params`, and the body `method`
        // must equal the URL path segment. The per-call `id` is the same
        // correlation id the result reports back as `requestId`.
        body: JSON.stringify({ jsonrpc: '2.0', id, method, params }),
        signal: AbortSignal.timeout(this.#options.timeoutMs ?? 15000),
      })
    } catch {
      // The request may or may not have been applied. We do not know, so we
      // say so — and we do NOT resend (C-03 §3).
      return frozen({ kind: 'Unknown', requestId: id, reason: 'result-unknown' })
    }

    let body: Record<string, unknown>
    try {
      body = (await response.json()) as Record<string, unknown>
    } catch {
      return frozen({ kind: 'Unknown', requestId: id, reason: 'result-unknown' })
    }
    return interpret(id, response.status, body)
  }
}

/**
 * Turn one HTTP answer into a typed result.
 *
 * wire/1 answers are JSON-RPC 2.0 envelopes (`encode_result`/`encode_error`):
 * a success carries exactly one `result` member, a refusal exactly one `error`
 * member. Business refusals arrive on 200 as well as on 4xx, so the shape of
 * the body decides — not the status code. Reading the status alone would turn
 * every business refusal into a transport error.
 */
export function interpret(
  id: string,
  status: number,
  body: Record<string, unknown>,
): WireResult {
  // The server echoes the JSON-RPC `id`; envelope rejections (auth, decode)
  // answer `id: null`, and then the caller's own id is the correlation.
  const requestId = typeof body['id'] === 'string' ? body['id'] : id
  if (status >= 500) {
    // The Server failed. Whether the call took effect is unknown to us.
    return frozen({ kind: 'Unknown', requestId, reason: 'result-unknown' })
  }
  const error = body['error']
  if (error !== undefined && error !== null && typeof error === 'object') {
    const refusal = error as Record<string, unknown>
    const reason = typeof refusal['message'] === 'string' ? refusal['message'] : 'server-refused'
    // The wire/1 error body carries `retryable` inside `details`
    // (`WireError.to_body`); a flat member is accepted too, so either shape
    // lands on the honest retryable fact.
    const details = refusal['details']
    const retryable = refusal['retryable'] === true
      || (details !== null && typeof details === 'object' && (details as Record<string, unknown>)['retryable'] === true)
    return frozen({
      kind: 'Refused',
      requestId,
      reason,
      retryable,
    })
  }
  if (status >= 400) {
    return frozen({ kind: 'Refused', requestId, reason: 'server-refused', retryable: false })
  }
  if ('result' in body) {
    const result = body['result']
    // A wire/1 handler answers an object (`handlers.py` dispatch rows); a
    // null/primitive "result" is an envelope this port refuses to dress up.
    if (result !== null && typeof result === 'object' && !Array.isArray(result)) {
      return frozen({ kind: 'Accepted', requestId, result: frozen({ ...result as Record<string, unknown> }) })
    }
  }
  return frozen({ kind: 'Unknown', requestId, reason: 'result-unknown' })
}

/**
 * C-03 §6 — what a plugin gets when the host provides no port.
 *
 * It is an object with the full interface, not `undefined`. A consumer that
 * checks `if (port)` would otherwise render an empty state that reads as
 * "no data"; this one answers `Unknown/port-absent` and says why.
 */
export class AbsentWirePort implements WirePort {
  readonly #scope: string | null

  constructor(scope: string | null = null) {
    this.#scope = scope
  }

  get ready(): boolean {
    return false
  }

  get scope(): string | null {
    return this.#scope
  }

  async call(_method = "", _params: Readonly<Record<string, unknown>> = {}): Promise<WireResult> {
    return frozen({ kind: 'Unknown', requestId: requestId(), reason: 'port-absent' })
  }
}

/**
 * A port that is not ready YET but will be: every call is
 * `Unknown/host-not-ready`, nothing is queued.
 *
 * Queuing would be a lie with a latency: the caller would eventually get an
 * `Accepted` for a call it had no evidence was accepted, and the global
 * rule "Unknown must not impersonate Accepted" is exactly that.
 */
export class PendingWirePort implements WirePort {
  readonly #scope: string | null

  constructor(scope: string | null = null) {
    this.#scope = scope
  }

  get ready(): boolean {
    return false
  }

  get scope(): string | null {
    return this.#scope
  }

  async call(_method = "", _params: Readonly<Record<string, unknown>> = {}): Promise<WireResult> {
    return frozen({ kind: 'Unknown', requestId: requestId(), reason: 'host-not-ready' })
  }
}

