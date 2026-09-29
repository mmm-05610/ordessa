// McpWireClient: the typed frontend seam over the `mcp.*` wire methods
// (docs/design/mcp/contracts.md §1 operation table; the ids are the ones the
// Server plugin registers: `mcp.list / mcp.get / mcp.archive` plus the
// same-name rows). The fetch implementation speaks the server's wire/1
// envelope (POST /wire/v1/{method}, JSON-RPC 2.0 shaped — apps/server
// transport/http/app.py + wire/envelope.py); tests inject an in-memory fake
// instead. The client is optionally injected: the session-service owner
// (T09/C0 assembly) decides whether one exists at all — absence is rendered
// as unavailable, never substituted with local data.
//
// WIRE ALIGNMENT (Q4 wire-alignment fix, specs/011-q4-mcp/reports/
// wire-alignment.md): the method ids, per-request param sets, injected
// identity fields, response unwrap paths and DTO field names below are kept
// exactly equal to the backend's registered descriptor face and live
// round-trip views; tests/contract/test_wire_contract_guard.py pins every
// one of them as a strict-equality guard (a rename, an added/removed field
// or a moved unwrap path on either side turns that guard red).

import type {
  McpAssignmentView, McpCanonicalDefinition, McpConnectionFacts, McpDefinitionSummary,
  McpListToolsResult, McpPreviewResult, McpProbeFacts, McpRevisionView, McpSaveRevisionResult,
  McpUnassignView,
} from './dto'

/** A typed wire refusal. `code` is the business code string (e.g. a probe
 * `PROBE_TIMEOUT` or a CAS conflict); the UI displays it, never reinterprets
 * it into success (contracts.md §1 "typed refusal"). */
export class McpWireError extends Error {
  readonly code: string
  constructor(code: string, message: string) {
    super(message)
    this.name = 'McpWireError'
    this.code = code
  }
}

/** The caller identity the session-service owner binds into the client
 * factory (T09 wires the principal as a REQUIRED wire param on every `mcp.*`
 * request; there is no host-level request principal injection yet — that is
 * the G7 integration point). The owner of the conversation is the factory
 * caller: a missing or blank identity is a construction-time typed refusal,
 * never a default. */
export interface McpWireIdentity {
  readonly serverScope: string
  readonly principal: string
}

