import {
  AgentSideConnection, ClientSideConnection, ndJsonStream, RequestError, PROTOCOL_VERSION,
} from '@agentclientprotocol/sdk'
import type * as acp from '@agentclientprotocol/sdk'

/**
 * A controllable Harness-side ACP peer for target tests. Everything protocol-shaped here comes
 * from the SDK pinned in this directory's package-lock.json (`@agentclientprotocol/sdk`), never
 * from memory: method names come from `AGENT_METHODS`, payload fields from the generated schema.
 */

export type Recorded = { method: string; params: any }

export interface PeerPromptApi {
  request: acp.PromptRequest
  /** Resolves the next time `session/cancel` arrives for this prompt's session. */
  cancelled(): Promise<void>
  update(update: acp.SessionUpdate): Promise<void>
  permission(toolCall: acp.ToolCallUpdate, options: acp.PermissionOption[]): Promise<acp.RequestPermissionResponse>
  elicitation(params: acp.CreateElicitationRequest): Promise<any>
}

export type PeerPromptScript = (api: PeerPromptApi) => Promise<acp.StopReason | acp.PromptResponse | void>

export interface HarnessPeerOptions {
  /** Exactly what `initialize` answers; absence of a capability must read as absence. */
  capabilities?: acp.AgentCapabilities
  /** Stop reason for turns with no queued script. */
  autoStop?: acp.StopReason
  /** When set, `initialize` records the request and then waits on this promise before answering —
   * it pins the mid-handshake window where dispose and a landing initialize own the same handle. */
  initializeGate?: Promise<void>
}

/** Two in-process byte pipes wrapped as the SDK's ndjson `Stream` on each side. EOF/abort on a
 * pipe is how the SDK connection ends, so `HarnessPeer.close()` and `drop()` simulate the link. */
export interface AcpStreamPair {
  clientStream: acp.Stream
  peerStream: acp.Stream
  /** Clean end-of-stream on both directions (an orderly shutdown). */
  shutdown: () => void
  /** Hard failure on both directions (a dropped link). */
  drop: (reason?: Error) => void
}

/** One direction of the byte pipe. `writable` is what this side writes into and `readable` is
 * what the far side reads; `eof`/`fail` end the readable (orderly / dropped). */
interface Channel {
  readable: ReadableStream<Uint8Array>
  writable: WritableStream<Uint8Array>
  eof: () => void
  fail: (reason: Error) => void
}

function makeChannel(): Channel {
  let controller!: ReadableStreamDefaultController<Uint8Array>
  let ended = false
  const readable = new ReadableStream<Uint8Array>({ start(c) { controller = c } })
  const eof = () => { if (!ended) { ended = true; try { controller.close() } catch { /* already settled */ } } }
  const fail = (reason: Error) => { if (!ended) { ended = true; try { controller.error(reason) } catch { /* already settled */ } } }
  // A connector releases its channel by closing or aborting the SDK Stream it was handed, so the
  // writable must propagate that as end-of-stream to the far readable. A write-only sink would
  // leave a correct `dispose()` waiting forever on a link end that never arrives.
  const writable = new WritableStream<Uint8Array>({
    write(chunk) { if (!ended) controller.enqueue(chunk) },
    close: eof,
    abort: (reason: unknown) => { fail(reason instanceof Error ? reason : new Error('acp channel aborted')) },
  })
  return { readable, writable, eof, fail }
}

/** Wrap one `Channel` as the SDK's ndjson `Stream`, forwarding the exposed writable's
 * close/abort down to the byte pipe so either side tearing the stream ends it for both. */
function bridgeStream(raw: Channel, input: ReadableStream<Uint8Array>): acp.Stream {
  const encoded = ndJsonStream(raw.writable, input)
  const writer = encoded.writable.getWriter()
  const exposed = new WritableStream<acp.AnyMessage>({
    write: message => writer.write(message),
    async close() { try { await writer.close() } catch { /* far end already gone */ } raw.eof() },
    abort(reason) { try { writer.abort(reason) } catch { /* far end already gone */ } raw.fail(reason instanceof Error ? reason : new Error('acp channel aborted')) },
  })
  return { readable: encoded.readable, writable: exposed }
}

