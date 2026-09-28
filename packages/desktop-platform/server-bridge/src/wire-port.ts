/**
 * C-03 — the wire port, the ONE channel a plugin has to the Server.
 *
 * The whole point of this module is that a plugin never holds a token. The
 * bytes live in the main process; a plugin gets a `WirePort` whose `call`
 * returns a typed three-state result and whose surface contains no
 * credential, no locator and no way to ask for one.
 *
 * Three rules are load-bearing and are implemented as such:
 *
 * 1. **Three states, never collapsed.** `Unknown` is not a softer `Refused`
 *    and never a disguised success. A transport that dies mid-call is
 *    `Unknown` + `result-unknown`, and it is NOT retried — a blind resend
 *    of a mutating call is how one action happens twice (C-03 §3).
 * 2. **The host never fails a call with an exception.** Every path returns a
 *    result. A plugin's `await port.call(...)` cannot throw, so a plugin
 *    cannot accidentally treat a transport failure as control flow.
 * 3. **The absent port is a real object.** `AbsentWirePort` answers
 *    `Unknown/port-absent` forever instead of the host leaving `undefined`
 *    in the extension API — an absent provider must not crash a consumer,
 *    and must not look like "no data" either.
 */
import { layout, tokenFileOf } from './data-root.js'

/** C-03 §7. Open-ended by design: a provider may add one, consumers must not assume exhaustiveness. */
export type WireReason =
  | 'host-not-ready'
  | 'port-absent'
  | 'transport-unreachable'
  | 'server-refused'
  | 'result-unknown'
  | 'invalid-method'

export type WireResult =
  | { readonly kind: 'Accepted'; readonly requestId: string; readonly result: Readonly<Record<string, unknown>> }
  | { readonly kind: 'Refused'; readonly requestId: string; readonly reason: string; readonly retryable: boolean }
  | { readonly kind: 'Unknown'; readonly requestId: string; readonly reason: string }

/** Everything C-03 §2 promises, and nothing more. */
export interface WirePort {
  call(method: string, params: Readonly<Record<string, unknown>>): Promise<WireResult>
  readonly ready: boolean
  /** `origin|serverId`. No token, no locator. */
  readonly scope: string | null
}

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
    const url = `${this.#options.origin}${layout().launch.wirePathPrefix}${method}`
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
        body: JSON.stringify({ requestId: id, ...params }),
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
 * The Server answers 200 for BOTH a result and a business refusal (C-03 §1),
 * so the shape of the body decides — not the status code. Reading the status
 * alone would turn every business refusal into a transport error.
 */
export function interpret(
  id: string,
  status: number,
  body: Record<string, unknown>,
): WireResult {
  const requestId = typeof body['requestId'] === 'string' ? body['requestId'] : id
  if (status >= 500) {
    // The Server failed. Whether the call took effect is unknown to us.
    return frozen({ kind: 'Unknown', requestId, reason: 'result-unknown' })
  }
  const error = body['error']
  if (error !== undefined && error !== null && typeof error === 'object') {
    const refusal = error as Record<string, unknown>
    const reason = typeof refusal['message'] === 'string' ? refusal['message'] : 'server-refused'
    return frozen({
      kind: 'Refused',
      requestId,
      reason,
      retryable: refusal['retryable'] === true,
    })
  }
  if (status >= 400) {
    return frozen({ kind: 'Refused', requestId, reason: 'server-refused', retryable: false })
  }
  const { requestId: _ignored, error: _alsoIgnored, ...result } = body
  return frozen({ kind: 'Accepted', requestId, result: frozen(result) })
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

  async call(): Promise<WireResult> {
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

  async call(): Promise<WireResult> {
    return frozen({ kind: 'Unknown', requestId: requestId(), reason: 'host-not-ready' })
  }
}

/**
 * Read the bearer from the data root's token file — main process only.
 *
 * The locator is built from the shared layout, the file is read with the
 * caller's own privileges, and the returned string is used inside the
 * `Authorization` header and nowhere else. A read failure answers `null`,
 * which the port turns into `transport-unreachable`; the error text is
 * dropped on the floor so no path can ride along in a result.
 */
export function tokenReaderFor(
  dataRoot: string,
  readFile: (file: string) => Promise<string>,
): () => Promise<string | null> {
  const locator = tokenFileOf(dataRoot)
  return async () => {
    try {
      const bytes = await readFile(locator)
      // A single trailing end-of-line is stripped; anything else is refused
      // rather than cleaned, because a token with a control byte in it is
      // not the token the Server issued.
      const token = bytes.replace(/\r?\n$/, '')
      if (token.length === 0 || /[\u0000-\u001f\u007f]/.test(token)) return null
      return token
    } catch {
      return null
    }
  }
}