export interface McpWireClient {
  listDefinitions(signal?: AbortSignal): Promise<readonly McpDefinitionSummary[]>
  getDefinition(definitionId: string, signal?: AbortSignal): Promise<McpRevisionView>
  /** Saves a CANDIDATE revision. Saving approves nothing and probes nothing
   * (contracts.md §1); approval is the separate `approveRevision` call. The
   * definitionId is a REQUIRED wire param: a new definition names itself by
   * its id from the first save. */
  saveRevision(input: {
    readonly definitionId: string
    readonly definition: McpCanonicalDefinition
    readonly expectedVersion: number
    readonly operationKey: string
    signal?: AbortSignal
  }): Promise<McpSaveRevisionResult>
  /** The standalone「批准并用于选择」action: makes one saved revision the
   * approved revision after the save returned. Independent of save. The
   * descriptor declares NO CAS fields here — approval is identified by the
   * (definitionId, revision) pair itself. */
  approveRevision(input: {
    readonly definitionId: string
    readonly revision: number
    signal?: AbortSignal
  }): Promise<{ readonly definitionId: string; readonly revision: number; readonly approval: { readonly actor: string; readonly approvedAt: string } }>
  /** Archives one definition (the registered id is `mcp.archive`). The
   * descriptor declares no CAS fields for archive; the answer is the
   * updated definition row. */
  archiveDefinition(input: { readonly definitionId: string; signal?: AbortSignal }): Promise<McpDefinitionSummary>
  /** Bounded, credential-less probe. The refusal path throws McpWireError with
   * the typed PROBE_* code; the success path carries the scope declaration. */
  probe(input: { readonly definitionId: string; readonly revision: number; signal?: AbortSignal }): Promise<McpProbeFacts>
  /** One scope decision row. The backend CAS param is `expectedRowVersion`
   * and the enable/disable switch is the `decision` vocabulary — the row
   * model carries no boolean `enabled`/`revision` field (the approved
   * revision travels as `approvedRevision`, the tool subset as a frozen
   * selection object). */
  assign(input: {
    readonly scopeKind: 'user-default' | 'project' | 'profile' | 'session'
    readonly scopeId: string
    readonly definitionId: string
    readonly decision: 'enable' | 'disable' | 'inherit'
    readonly expectedRowVersion: number
    readonly operationKey: string
    readonly harness?: string
    readonly approvedRevision?: number
    readonly toolSelection?: { readonly mode: 'allowNames' | 'allObserved'; readonly names: readonly string[]; readonly catalogDigest: string } | null
    signal?: AbortSignal
  }): Promise<McpAssignmentView>
  unassign(input: {
    readonly scopeKind: 'user-default' | 'project' | 'profile' | 'session'
    readonly scopeId: string
    readonly definitionId: string
    readonly expectedRowVersion: number
    readonly operationKey: string
    readonly harness?: string
    signal?: AbortSignal
  }): Promise<McpUnassignView>
  /** Read-only effective snapshot. The §1 row addresses the target with the
   * individual optional params (there is no free-form `target` object on the
   * wire); `scopeRevisions` never existed — the snapshot's own revision
   * digest is the answer-side binding. */
  resolvePreview(input: {
    readonly harness?: string
    readonly projectId?: string
    readonly profileRevision?: string
    readonly sessionRef?: string
    readonly targetSession?: string
    readonly runtimeGeneration?: number
    signal?: AbortSignal
  }): Promise<McpPreviewResult>
  /** Live lease facts for ONE managed connection. The lease is addressed by
   * (sessionRef, runtimeGeneration, leaseId) — the session owner maps its
   * definitions to lease ids; `serverScope` is NOT a param of this row. */
  inspectConnection(input: {
    readonly sessionRef: string
    readonly runtimeGeneration: number
    readonly leaseId: string
    signal?: AbortSignal
  }): Promise<McpConnectionFacts>
  /** Live catalog for one definition revision of this caller's session
   * (refuses MCP_CATALOG_MISSING typed when no lease is observing it — a
   * stored definition is never dressed up as a connection). */
  listTools(input: {
    readonly sessionRef: string
    readonly runtimeGeneration: number
    readonly definitionId: string
    readonly revision: number
    signal?: AbortSignal
  }): Promise<McpListToolsResult>
  // Absence kept by adjudication (contract-guard.md §四.2): the descriptor
  // face also registers `mcp.planForSubmission`, which this client does NOT
  // bind — the submission leg is consumed by the Chat/Profile owner through
  // the provided service port, not through this Settings/Status surface.
}

/** Method ids registered by the MCP Server plugin (T09 `plugin.py`); one
 * `mcp.*` per client operation. Kept in one table so the C0 binding check is
 * a single diff. `listDefinitions/getDefinition/archiveDefinition` bind to
 * the registered short ids `mcp.list/mcp.get/mcp.archive` — the wire id is
 * the descriptor name, only the TS member keeps its operation word. */
export const MCP_WIRE_METHODS = {
  listDefinitions: 'mcp.list',
  getDefinition: 'mcp.get',
  saveRevision: 'mcp.saveRevision',
  approveRevision: 'mcp.approveRevision',
  archiveDefinition: 'mcp.archive',
  probe: 'mcp.probe',
  assign: 'mcp.assign',
  unassign: 'mcp.unassign',
  resolvePreview: 'mcp.resolvePreview',
  inspectConnection: 'mcp.inspectConnection',
  listTools: 'mcp.listTools',
} as const

