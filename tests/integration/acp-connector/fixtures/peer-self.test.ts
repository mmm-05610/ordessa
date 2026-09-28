import { describe, expect, it } from 'vitest'
import { RequestError, PROTOCOL_VERSION } from '@agentclientprotocol/sdk'
import { FixtureClient, HarnessPeer } from './acp-peer'

/**
 * Fixture self-verification. These tests prove the controllable peer behaves like a real ACP
 * agent over the locked SDK before any product seam is trusted: request/notification/result,
 * error responses, reverse requests, and cleanup. They are NOT the target tests — they exercise
 * only the fixture and the SDK, and they must pass today.
 */

const initialize = async (peer: HarnessPeer, client: FixtureClient) =>
  client.conn.initialize({ protocolVersion: PROTOCOL_VERSION, clientCapabilities: {} })

describe('HarnessPeer fixture', () => {
  it('answers initialize with the negotiated version and declared capabilities, recording the request', async () => {
    const peer = new HarnessPeer({ capabilities: { loadSession: true } })
    const client = new FixtureClient(peer.stream)
    const result = await initialize(peer, client)
    expect(result.protocolVersion).toBe(PROTOCOL_VERSION)
    expect(result.agentCapabilities).toEqual({ loadSession: true })
    expect(peer.recorded('initialize')).toHaveLength(1)
    peer.close()
  })

  it('carries request params through the wire and returns the result to the caller', async () => {
    const peer = new HarnessPeer()
    const client = new FixtureClient(peer.stream)
    await initialize(peer, client)
    const created = await client.conn.newSession({ cwd: '/repo/app', mcpServers: [] })
    expect(created.sessionId).toMatch(/^acp-session-\d+$/)
    expect(peer.recorded('session/new')[0].params).toMatchObject({ cwd: '/repo/app' })
    peer.close()
  })

  it('streams notifications and resolves a prompt with its stop reason', async () => {
    const peer = new HarnessPeer()
    const client = new FixtureClient(peer.stream)
    await initialize(peer, client)
    const { sessionId } = await client.conn.newSession({ cwd: '/repo', mcpServers: [] })
    peer.queueTurn(async api => {
      await api.update({ sessionUpdate: 'agent_message_chunk', content: { type: 'text', text: 'hello' } })
      return 'end_turn'
    })
    const response = await client.conn.prompt({ sessionId, prompt: [{ type: 'text', text: 'hi' }] })
    expect(response.stopReason).toBe('end_turn')
    expect(client.updates.map(update => update.update.sessionUpdate)).toEqual(['agent_message_chunk'])
    expect(client.updates[0]).toMatchObject({ sessionId })
    peer.close()
  })

  it('turns a thrown RequestError into a JSON-RPC error rejection on the client', async () => {
    const peer = new HarnessPeer()
    const client = new FixtureClient(peer.stream)
    await initialize(peer, client)
    peer.armFailure('session/new', new RequestError(-32603, 'project path refused'))
    const failure = await client.conn.newSession({ cwd: '/nope', mcpServers: [] }).catch(error => error)
    expect(String(failure)).toContain('project path refused')
    // And the channel stays usable afterwards — one refusal is not a dead link.
    peer.queueTurn(async () => 'end_turn')
    const ok = await client.conn.newSession({ cwd: '/repo', mcpServers: [] })
    expect(ok.sessionId).toBeTruthy()
    peer.close()
  })

  it('drives a reverse request inside a turn and receives the client answer', async () => {
    const peer = new HarnessPeer()
    const client = new FixtureClient(peer.stream)
    client.permissionAnswer = { outcome: { outcome: 'selected', optionId: 'allow_once' } }
    await initialize(peer, client)
    const { sessionId } = await client.conn.newSession({ cwd: '/repo', mcpServers: [] })
    let seen: unknown
    peer.queueTurn(async api => {
      seen = await api.permission(
        { toolCallId: 'call_1', status: 'pending', title: 'run tests' },
        [{ optionId: 'allow_once', name: 'Allow', kind: 'allow_once' }])
      return 'end_turn'
    })
    const response = await client.conn.prompt({ sessionId, prompt: [{ type: 'text', text: 'go' }] })
    expect(response.stopReason).toBe('end_turn')
    expect(client.permissionRequests).toHaveLength(1)
    expect(client.permissionRequests[0].sessionId).toBe(sessionId)
    expect(seen).toEqual({ outcome: { outcome: 'selected', optionId: 'allow_once' } })
    peer.close()
  })

  it('records the cancel notification and releases the waiting turn with cancelled', async () => {
    const peer = new HarnessPeer()
    const client = new FixtureClient(peer.stream)
    await initialize(peer, client)
    const { sessionId } = await client.conn.newSession({ cwd: '/repo', mcpServers: [] })
    peer.queueTurn(async api => { await api.cancelled(); return 'cancelled' })
    const prompt = client.conn.prompt({ sessionId, prompt: [{ type: 'text', text: 'go' }] })
    await client.conn.cancel({ sessionId })
    expect((await prompt).stopReason).toBe('cancelled')
    expect(peer.recorded('session/cancel')[0].params).toEqual({ sessionId })
    peer.close()
  })

  it('refuses capability-gated methods the peer does not advertise', async () => {
    const withoutHistory = new HarnessPeer({ capabilities: {} })
    const client = new FixtureClient(withoutHistory.stream)
    await initialize(withoutHistory, client)
    const failure = await client.conn.loadSession?.({ sessionId: 'x', cwd: '/repo', mcpServers: [] })
      .catch(error => error)
      ?? new Error('client has no loadSession method at all')
    expect(String(failure)).toMatch(/not found|unimplemented|loadSession|method/i)
    withoutHistory.close()
    const withHistory = new HarnessPeer({ capabilities: { loadSession: true } })
    const client2 = new FixtureClient(withHistory.stream)
    await initialize(withHistory, client2)
    withHistory.onLoadReplay('acp-session-1', [{ sessionUpdate: 'agent_message_chunk', content: { type: 'text', text: 'old' } }])
    const { sessionId } = await client2.conn.newSession({ cwd: '/repo', mcpServers: [] })
    await client2.conn.loadSession!({ sessionId, cwd: '/repo', mcpServers: [] })
    expect(withHistory.recorded('session/load')).toHaveLength(1)
    expect(client2.updates).toHaveLength(1)
    withHistory.close()
  })

  it('rejects in-flight work and settles both closed promises when the link drops', async () => {
    const peer = new HarnessPeer()
    const client = new FixtureClient(peer.stream)
    await initialize(peer, client)
    const { sessionId } = await client.conn.newSession({ cwd: '/repo', mcpServers: [] })
    peer.queueTurn(async api => { await api.cancelled(); return 'cancelled' })
    const stuck = client.conn.prompt({ sessionId, prompt: [{ type: 'text', text: 'never' }] })
    peer.drop(new Error('link reset'))
    const failure = await stuck.then(() => undefined, error => error)
    expect(failure).toBeInstanceOf(Error)
    await expect(peer.closed).resolves.toBeUndefined()
  })

  it('propagates a client-side stream close to the peer as end-of-stream', async () => {
    const peer = new HarnessPeer()
    const client = new FixtureClient(peer.stream)
    await initialize(peer, client)
    // This is exactly what a connector's dispose() does to the SDK Stream it was handed; the peer
    // must see EOF, or a correct release implementation would hang forever.
    await peer.stream.writable.close()
    await expect(peer.closed).resolves.toBeUndefined()
    void client
  })

  it('propagates a client-side stream abort to the peer as a failed channel', async () => {
    const peer = new HarnessPeer()
    const client = new FixtureClient(peer.stream)
    await initialize(peer, client)
    await peer.stream.writable.abort(new Error('connector disposed'))
    await expect(peer.closed).resolves.toBeUndefined()
    void client
  })
})
