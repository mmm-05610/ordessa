// Chat panel glue runs through the REAL chat-api r3 registry
// (createChatContributions + chatContribution + addInputSource/queryInputSources):
// the tests below register the MCP source the same way the session UI will,
// proving the consumption seam, not a stubbed copy of it.

import { describe, expect, it } from 'vitest'
import { OwnedResources } from '@ordessa/extension-api'
import { createChatContributions, type ChatInputQuery, type ChatLocation } from '@extensions/ordessa.chat-api/contract.js'
import { createMcpChatInputSource, mcpStatusChipContribution, serverFactLine, summarizeMcpFacts, MCP_CHAT_SOURCE_ID } from '../src/chat'
import { createMcpStatusService, type McpStatusService } from '../src/status'
import { createFakeWireClient } from './fakes'

const cleanup: OwnedResources[] = []
const newScope = () => { const scope = new OwnedResources(); cleanup.push(scope); return scope }

const sessionLocation: ChatLocation = { kind: 'session', connectionId: 'conn-1', sessionId: 'sess-1', contextRevision: 1 }

function queryRequest(overrides: Partial<ChatInputQuery> = {}): ChatInputQuery {
  return { location: sessionLocation, query: '', surface: 'plus', signal: new AbortController().signal, ...overrides }
}

async function queryReady(chat: ReturnType<typeof createChatContributions>, request: ChatInputQuery) {
  const view = chat.queryInputSources(request)
  // The registry resolves source queries asynchronously; poll until no source
  // is loading (same cadence the shared panel uses).
  for (let i = 0; i < 50 && view.getSnapshot().some(source => source.state.status === 'loading'); i++)
    await new Promise(resolve => setTimeout(resolve, 0))
  return view.getSnapshot()
}

describe('MCP chat input source without a status provider', () => {
  it('registers into the real ChatContributions service and answers with the unavailable row', async () => {
    const chat = createChatContributions()
    const scope = newScope()
    chat.forScope(scope).addInputSource(createMcpChatInputSource(undefined))
    const [sourceView] = await queryReady(chat, queryRequest())
    expect(sourceView.source.id).toBe(MCP_CHAT_SOURCE_ID)
    expect(sourceView.state.status).toBe('ready')
    expect(sourceView.entries).toHaveLength(1)
    expect(sourceView.entries[0].title).toBe('MCP 状态服务不可用')
    expect(sourceView.entries[0].availability).toEqual({ kind: 'disabled', reason: 'mcp-status-service-absent' })
  })

  it('scope close revokes exactly the MCP source', async () => {
    const chat = createChatContributions()
    const scope = newScope()
    chat.forScope(scope).addInputSource(createMcpChatInputSource(undefined))
    scope.dispose()
    const view = await queryReady(chat, queryRequest())
    expect(view.find(source => source.source.id === MCP_CHAT_SOURCE_ID)).toBeUndefined()
  })
})