/** Per-operation params the client factory injects from its bound identity
 * (mirrored 1:1 by the contract guard's WCG-02: the sent body equals each
 * request row ∪ this injection, exactly the descriptor's required set plus
 * optional fields the caller passed). `mcp.inspectConnection` has no
 * `serverScope` in its required set — leasing is addressed per session. */
export const MCP_WIRE_IDENTITY_INJECTION = {
  listDefinitions: ['serverScope', 'principal'],
  getDefinition: ['serverScope', 'principal'],
  saveRevision: ['serverScope', 'principal'],
  approveRevision: ['serverScope', 'principal'],
  archiveDefinition: ['serverScope', 'principal'],
  probe: ['serverScope', 'principal'],
  assign: ['serverScope', 'principal'],
  unassign: ['serverScope', 'principal'],
  resolvePreview: ['serverScope', 'principal'],
  inspectConnection: ['principal'],
  listTools: ['serverScope', 'principal'],
} as const satisfies Record<keyof typeof MCP_WIRE_METHODS, readonly (keyof McpWireIdentity)[]>

/** Which member of the top-level result envelope carries each operation's
 * answer ('' = the result IS the answer). The backend wraps its views at the
 * top level (contracts §1 read rows); this client unwraps exactly here —
 * pinned by the guard's WCG-03 against live round-trip keys. */
export const MCP_WIRE_RESULT_PATH = {
  listDefinitions: 'definitions',
  getDefinition: 'latestRevision',
  saveRevision: '',
  approveRevision: '',
  archiveDefinition: 'definition',
  probe: 'probe',
  assign: 'assignment',
  unassign: 'assignment',
  resolvePreview: '',
  inspectConnection: 'connection',
  listTools: '',
} as const satisfies Record<keyof typeof MCP_WIRE_METHODS, string>

export interface FetchMcpWireOptions {
  /** Server origin (loopback http per the domain's url rule), no trailing path
   * requirement; `/wire/v1/<method>` is appended. */
  readonly baseUrl: string
  /** The session-service owner's identity, bound once for every request.
   * Required: construction with a missing/blank identity is the typed
   * `MCP_WIRE_IDENTITY_REQUIRED` refusal, never a default. */
  readonly identity: McpWireIdentity
  /** Injectable fetch (tests pass a fake; runtime defaults to globalThis). */
  readonly fetchImpl?: (request: string, init: RequestInit) => Promise<Response>
  /** Per-request auth headers supplied by the owner (bearer token handling
   * stays with the session-service owner — the client stores no secrets). */
  readonly headers?: () => Record<string, string> | Promise<Record<string, string>>
}

function requireMcpWireIdentity(identity: McpWireIdentity | undefined): McpWireIdentity {
  if (!identity
      || typeof identity.serverScope !== 'string' || identity.serverScope === ''
      || typeof identity.principal !== 'string' || identity.principal === '') {
    throw new McpWireError('MCP_WIRE_IDENTITY_REQUIRED',
      'createFetchMcpWireClient needs the session-service owner to bind {serverScope, principal};'
      + ' every mcp.* request names its caller and no identity is fabricated as a default')
  }
  return identity
}

/** The optional fetch-based implementation of {@link McpWireClient}: wire/1
 * envelope, exactly one of `result`/`error` per response
 * (wire/envelope.py `decode_request`/`encode_result`/`encode_error`). */
