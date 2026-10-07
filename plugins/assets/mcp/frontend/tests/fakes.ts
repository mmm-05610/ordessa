import type { McpCatalogFacts, McpConnectionFacts, McpDefinitionSummary, McpProbeFacts, McpRevisionView } from '../src/dto'
import type { McpWireClient } from '../src/wire'
import { McpWireError } from '../src/wire'
export const baseDefinition: McpRevisionView = {
  definitionId: 'srv-a', revision: 2, digest: 'sha256:aaa', shape: 'v2',
  source: '导入 · claude_desktop', createdAt: '2026-09-01T00:00:00Z',
  approval: { actor: 'user', approvedAt: '2026-09-01T00:00:00Z' },
}
export const baseSummary: McpDefinitionSummary = {
  definitionId: 'srv-a', nativeName: 'srv-a', transport: 'stdio', latestRevision: 2, serverScope: 'scope', archived: false,
}
export const probeFacts: McpProbeFacts = {
  status: 'ok', transport: 'stdio', evidence: 'initialize-handshake', serverInfo: { name: 'srv-a', version: '0.1' }, protocolVersion: '2025-06-18',
  negotiation: { requested: '2025-06-18', supported: ['2025-06-18'], negotiated: '2025-06-18' },
  credentialScope: 'unproven', credentialsExcluded: ['env.TOKEN'], proves: ['initialize-handshake'],
  doesNotProve: ['tool-catalog', 'credential-usability', 'connection-lease', 'tool-invocability'],
}
export function catalogFacts(toolNames: readonly string[] = ['echo']): McpCatalogFacts {
  return { leaseId: 'lease-a', definitionId: 'srv-a', revision: 1, observedAt: '2026-09-01T00:00:00Z',
    protocolVersion: '2025-06-18', serverInfo: {}, toolNames, toolSchemaDigests: {}, catalogDigest: 'digest', sourceEvidence: {}, status: 'observed' }
}
export const runtimeContext = { context: () => ({ sessionRef: 'sess-1', runtimeGeneration: 7 }) }
export interface FakeWireState {
  definitions: McpDefinitionSummary[]
  revisions: Record<string, McpRevisionView>
  connections: Record<string, McpConnectionFacts>
  catalogs: Record<string, McpCatalogFacts>
  previewEntries: { definitionId: string; revision: number; enabled: boolean; toolSelection: readonly string[] | null }[]
  failOn: Partial<Record<keyof McpWireClient, string>>
}
export interface FakeWire extends McpWireClient { readonly state: FakeWireState; readonly calls: { method: string; params: unknown }[] }
export function createFakeWireClient(overrides: Partial<FakeWireState> = {}): FakeWire {
  const state: FakeWireState = { definitions: [{ ...baseSummary }], revisions: { 'srv-a': { ...baseDefinition } }, connections: {}, catalogs: {}, previewEntries: [], failOn: {}, ...overrides }
  const calls: FakeWire['calls'] = []
  const guard = <T>(method: keyof McpWireClient, params: unknown, value: T): T => {
    calls.push({ method, params })
    if (state.failOn[method]) throw new McpWireError(`${method.toUpperCase()}_FAILED`, state.failOn[method])
    return value
  }
  return {
    state, calls,
    listDefinitions: async () => guard('listDefinitions', {}, state.definitions),
    getDefinition: async definitionId => guard('getDefinition', { definitionId }, state.revisions[definitionId]),
    saveRevision: async input => {
      const version = state.revisions[input.definitionId]?.revision ?? 0
      if (input.expectedVersion !== version) throw new McpWireError('CAS_CONFLICT', 'revision changed')
      const revision = { ...baseDefinition, definitionId: input.definitionId, revision: version + 1, approval: null }
      const definition = { ...baseSummary, definitionId: input.definitionId, nativeName: input.definition.name, latestRevision: revision.revision, transport: 'stdio' in input.definition.transport ? 'stdio' as const : 'remote' as const }
      guard('saveRevision', input, null)
      state.revisions[input.definitionId] = revision
      state.definitions = [...state.definitions.filter(row => row.definitionId !== input.definitionId), definition]
      return { definition, revision, replayed: false }
    },
    approveRevision: async input => {
      const approval = { actor: 'user', approvedAt: '2026-09-30T00:00:00Z' }
      guard('approveRevision', input, null)
      state.revisions[input.definitionId] = { ...state.revisions[input.definitionId], approval }
      return { definitionId: input.definitionId, revision: input.revision, approval }
    },
    archiveDefinition: async input => guard('archiveDefinition', input, { ...baseSummary, definitionId: input.definitionId, archived: true }),
    probe: async input => guard('probe', input, probeFacts),
    assign: async input => guard('assign', input, { scopeKind: input.scopeKind, scopeId: input.scopeId, definitionId: input.definitionId, decision: input.decision, rowVersion: input.expectedRowVersion + 1, harness: input.harness ?? '*', approvedRevision: input.approvedRevision ?? null }),
    unassign: async input => guard('unassign', input, { scopeKind: input.scopeKind, scopeId: input.scopeId, definitionId: input.definitionId, decision: 'inherit' as const, rowVersion: null, harness: input.harness ?? '*', approvedRevision: null, removed: true }),
    resolvePreview: async input => guard('resolvePreview', input, { snapshot: {
      targetSession: input.targetSession ?? null, runtimeGeneration: input.runtimeGeneration ?? null, projectId: null, profileRevision: null,
      definitionRevisions: state.previewEntries.filter(row => row.enabled).map(row => ({ definitionId: row.definitionId, revision: row.revision, canonicalDigest: 'digest', canonicalShape: 'v2' })),
      assignmentRevisions: [], credentialRefRevisions: [], allowedToolNames: [], laneByDefinition: {}, needsRevalidation: [], snapshotDigest: 'snapshot', submissionId: null,
    }, nativePermissionPostures: [] }),
    inspectConnection: async input => guard('inspectConnection', input, state.connections[input.leaseId] ?? { definitionId: 'srv-a', revision: 1, generation: input.runtimeGeneration, observation: 'pending', callableNow: null }),
    listTools: async input => {
      const catalog = state.catalogs[input.definitionId]
      guard('listTools', input, null)
      if (!catalog) throw new McpWireError('MCP_CATALOG_MISSING', 'catalog absent')
      return { leaseId: catalog.leaseId, catalog }
    },
  }
}
