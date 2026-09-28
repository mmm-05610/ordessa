// In-memory fakes for the MCP frontend tests. They implement the same
// McpWireClient interface the production fetch client implements — the tests
// never stub around the seam, they replace it.

import type {
  McpAssignmentView, McpCatalogFacts, McpConnectionFacts, McpDefinitionSummary, McpProbeFacts, McpRevisionView,
} from '../src/dto'
import type { McpWireClient } from '../src/wire'
import { McpWireError } from '../src/wire'

export const baseDefinition: McpRevisionView = {
  definitionId: 'srv-a', revision: 2, canonicalDigest: 'sha256:aaa',
  canonical: {
    name: 'srv-a',
    transport: { stdio: { command: '/bin/srv-a', args: ['--x'], env: { TOKEN: { secretRef: 'cred-1' }, LOG: { literal: 'debug' } } } },
  },
  canonicalShape: 'v2', source: null, createdAt: '2026-09-01T00:00:00Z',
  approval: { actor: 'user', approvedAt: '2026-09-01T00:00:00Z' },
}

export const baseSummary: McpDefinitionSummary = {
  definitionId: 'srv-a', name: 'srv-a', transport: 'stdio', latestRevision: 2,
  approvedRevision: 1, source: '导入 · claude_desktop', archived: false,
  lastProbe: { result: 'ok', revision: 2, at: '2026-09-20T10:00:00Z' },
}

export const probeFacts: McpProbeFacts = {
  status: 'ok', transport: 'stdio', evidence: 'initialize-handshake',
  serverInfo: { name: 'srv-a', version: '0.1' }, protocolVersion: '2025-06-18',
  credentialScope: 'unproven', credentialsExcluded: ['env.TOKEN'],
  proves: ['initialize-handshake'],
  doesNotProve: ['tool-catalog', 'credential-usability', 'connection-lease', 'tool-invocability'],
}

export interface FakeWireState {
  definitions: McpDefinitionSummary[]
  revisions: Record<string, McpRevisionView>
  connections: Record<string, McpConnectionFacts>
  catalogs: Record<string, McpCatalogFacts>
  previewEntries: { definitionId: string; revision: number; enabled: boolean; toolSelection: readonly string[] | null }[]
  failOn: Partial<Record<keyof McpWireClient | 'listTools', string>>
}

export interface FakeWire extends McpWireClient {
  readonly state: FakeWireState
  readonly calls: { method: string; params: unknown }[]
}

export function createFakeWireClient(overrides: Partial<FakeWireState> = {}): FakeWire {
  const state: FakeWireState = {
    definitions: [{ ...baseSummary }],
    revisions: { 'srv-a': { ...baseDefinition } },
    connections: {},
    catalogs: {},
    previewEntries: [],
    failOn: {},
    ...overrides,
  }
  const calls: FakeWire['calls'] = []
  const guard = <T>(method: keyof McpWireClient, params: unknown, value: T): T => {
    calls.push({ method, params })
    const failure = state.failOn[method]
    if (failure) throw new McpWireError(`${method.toUpperCase()}_FAILED`, failure)
    return value
  }
  return {
    calls,
    get state() { return state },
    listDefinitions: async signal => guard('listDefinitions', {}, state.definitions.map(row => ({ ...row }))),
    getDefinition: async definitionId => guard('getDefinition', { definitionId }, state.revisions[definitionId]),
    saveRevision: async input => {
      const definitionId = input.definitionId ?? 'srv-new'
      const revision = (state.revisions[definitionId]?.revision ?? 0) + 1
      state.revisions[definitionId] = {
        ...baseDefinition, definitionId, revision, canonical: input.definition, approval: null,
      }
      return guard('saveRevision', input, { definitionId, revision, canonicalDigest: `sha256:${revision}` })
    },
    approveRevision: async input => {
      state.definitions = state.definitions.map(item =>
        item.definitionId === input.definitionId ? { ...item, approvedRevision: input.revision } : item)
      return guard('approveRevision', input, { approvedRevision: input.revision })
    },
    archiveDefinition: async input => guard('archiveDefinition', input, { archived: true }),
    probe: async input => {
      const stored = state.revisions[input.definitionId]
      const facts: McpProbeFacts = {
        ...probeFacts,
        transport: stored && 'stdio' in stored.canonical.transport ? 'stdio' : 'remote',
      }
      return guard('probe', input, facts)
    },
    assign: async input => {
      const view: McpAssignmentView = {
        scopeKind: input.scopeKind, scopeId: input.scopeId, definitionId: input.definitionId,
        revision: input.revision, enabled: input.enabled, toolSelection: input.toolSelection,
      }
      const preview = state.previewEntries.find(entry => entry.definitionId === input.definitionId)
      if (preview) Object.assign(preview, { enabled: input.enabled, revision: input.revision })
      else state.previewEntries.push({ definitionId: input.definitionId, revision: input.revision, enabled: input.enabled, toolSelection: input.toolSelection })
      return guard('assign', input, view)
    },
    unassign: async input => {
      state.previewEntries = state.previewEntries.filter(entry => entry.definitionId !== input.definitionId)
      return guard('unassign', input, { removed: true })
    },
    resolvePreview: async input => guard('resolvePreview', input, { entries: state.previewEntries.map(entry => ({ ...entry })) }),
    inspectConnection: async ({ definitionId }) => guard('inspectConnection', { definitionId },
      state.connections[definitionId] ?? { definitionId, revision: 1, generation: null, observation: 'pending', callableNow: null }),
    listTools: async ({ definitionId }) => guard('listTools', { definitionId },
      state.catalogs[definitionId] ?? { definitionId, generation: null, tools: [], catalogChanged: null }),
  }
}
