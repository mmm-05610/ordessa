// MCP wire DTO shapes (frontend glue, Q4 T08).
//
// These mirror the backend domain reads/writes of docs/design/mcp/contracts.md §1
// and the canonical v2 storage model in `plugins/assets/mcp/backend/definition.py`
// (typed env/header values `{"literal": …}` / `{"secretRef": …}`; legacy
// `credentialRef` reads are restored to `secretRef` server-side). They are
// transport types only: no business rule is duplicated here, and the UI never
// promotes one tier's fact into another's (FR-02 six-tier grading lives in
// ./status).

/** Exactly the two transports the domain validates (`_TRANSPORTS`). */
export type McpTransportKind = 'stdio' | 'remote'

/** One canonical env/header value: a readable constant or a credential REFERENCE.
 * A reference is an id only — a plaintext secret never crosses this surface. */
export type McpWireValue = { readonly literal: string } | { readonly secretRef: string }

/** The canonical definition document (`canonical_definition_v2` shape; the two
 * scalar keys stay exactly as the backend stores them). */
export interface McpCanonicalDefinition {
  readonly name: string
  readonly transport:
    | { readonly stdio: { readonly command: string; readonly args: readonly string[]; readonly env?: Record<string, McpWireValue> } }
    | { readonly remote: { readonly url: string; readonly headers?: Record<string, McpWireValue> } }
}

export interface McpApproval { readonly actor: string; readonly approvedAt: string }

/** One stored revision of a definition (`McpRevision` read model). */
export interface McpRevisionView {
  readonly definitionId: string
  readonly revision: number
  readonly canonicalDigest: string
  readonly canonical: McpCanonicalDefinition
  readonly canonicalShape: 'legacy' | 'v2'
  readonly source: string | null
  readonly createdAt: string
  readonly approval: McpApproval | null
}

/** Last probe outcome attached to a definition row. `ok` is a PROBE fact only —
 * rendering it as "connected" is forbidden (ux.md: 探测成功 ≠ 会话已连接). */
export type McpProbeOutcome =
  | { readonly result: 'ok'; readonly revision: number; readonly at: string }
 | { readonly result: 'refused'; readonly revision: number; readonly at: string; readonly code: string; readonly message: string }

/** `mcp.listDefinitions` row. */
export interface McpDefinitionSummary {
  readonly definitionId: string
  readonly name: string
  readonly transport: McpTransportKind
  readonly latestRevision: number
  /** The revision currently approved for selection; null means none. */
  readonly approvedRevision: number | null
  readonly source: string | null
  readonly archived: boolean
  readonly lastProbe: McpProbeOutcome | null
}

/** The graded facts a successful probe returns (`_handshake_facts` in
 * backend/probe.py). Note what is absent: any catalog, any credential verdict,
 * any live connection. */
export interface McpProbeFacts {
  readonly status: 'ok'
  readonly transport: McpTransportKind
  readonly evidence: string
  readonly serverInfo: { readonly name?: string | null; readonly version?: string | null }
  readonly protocolVersion: string
  readonly credentialScope: 'unproven'
  readonly credentialsExcluded: readonly string[]
  readonly proves: readonly string[]
  readonly doesNotProve: readonly string[]
}

/** Connection observation classes the session surface distinguishes
 * (contracts.md §2: pending / connected / catalog-changed / refused). */
export type McpConnectionObservation = 'pending' | 'connected' | 'catalog-changed' | 'refused' | 'unknown'

/** `mcp.inspectConnection` facts (lease facts only; a definition row is never
 * disguised as a live connection). */
export interface McpConnectionFacts {
  readonly definitionId: string
  readonly revision: number
  readonly generation: number | null
  readonly observation: McpConnectionObservation
  readonly refusalReason?: string | null
  /** Tri-state: true/false are evidenced, null means the backend said nothing
   * (never upgraded to false, and never to true). */
  readonly callableNow?: boolean | null
}

/** `mcp.listTools` catalog facts for one session generation. */
export interface McpCatalogFacts {
  readonly definitionId: string
  readonly generation: number | null
  readonly tools: readonly { readonly name: string }[]
  /** Backend-stated catalog drift against the selection in force. */
  readonly catalogChanged?: boolean | null
}

/** The session/draft target the status surface is asked about. Structurally
 * compatible with chat-api `ChatLocation` (identity fields only; the UI never
 * guesses identity from titles or endpoints). */
export interface McpSessionTarget {
  readonly kind: 'session' | 'draft'
  readonly connectionId?: string
  readonly serverInstanceId?: string
  readonly sessionId?: string
  readonly draftId?: string
}

/** Assignment view (`mcp.assign`/`mcp.unassign` read shape). */
export interface McpAssignmentView {
  readonly scopeKind: 'user' | 'project' | 'profile'
  readonly scopeId: string
  readonly definitionId: string
  readonly revision: number
  readonly enabled: boolean
  readonly toolSelection: readonly string[] | null
}

/** Preview of the effective set for one target (`mcp.resolvePreview` shape). */
export interface McpPreviewEntry {
  readonly definitionId: string
  readonly revision: number
  readonly enabled: boolean
  readonly toolSelection: readonly string[] | null
}