describe('MCP chat input source with live facts', () => {
  const enabledStatus = (): { source: ReturnType<typeof createMcpChatInputSource>; status: McpStatusService } => {
    const client = createFakeWireClient({
      previewEntries: [{ definitionId: 'srv-a', revision: 1, enabled: true, toolSelection: null }],
      connections: { 'srv-a': { definitionId: 'srv-a', revision: 1, generation: 4, observation: 'connected', callableNow: null } },
      catalogs: { 'srv-a': { definitionId: 'srv-a', generation: 4, tools: [{ name: 'echo' }], catalogChanged: null } },
    })
    const status = createMcpStatusService(client)
    return { source: createMcpChatInputSource(status), status }
  }

  it('one row per server carries the graded line: connected with a catalog, callable still unconfirmed', async () => {
    const chat = createChatContributions()
    const { source } = enabledStatus()
    chat.forScope(newScope()).addInputSource(source)
    const [sourceView] = await queryReady(chat, queryRequest())
    expect(sourceView.entries).toHaveLength(1)
    const entry = sourceView.entries[0]
    expect(entry.id).toBe('mcp.server.srv-a')
    expect(entry.description).toContain('连接成功')
    expect(entry.description).toContain('工具已发现 1 个')
    expect(entry.description).toContain('可调用性未确认')
    expect(entry.description).toContain('批准修订 r1')
  })

  it('pending never renders as connected', async () => {
    const client = createFakeWireClient({
      previewEntries: [{ definitionId: 'srv-a', revision: 1, enabled: true, toolSelection: null }],
      connections: { 'srv-a': { definitionId: 'srv-a', revision: 1, generation: null, observation: 'pending', callableNow: null } },
    })
    const line = serverFactLine((await createMcpStatusService(client).refresh({ kind: 'session', connectionId: 'c', sessionId: 's' })).servers[0])
    expect(line).toContain('连接确认中（pending，非已连接）')
    expect(line).not.toContain('连接成功')
  })

  it('selection rows stay disabled with a reason when the owner provides no select', async () => {
    const chat = createChatContributions()
    const { source } = enabledStatus()
    chat.forScope(newScope()).addInputSource(source)
    const [sourceView] = await queryReady(chat, queryRequest())
    const availability = sourceView.entries[0].availability
    expect(availability.kind).toBe('disabled')
  })

  it('an owner-provided select makes rows ready and routes the toggle through it', async () => {
    const calls: [string, boolean][] = []
    const status = createMcpStatusService(createFakeWireClient(), {
      select: async (_target, definitionId, enabled) => { calls.push([definitionId, enabled]); return { status: 'accepted' as const } },
    })
    const chat = createChatContributions()
    chat.forScope(newScope()).addInputSource(createMcpChatInputSource(status))
    const [sourceView] = await queryReady(chat, queryRequest())
    expect(sourceView.entries[0].availability.kind).toBe('ready')
    // srv-a only reaches `approved` (nothing enabled) ⇒ toggle asks for on.
    const action = sourceView.entries[0].action
    if (action.kind === 'invoke') await action.execute(sessionLocation)
    expect(calls).toEqual([['srv-a', true]])
  })
})

describe('MCP composer toolbar contribution', () => {
  it('registers through chatContribution() on composer.toolbar and projects six-tier summaries', async () => {
    const chat = createChatContributions()
    const scope = newScope()
    chat.forScope(scope).addContribution(mcpStatusChipContribution(undefined))
    const [view] = chat.contributionsBySlot('composer.toolbar').getSnapshot()
    expect(view.id).toBe('ordessa.asset.mcp.status-chip')
    expect(view.keyId).toBe('ordessa.asset.mcp.status-chip')
    const projected = view.project!({ slot: 'composer.toolbar', location: sessionLocation, connection: { status: 'connected' } })
    expect(projected.hidden).toBe(false)
    expect(summarizeMcpFacts((projected as { props: { facts: never } }).props.facts)).toBe('MCP：状态服务不可用')
    const other = view.project!({ slot: 'session.actions', location: sessionLocation })
    expect(other.hidden).toBe(true)
  })

  it('a live snapshot summarizes defined/connected/catalog/callable separately', () => {
    const facts = {
      status: 'ready' as const,
      servers: [
        { definitionId: 'a', name: 'a', transport: 'stdio' as const, reachedLevel: 'connected' as const, observation: 'connected' as const, approvedRevision: 1, toolsDiscovered: null, callableNow: null },
        { definitionId: 'b', name: 'b', transport: 'stdio' as const, reachedLevel: 'catalog' as const, observation: 'connected' as const, approvedRevision: 2, toolsDiscovered: 3, callableNow: true },
      ],
    }
    expect(summarizeMcpFacts(facts)).toBe('MCP：已定义 2 · 连接 2 · 工具目录 1 · 可调用 1')
  })
})