export function createFetchMcpWireClient(options: FetchMcpWireOptions): McpWireClient {
  const identity = requireMcpWireIdentity(options.identity)
  const fetchImpl = options.fetchImpl ?? ((request, init) => globalThis.fetch(request, init))
  const base = options.baseUrl.replace(/\/+$/, '')
  let nextId = 1
  const clientKeyOf = (method: string): keyof typeof MCP_WIRE_METHODS => {
    const entry = Object.entries(MCP_WIRE_METHODS).find(([, id]) => id === method)
    if (!entry) throw new McpWireError('WIRE_METHOD_UNBOUND', `${method} has no bound row in MCP_WIRE_METHODS`)
    return entry[0] as keyof typeof MCP_WIRE_METHODS
  }
  const rpc = async (method: string, params: Record<string, unknown>, signal?: AbortSignal): Promise<unknown> => {
    const response = await fetchImpl(`${base}/wire/v1/${method}`, {
      method: 'POST',
      headers: { 'content-type': 'application/json', ...(await (options.headers?.() ?? {})) },
      body: JSON.stringify({ jsonrpc: '2.0', id: nextId++, method, params }),
      signal,
    })
    let body: unknown
    try { body = await response.json() }
    catch { throw new McpWireError('WIRE_BAD_RESPONSE', `the ${method} answer is not JSON (HTTP ${response.status})`) }
    if (!body || typeof body !== 'object') throw new McpWireError('WIRE_BAD_RESPONSE', `the ${method} answer is not an envelope`)
    const envelope = body as { result?: unknown; error?: unknown }
    if ('error' in envelope && envelope.error !== undefined) {
      const error = envelope.error as { code?: unknown; message?: unknown }
      const code = typeof error.code === 'string' ? error.code : 'WIRE_ERROR'
      const message = typeof error.message === 'string' ? error.message : `${method} refused`
      throw new McpWireError(code, message)
    }
    if (!('result' in envelope)) throw new McpWireError('WIRE_BAD_RESPONSE', `${method} returned neither result nor error`)
    return envelope.result
  }
  const call = async <T>(method: string, params: Record<string, unknown>, signal?: AbortSignal): Promise<T> => {
    const key = clientKeyOf(method)
    const injected: Record<string, string> = {}
    for (const name of MCP_WIRE_IDENTITY_INJECTION[key]) injected[name] = identity[name]
    const result = await rpc(method, { ...injected, ...params }, signal)
    const path = MCP_WIRE_RESULT_PATH[key]
    if (path === '') return result as T
    if (!result || typeof result !== 'object' || !(path in result)) {
      throw new McpWireError('WIRE_BAD_RESPONSE', `the ${method} answer carries no '${path}' wrapper member`)
    }
    const value = (result as Record<string, unknown>)[path]
    // The backend views put a null under the wrapper only for states the
    // stores themselves cannot produce (e.g. a definition row without any
    // revision); treating that as an empty answer object would fake a read.
    if (value === undefined || value === null) {
      throw new McpWireError('WIRE_ANSWER_INCOMPLETE', `the ${method} answer's '${path}' member carries no view`)
    }
    return value as T
  }
  return {
    listDefinitions: signal => call(MCP_WIRE_METHODS.listDefinitions, {}, signal),
    getDefinition: (definitionId, signal) => call(MCP_WIRE_METHODS.getDefinition, { definitionId }, signal),
    saveRevision: ({ signal, ...params }) => call(MCP_WIRE_METHODS.saveRevision, { ...params }, signal),
    approveRevision: ({ signal, ...params }) => call(MCP_WIRE_METHODS.approveRevision, { ...params }, signal),
    archiveDefinition: ({ signal, ...params }) => call(MCP_WIRE_METHODS.archiveDefinition, { ...params }, signal),
    probe: ({ signal, ...params }) => call(MCP_WIRE_METHODS.probe, { ...params }, signal),
    assign: ({ signal, ...params }) => call(MCP_WIRE_METHODS.assign, { ...params }, signal),
    unassign: ({ signal, ...params }) => call(MCP_WIRE_METHODS.unassign, { ...params }, signal),
    resolvePreview: ({ signal, ...params }) => call(MCP_WIRE_METHODS.resolvePreview, { ...params }, signal),
    inspectConnection: ({ signal, ...params }) => call(MCP_WIRE_METHODS.inspectConnection, { ...params }, signal),
    listTools: ({ signal, ...params }) => call(MCP_WIRE_METHODS.listTools, { ...params }, signal),
  }
}
