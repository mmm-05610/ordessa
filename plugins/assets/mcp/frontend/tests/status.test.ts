// Six-tier grading (FR-02): each tier only lights up on its own evidence, and
// an absent service stays absent.

import { describe, expect, it } from 'vitest'
import { createMcpStatusService, MCP_LEVEL_LABELS } from '../src/status'
import { createFakeWireClient } from './fakes'

const target = { kind: 'session', connectionId: 'conn-1', sessionId: 'sess-1' } as const

describe('createMcpStatusService without a wire client', () => {
  it('reports absent everywhere and exposes no fake data', async () => {
    const service = createMcpStatusService(undefined)
    expect(service.snapshot(target)).toEqual({ status: 'absent', servers: [] })
    await expect(service.refresh(target)).resolves.toEqual({ status: 'absent', servers: [] })
    expect(service.select).toBeUndefined()
  })
})

describe('createMcpStatusService grading', () => {
  it('stops at `approved` when nothing is enabled for the session', async () => {
    const client = createFakeWireClient()
    const facts = await createMcpStatusService(client).refresh(target)
    expect(facts.status).toBe('ready')
    expect(facts.servers).toHaveLength(1)
    expect(facts.servers[0].reachedLevel).toBe('approved')
    expect(facts.servers[0].observation).toBe('none')
    expect(facts.servers[0].callableNow).toBeNull()
    // No inspectConnection / listTools was ever attempted for an un-enabled row.
    expect(client.calls.some(call => call.method === 'inspectConnection')).toBe(false)
  })

  it('walks enabled → connected → catalog and keeps `callable` unconfirmed unless the backend states it', async () => {
    const client = createFakeWireClient({
      previewEntries: [{ definitionId: 'srv-a', revision: 1, enabled: true, toolSelection: null }],
      connections: { 'srv-a': { definitionId: 'srv-a', revision: 1, generation: 7, observation: 'connected', callableNow: null } },
      catalogs: { 'srv-a': { definitionId: 'srv-a', generation: 7, tools: [{ name: 'echo' }, { name: 'add' }], catalogChanged: false } },
    })
    const server = (await createMcpStatusService(client).refresh(target)).servers[0]
    expect(server.reachedLevel).toBe('catalog')
    expect(server.observation).toBe('connected')
    expect(server.toolsDiscovered).toBe(2)
    expect(server.callableNow).toBeNull()
  })

  it('pending is not connected, refused carries its reason, catalog-changed stays distinct', async () => {
    const pendingClient = createFakeWireClient({
      previewEntries: [{ definitionId: 'srv-a', revision: 1, enabled: true, toolSelection: null }],
      connections: { 'srv-a': { definitionId: 'srv-a', revision: 1, generation: null, observation: 'pending', callableNow: null } },
    })
    const pending = (await createMcpStatusService(pendingClient).refresh(target)).servers[0]
    expect(pending.reachedLevel).toBe('enabled')
    expect(pending.observation).toBe('pending')

    const refusedClient = createFakeWireClient({
      previewEntries: [{ definitionId: 'srv-a', revision: 1, enabled: true, toolSelection: null }],
      connections: { 'srv-a': { definitionId: 'srv-a', revision: 1, generation: null, observation: 'refused', refusalReason: 'approval revoked', callableNow: false } },
    })
    const refused = (await createMcpStatusService(refusedClient).refresh(target)).servers[0]
    expect(refused.reachedLevel).toBe('enabled')
    expect(refused.observation).toBe('refused')

    const changedClient = createFakeWireClient({
      previewEntries: [{ definitionId: 'srv-a', revision: 1, enabled: true, toolSelection: null }],
      connections: { 'srv-a': { definitionId: 'srv-a', revision: 1, generation: 2, observation: 'connected', callableNow: null } },
      catalogs: { 'srv-a': { definitionId: 'srv-a', generation: 2, tools: [], catalogChanged: true } },
    })
    const changed = (await createMcpStatusService(changedClient).refresh(target)).servers[0]
    expect(changed.observation).toBe('catalog-changed')
  })

  it('a connection listing failure degrades that tier only — definitions stay visible with an error note', async () => {
    const client = createFakeWireClient({
      previewEntries: [{ definitionId: 'srv-a', revision: 1, enabled: true, toolSelection: null }],
    })
    client.state.failOn.inspectConnection = 'connection registry unavailable'
    const facts = await createMcpStatusService(client).refresh(target)
    expect(facts.status).toBe('ready')
    expect(facts.servers[0].reachedLevel).toBe('enabled')
    expect(facts.servers[0].note).toContain('connection registry unavailable')
  })

  it('a failing definition listing surfaces as an error status, not as an empty success', async () => {
    const client = createFakeWireClient()
    client.state.failOn.listDefinitions = 'mcp service down'
    const facts = await createMcpStatusService(client).refresh(target)
    expect(facts.status).toBe('error')
    expect(facts.error).toContain('mcp service down')
  })

  it('callable lights only when the backend states it AND the catalog exists', async () => {
    const client = createFakeWireClient({
      previewEntries: [{ definitionId: 'srv-a', revision: 1, enabled: true, toolSelection: null }],
      connections: { 'srv-a': { definitionId: 'srv-a', revision: 1, generation: 3, observation: 'connected', callableNow: true } },
      catalogs: { 'srv-a': { definitionId: 'srv-a', generation: 3, tools: [{ name: 'echo' }], catalogChanged: null } },
    })
    const server = (await createMcpStatusService(client).refresh(target)).servers[0]
    expect(server.reachedLevel).toBe('callable')
    expect(server.reachedLevel && MCP_LEVEL_LABELS[server.reachedLevel]).toBe('本次可调用')
  })

  it('a draft target has no session facts and never calls connection methods', async () => {
    const client = createFakeWireClient()
    const facts = await createMcpStatusService(client).refresh({ kind: 'draft', draftId: 'd1' })
    expect(facts.servers).toEqual([])
    expect(client.calls.map(call => call.method)).toEqual([])
  })
})