/** A one-shot open switch: the peer turn holds until `resolve`, letting a test observe the state
 * strictly between "request sent" and "confirmation received" without a race. */
export interface Deferred {
  promise: Promise<void>
  resolve: () => void
}
export function deferred(): Deferred {
  let resolve!: () => void
  const promise = new Promise<void>(r => { resolve = r })
  return { promise, resolve }
}

export function acpStreamPair(): AcpStreamPair {
  const peerToClient = makeChannel()
  const clientToPeer = makeChannel()
  return {
    clientStream: bridgeStream(clientToPeer, peerToClient.readable),
    peerStream: bridgeStream(peerToClient, clientToPeer.readable),
    shutdown: () => { peerToClient.eof(); clientToPeer.eof() },
    drop: (reason = new Error('acp channel dropped')) => { peerToClient.fail(reason); clientToPeer.fail(reason) },
  }
}

export class HarnessPeer {
  /** The end of the channel a client (product connector or fixture) connects to. */
  readonly stream: acp.Stream
  readonly requests: Recorded[] = []
  readonly notifications: Recorded[] = []
  readonly promptResponses: { sessionId: string; stopReason: acp.StopReason }[] = []
  private readonly conn: AgentSideConnection
  private readonly pair: AcpStreamPair
  private readonly scripts: PeerPromptScript[] = []
  private readonly failures = new Map<string, RequestError>()
  private readonly cancelWaiters = new Map<string, Array<() => void>>()
  private readonly cancelledSessions = new Set<string>()
  private readonly loadScripts = new Map<string, acp.SessionUpdate[]>()
  private sessions = 0
  /** Sessions offered through `session/list`; only consulted when the capability is on. */
  listed: acp.SessionInfo[] = []
  /** When set, every `session/list` waits on this promise before answering — pins the stale-response
   * window: a list whose answer lands only after a newer name has already been applied. */
  listHold?: Promise<void>
  closed: Promise<void>

  constructor(readonly options: HarnessPeerOptions = {}) {
    const pair = acpStreamPair()
    this.pair = pair
    this.stream = pair.clientStream
    const record = (kind: Recorded[], method: string, params: unknown) => kind.push({ method, params })
    const agent: acp.Agent = {
      initialize: async params => {
        record(this.requests, 'initialize', params)
        if (this.options.initializeGate) await this.options.initializeGate
        this.checkFailure('initialize')
        return { protocolVersion: PROTOCOL_VERSION, agentCapabilities: this.options.capabilities ?? {} }
      },
      newSession: async params => {
        record(this.requests, 'session/new', params)
        this.checkFailure('session/new')
        const sessionId = `acp-session-${++this.sessions}`
        return { sessionId }
      },
      // The pinned SDK's Agent interface requires the method; no target test calls it, and
      // recording it keeps the surface honest if one ever does.
      authenticate: async params => {
        record(this.requests, 'authenticate', params)
        return {}
      },
      prompt: async params => {
        record(this.requests, 'session/prompt', params)
        this.checkFailure('session/prompt')
        const sessionId = params.sessionId
        // A cancel belongs to the turn it arrived on; a new prompt starts clean.
        this.cancelledSessions.delete(sessionId)
        const script = this.scripts.shift()
        const api: PeerPromptApi = {
          request: params,
          cancelled: () => this.cancellation(sessionId),
          update: update => this.conn.sessionUpdate({ sessionId, update }),
          permission: (toolCall, options) => this.conn.requestPermission({ sessionId, toolCall, options }),
          elicitation: elicit => this.conn.request('elicitation/create', elicit as any),
        }
        const outcome = await script?.(api)
        const stopReason = typeof outcome === 'object' && outcome && 'stopReason' in outcome
          ? outcome.stopReason : (outcome ?? this.options.autoStop ?? 'end_turn') as acp.StopReason
        this.promptResponses.push({ sessionId, stopReason })
        return { stopReason }
      },
      cancel: async params => {
        record(this.notifications, 'session/cancel', params)
        // Cancellation is a state, not just an edge: a cancel arriving before a script parks on
        // `cancelled()` must not be lost (a real agent never misses it).
        if (params?.sessionId) this.cancelledSessions.add(params.sessionId)
        for (const resolve of this.cancelWaiters.get(params?.sessionId) ?? []) resolve()
        this.cancelWaiters.delete(params?.sessionId)
      },
      // Registered only when the capability is advertised — an absent capability must answer as
      // method-not-found on the wire, which is what the target tests assert against.
      ...(this.options.capabilities?.loadSession ? {
        loadSession: async (params: acp.LoadSessionRequest) => {
          record(this.requests, 'session/load', params)
          this.checkFailure('session/load')
          for (const update of this.loadScripts.get(params.sessionId) ?? []) {
            await this.conn.sessionUpdate({ sessionId: params.sessionId, update })
          }
          return {}
        },
      } : {}),
      ...(this.options.capabilities?.sessionCapabilities?.list !== undefined && this.options.capabilities?.sessionCapabilities?.list !== null ? {
        listSessions: async (params: acp.ListSessionsRequest) => {
          record(this.requests, 'session/list', params)
          // The list is computed when the request ARRIVES, then the hold delays only the answer.
          // So a held response carries the data as of its own issue time — a genuinely stale
          // answer, even if `listed` has since moved. Without this the fixture would hand the
          // stale response the fresh title and flatter exactly the bug under test.
          const answer = this.listed
          if (this.listHold) await this.listHold
          return { sessions: answer }
        },
      } : {}),
    }
    this.conn = new AgentSideConnection(() => agent, pair.peerStream)
    this.closed = this.conn.closed
  }

