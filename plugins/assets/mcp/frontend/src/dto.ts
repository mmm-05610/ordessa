// MCP wire DTO shapes (frontend glue; Q4 T08 originally, aligned to the live
// registration face by the 016 CMP reconciliation — specs/011-q4-mcp/reports/
// wire-alignment.md; every interface below is pinned field-by-field against
// REAL round-trip dispatches by tests/contract/test_wire_contract_guard.py
// WCG-03).
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

/** The scope kinds the backend accepts (`backend/assignment.py SCOPE_KINDS`;
 * the legacy `'user'` spelling is not dispatchable — WCG-04 pins the pair). */
export type McpScopeKind = 'user-default' | 'project' | 'profile' | 'session'

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

/** `mcp.get → latestRevision` (the live revision read row; the canonical
 * document itself is NOT part of this answer — it travels only on writes). */
export interface McpRevisionView {
  readonly definitionId: string
  readonly revision: number
  readonly digest: string
  readonly shape: 'legacy' | 'v2'
  readonly source: string | null
  readonly createdAt: string
  readonly approval: McpApproval | null
}

/** `mcp.list → definitions[i]` row: the identity face of a stored definition
 * (probe outcomes are per-session facts and deliberately absent here). */
export interface McpDefinitionSummary {
  readonly definitionId: string
  readonly nativeName: string
  readonly transport: McpTransportKind
  readonly latestRevision: number
  readonly serverScope: string
  readonly archived: boolean
}

/** `mcp.saveRevision` answer: the stored candidate (`replayed` distinguishes a
 * CAS replay from a fresh store), never an approval. */
export interface McpSaveRevisionResult {
  readonly definition: McpDefinitionSummary
  readonly replayed: boolean
  readonly revision: McpRevisionView
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
  readonly negotiation: { readonly requested: string; readonly supported: readonly string[]; readonly negotiated: string }
  readonly credentialScope: 'unproven'
  readonly credentialsExcluded: readonly string[]
  readonly proves: readonly string[]
  readonly doesNotProve: readonly string[]
}

/** Connection observation classes the session surface distinguishes
 * (contracts.md §2: pending / connected / catalog-changed / refused). */
export type McpConnectionObservation = 'pending' | 'connected' | 'catalog-changed' | 'refused' | 'unknown'

/** `mcp.inspectConnection → connection` facts (lease facts only; a definition
 * row is never disguised as a live connection). */
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

/** The live catalog view (`backend/service.py catalog_view`) behind
 * `mcp.listTools`. */
export interface McpCatalogFacts {
  readonly leaseId: string
  readonly definitionId: string
  readonly revision: number
  readonly observedAt: string
  readonly protocolVersion: string
  readonly serverInfo: Readonly<Record<string, unknown>>
  readonly toolNames: readonly string[]
  readonly toolSchemaDigests: Readonly<Record<string, string>>
  readonly catalogDigest: string
  readonly sourceEvidence: Readonly<Record<string, unknown>>
  readonly status: string
}

/** `mcp.listTools` answer: the lease serving the read plus its catalog. */
export interface McpListToolsResult {
  readonly leaseId: string
  readonly catalog: McpCatalogFacts
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

/** Assignment view (`mcp.assign → assignment`): one scope decision row. The
 * approved revision and decision travel here, not on the definition row. */
export interface McpAssignmentView {
  readonly scopeKind: McpScopeKind
  readonly scopeId: string
  readonly definitionId: string
  readonly decision: 'enable' | 'disable' | 'inherit'
  readonly rowVersion: number
  readonly harness: string
  readonly approvedRevision: number | null
}

/** `mcp.unassign → assignment`: the row after removal (`removed` states the
 * effect; `rowVersion` is null once the row is gone). */
export interface McpUnassignView {
  readonly scopeKind: McpScopeKind
  readonly scopeId: string
  readonly definitionId: string
  readonly decision: 'enable' | 'disable' | 'inherit'
  readonly rowVersion: number | null
  readonly harness: string
  readonly approvedRevision: number | null
  readonly removed: boolean
}

/** One definition's bound revision inside the effective snapshot
 * (`backend/service.py snapshot_view`). */
export interface McpSnapshotDefinitionRevision {
  readonly definitionId: string | null
  readonly revision: number | null
  readonly canonicalDigest: string | null
  readonly canonicalShape: string | null
}

/** One scope assignment row inside the effective snapshot. */
export interface McpSnapshotAssignmentRevision {
  readonly definitionId: string | null
  readonly scopeKind: string | null
  readonly scopeId: string | null
  readonly harness: string | null
  readonly decision: string | null
  readonly rowVersion: number | null
}

/** One credential reference binding inside the effective snapshot. */
export interface McpSnapshotCredentialRef {
  readonly definitionId: string | null
  readonly revision: number | null
  readonly slot: string | null
  readonly credentialId: string | null
}

/** The frozen effective set (`mcp.resolvePreview → snapshot`;
 * `snapshotDigest` is the answer-side binding — there is no client-supplied
 * scope-revision echo). */
export interface McpEffectiveSnapshot {
  readonly targetSession: string | null
  readonly runtimeGeneration: number | null
  readonly projectId: string | null
  readonly profileRevision: string | null
  readonly definitionRevisions: readonly McpSnapshotDefinitionRevision[]
  readonly assignmentRevisions: readonly McpSnapshotAssignmentRevision[]
  readonly credentialRefRevisions: readonly McpSnapshotCredentialRef[]
  readonly allowedToolNames: readonly string[]
  readonly laneByDefinition: Readonly<Record<string, Readonly<Record<string, string>>>>
  readonly needsRevalidation: readonly string[]
  readonly snapshotDigest: string
  readonly submissionId: string | null
}

/** One harness-native posture display row (`backend/permissions.py
 * posture_view`). `claimsOrdessaAuthority` is pinned to `false` by
 * construction (FR-09): the row never reads as Ordessa authority. */
export interface McpNativePermissionPosture {
  readonly definitionId: string
  readonly source: string
  readonly scope: string
  readonly policyRef: string
  readonly provenance: string
  readonly claimsOrdessaAuthority: false
}

/** `mcp.resolvePreview` answer: the frozen snapshot plus the honest native
 * posture rows beside it (T012; they label, never authorize). */
export interface McpPreviewResult {
  readonly snapshot: McpEffectiveSnapshot
  readonly nativePermissionPostures: readonly McpNativePermissionPosture[]
}