  /** Out-of-band `session/update` — late events, title updates, anything outside a turn. */
  update(sessionId: string, update: acp.SessionUpdate): Promise<void> {
    return this.conn.sessionUpdate({ sessionId, update })
  }

  /** Out-of-band reverse request; resolves with whatever the client answers. */
  permission(sessionId: string, toolCall: acp.ToolCallUpdate, options: acp.PermissionOption[]): Promise<acp.RequestPermissionResponse> {
    return this.conn.requestPermission({ sessionId, toolCall, options })
  }

  elicit(sessionId: string, params: Record<string, unknown>): Promise<any> {
    return this.conn.request('elicitation/create', { sessionId, ...params } as acp.CreateElicitationRequest)
  }

  queueTurn(script: PeerPromptScript) { this.scripts.push(script) }
  onLoadReplay(sessionId: string, updates: acp.SessionUpdate[]) { this.loadScripts.set(sessionId, updates) }
  armFailure(method: string, error: RequestError) { this.failures.set(method, error) }
  private checkFailure(method: string) {
    const failure = this.failures.get(method)
    if (failure) { this.failures.delete(method); throw failure }
  }
  cancellation(sessionId: string): Promise<void> {
    if (this.cancelledSessions.has(sessionId)) return Promise.resolve()
    return new Promise(resolve => {
      const waiters = this.cancelWaiters.get(sessionId) ?? []
      waiters.push(resolve)
      this.cancelWaiters.set(sessionId, waiters)
    })
  }
  recorded(method: string) {
    return [...this.requests, ...this.notifications].filter(item => item.method === method)
  }
  async waitFor(what: string, predicate: () => boolean, timeoutMs = 2_000) {
    const deadline = Date.now() + timeoutMs
    while (!predicate()) {
      if (Date.now() > deadline) throw new Error(`HarnessPeer timed out waiting for ${what}`)
      await new Promise(resolve => setTimeout(resolve, 5))
    }
  }
  /** Orderly end of the channel, both directions. */
  close() { this.pair.shutdown() }
  /** Simulated link failure: in-flight requests reject, both sides close. */
  drop(reason?: Error) { this.pair.drop(reason) }
}

/** The fixture's own client end, used by the self-verification test only (never by target
 * tests): it drives the real SDK client over `HarnessPeer.stream`. */
export class FixtureClient {
  readonly conn: ClientSideConnection
  readonly updates: acp.SessionNotification[] = []
  readonly permissionRequests: acp.RequestPermissionRequest[] = []
  permissionAnswer: acp.RequestPermissionResponse = { outcome: { outcome: 'cancelled' } }
  constructor(clientStream: acp.Stream) {
    this.conn = new ClientSideConnection(() => ({
      sessionUpdate: async params => { this.updates.push(params) },
      requestPermission: async params => {
        this.permissionRequests.push(params)
        return this.permissionAnswer
      },
    }), clientStream)
  }
}
