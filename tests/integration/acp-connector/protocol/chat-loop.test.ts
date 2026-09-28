import { expect, it } from 'vitest'
import { PROTOCOL_VERSION, RequestError } from '@agentclientprotocol/sdk'
import type * as acp from '@agentclientprotocol/sdk'
import { connectTarget, connectTargetFor, loadAcpTarget } from '../fixtures/target-seam'
import type { AcpChannelHandle } from '../fixtures/target-seam'
import { HarnessPeer, deferred } from '../fixtures/acp-peer'

/**
 * Connection-loop targets R1–R7: the client reaches the Harness only through the orchestration
 * seam, channels exist only for a bound project, and the native session — never a frontend
 * stand-in — stays the authority. All red today with TARGET_MISSING; each assertion is written
 * against the pinned SDK's wire behavior.
 */

it('R1 connects with no project-less channel; binding a project acquires one and initializes it exactly once', async () => {
  const { peer, spec, client, acquired } = await connectTarget({ capabilities: { promptCapabilities: {} } })
  // Selecting a Server/Harness must not open an ACP channel that no project owns.
  expect(peer.recorded('initialize')).toHaveLength(0)
  expect(acquired).toEqual([])
  // The project-bound channel comes first, then exactly one `initialize` on it — and opening a
  // project is not a session: no `session/new` may ride along.
  await client.openWorkspace!('ws_app')
  expect(acquired).toEqual(['ws_app'])
  expect(peer.recorded('initialize')).toHaveLength(1)
  expect(peer.requests.find(r => r.method === 'initialize')?.params).toMatchObject({ protocolVersion: PROTOCOL_VERSION })
  expect(peer.recorded('session/new')).toHaveLength(0)
  const state = client.getSnapshot()
  expect(state.connection.status).toBe('connected')
  // A peer that never advertised loadSession or session/list must read as unsupported history.
  expect(state.connection.capabilities.history).toBe('unsupported')
  expect(state.connection.serverInstanceId).toBe(spec.serverInstanceId)
  peer.close()
})

it('R2 a Harness that advertises history reads as supported, absent never falls back', async () => {
  const bare = await connectTarget({ capabilities: {} })
  await bare.client.openWorkspace!('ws_app') // capabilities exist only from a real initialize answer
  expect(bare.client.getSnapshot().connection.capabilities.history).toBe('unsupported')
  bare.peer.close()
  const loaded = await connectTarget({ capabilities: { loadSession: true, sessionCapabilities: { list: {} } } })
  await loaded.client.openWorkspace!('ws_app')
  expect(loaded.client.getSnapshot().connection.capabilities.history).toBe('supported')
  loaded.peer.close()
})

it('R3 the first send creates the real session under the orchestration-bound project path', async () => {
  const { peer, client, acquired } = await connectTarget()
  await client.openWorkspace!('ws_app')
  // Draft state: binding a project creates no native session and none is invented.
  expect(client.getSnapshot().sessions).toEqual([])
  expect(client.getSnapshot().selectedSessionId).toBeUndefined()
  expect(peer.recorded('session/new')).toHaveLength(0)
  const accepted = await client.createAndSend!('ws_app', 'first text', 'req_1')
  const created = peer.recorded('session/new')[0]
  // ACP carries the project as the absolute `cwd` of `session/new` — the Server-authoritative path
  // from the project binding, never a locally guessed one.
  expect(created.params).toMatchObject({ cwd: '/repo/app' })
  // Same project-bound channel: still exactly one initialize.
  expect(acquired).toEqual(['ws_app'])
  expect(peer.recorded('initialize')).toHaveLength(1)
  expect(peer.recorded('session/prompt')[0].params).toMatchObject({
    sessionId: accepted.sessionId,
    prompt: [{ type: 'text', text: 'first text' }],
  })
  const state = client.getSnapshot()
  // The draft ends on the native id, selected and project-bound (FC-0031 semantics carried over).
  expect(state.selectedSessionId).toBe(accepted.sessionId)
  expect(state.sessions.find(s => s.id === accepted.sessionId)?.workspaceId).toBe('ws_app')
  peer.close()
})

it('R4 a project the orchestration does not offer never acquires a channel or reaches the ACP wire', async () => {
  const { peer, client, acquired } = await connectTarget()
  const failure = await client.createAndSend!('ws_missing', 'text', 'req_1').catch(error => error)
  expect(String(failure)).toMatch(/project-invalid/)
  // No binding, therefore no channel, therefore not one frame of ACP traffic.
  expect(acquired).toEqual([])
  expect(peer.recorded('initialize')).toHaveLength(0)
  expect(peer.recorded('session/new')).toHaveLength(0)
  expect(peer.recorded('session/prompt')).toHaveLength(0)
  expect(client.getSnapshot().sessions).toEqual([])
  peer.close()
})

it('R5 two consecutive turns reuse the one native session', async () => {
  const { peer, client } = await connectTarget()
  peer.queueTurn(async api => { await api.update({ sessionUpdate: 'agent_message_chunk', content: { type: 'text', text: 'one' } }); return 'end_turn' })
  const { sessionId } = await client.createAndSend!('ws_app', 'first', 'req_1')
  peer.queueTurn(async api => { await api.update({ sessionUpdate: 'agent_message_chunk', content: { type: 'text', text: 'two' } }); return 'end_turn' })
  await client.send(sessionId, 'second')
  // One session was created; both turns prompted it. A second `session/new` here would be a split brain.
  expect(peer.recorded('session/new')).toHaveLength(1)
  const prompts = peer.recorded('session/prompt')
  expect(prompts).toHaveLength(2)
  expect(prompts.map(p => p.params.sessionId)).toEqual([sessionId, sessionId])
  expect(prompts[1].params.prompt).toEqual([{ type: 'text', text: 'second' }])
  const messages = client.getSnapshot().messages[sessionId] ?? []
  expect(messages.map(m => m.text).join('\n')).toContain('one')
  expect(messages.map(m => m.text).join('\n')).toContain('two')
  peer.close()
})

it('R6 a native title update replaces the session title without inventing one', async () => {
  const { peer, client } = await connectTarget()
  const { sessionId } = await client.createAndSend!('ws_app', 'text', 'req_1')
  await peer.update(sessionId, { sessionUpdate: 'session_info_update', title: 'Fix the flaky gate' })
  const listed = client.getSnapshot().sessions.find(s => s.id === sessionId)
  expect(listed?.title).toBe('Fix the flaky gate')
  peer.close()
})

it('R7 an unconfirmed first send is never silently re-issued', async () => {
  const { peer, client } = await connectTarget()
  // The link dies after `session/new` but before the first prompt settles.
  peer.queueTurn(async api => { await api.cancelled(); return 'cancelled' })
  const inFlight = client.createAndSend!('ws_app', 'text', 'req_1')
  await peer.waitFor('the first prompt to leave', () => peer.recorded('session/prompt').length === 1)
  peer.drop(new Error('link reset mid-first-send'))
  const failure = await inFlight.then(() => undefined, error => error)
  expect(failure).toBeInstanceOf(Error)
  // Zero automatic retries: re-issuing belongs to the caller holding the request id.
  expect(peer.recorded('session/new')).toHaveLength(1)
  peer.close()
})

/**
 * Round 12, native session names. The traced wire facts: `session/new` carries no title, and the
 * only name authority the connector may consume is `session/list` (measured: the real Pi harness
 * titles sessions from native data there). So a settled turn pulls that native name through the
 * EXISTING capability — no model naming, no summary substitution, and an honest placeholder where
 * the list has no name yet. (The bridge never emits `session_info_update` on the real chain; R6
 * keeps the fake's late-update path honest for a client that already handles it.)
 */

it('R33 a settled turn adopts the native session/list title; a late one arrives, an absent one is never invented', async () => {
  const { peer, client } = await connectTarget({ capabilities: { sessionCapabilities: { list: {} } } })
  const titleOf = (id: string) => client.getSnapshot().sessions.find(s => s.id === id)?.title
  peer.listed = [{ sessionId: 'acp-session-1', cwd: '/repo/app', title: 'Reply with exactly: alpha' }]
  const { sessionId } = await client.createAndSend!('ws_app', 'Reply with exactly: alpha', 'req_1')
  // The name reached the projection through the existing list capability — one automatic pull,
  // no manual refresh and not one model call.
  await peer.waitFor('the native title projected', () => titleOf(sessionId) === 'Reply with exactly: alpha')
  expect(peer.recorded('session/list').length).toBeGreaterThanOrEqual(1)
  // A second session the list has no name for yet keeps its placeholder honestly...
  const second = await client.newSession() // native id acp-session-2
  await client.send(second, 'beta')
  await peer.waitFor("the second turn to settle", () =>
    Object.values(client.getSnapshot().runs).some(r => r.sessionId === second && r.status === 'completed'))
  await peer.waitFor('the second name pull', () => peer.recorded('session/list').length >= 2)
  expect(titleOf(second)).toBe('New session')
  // ...and the name arriving late is picked up by a later settled turn, still without any refresh.
  peer.listed.push({ sessionId: 'acp-session-2', cwd: '/repo/app', title: 'Beta thread' })
  await client.send(second, 'again')
  await peer.waitFor('the late native name projected', () => titleOf(second) === 'Beta thread')
  peer.close()
})

it('R34 a native name survives reload-listing and reopening: no path re-folds it back to a placeholder', async () => {
  const { peer, client } = await connectTarget({ capabilities: { loadSession: true, sessionCapabilities: { list: {} } } })
  peer.listed = [{ sessionId: 's-keep', cwd: '/repo/app', title: 'Quarterly review notes' }]
  await client.openWorkspace!('ws_app')
  // Reload path: the list is the origin of the projection — the native title arrives, unprefabricated.
  await client.refreshSessions()
  expect(client.getSnapshot().sessions.find(s => s.id === 's-keep')?.title).toBe('Quarterly review notes')
  // Reopening the session for a replay must not drop the name it already has.
  await client.openSession('s-keep')
  expect(client.getSnapshot().sessions.find(s => s.id === 's-keep')?.title).toBe('Quarterly review notes')
  expect(client.getSnapshot().selectedSessionId).toBe('s-keep')
  // And a later manual refresh keeps it: the name is stable across every list round-trip.
  await client.refreshSessions()
  expect(client.getSnapshot().sessions.find(s => s.id === 's-keep')?.title).toBe('Quarterly review notes')
  peer.close()
})

it('R35 same native sessionIds on two channels keep two names: each channel titles only its own session', async () => {
  const { client, peerFor, closeAll } = await connectTargetFor({
    capabilities: { sessionCapabilities: { list: {} } },
    projects: { ws_a: '/repo/a', ws_b: '/repo/b' },
  })
  const peerA = peerFor('ws_a'), peerB = peerFor('ws_b')
  peerA.listed = [{ sessionId: 'acp-session-1', cwd: '/repo/a', title: 'Name on A' }]
  peerB.listed = [{ sessionId: 'acp-session-1', cwd: '/repo/b', title: 'Name on B' }]
  const { sessionId: idA } = await client.createAndSend!('ws_a', 'work in A', 'req_a')
  await client.openWorkspace!('ws_b')
  const { sessionId: idB } = await client.createAndSend!('ws_b', 'work in B', 'req_b')
  try {
    expect(idA).not.toBe(idB) // one native id, two distinct keys
    // Each pull goes out on its own channel and lands only on its own session.
    await peerA.waitFor("A's native title projected", () =>
      client.getSnapshot().sessions.find(s => s.id === idA)?.title === 'Name on A')
    expect(client.getSnapshot().sessions.find(s => s.id === idB)?.title).not.toBe('Name on A')
    await peerB.waitFor("B's native title projected", () =>
      client.getSnapshot().sessions.find(s => s.id === idB)?.title === 'Name on B')
    // A late out-of-band rename on the shared native id moves A only. (The listed record moves
    // with it, so a background name pull can never race the out-of-band rename back.)
    peerA.listed[0] = { ...peerA.listed[0]!, title: 'Renamed on A' }
    await peerA.update('acp-session-1', { sessionUpdate: 'session_info_update', title: 'Renamed on A' })
    expect(client.getSnapshot().sessions.find(s => s.id === idA)?.title).toBe('Renamed on A')
    expect(client.getSnapshot().sessions.find(s => s.id === idB)?.title).toBe('Name on B')
    // The merged list keeps both apart, each under its own channel's authority.
    await client.refreshSessions()
    const state = client.getSnapshot()
    expect(state.sessions.find(s => s.id === idA)?.title).toBe('Renamed on A')
    expect(state.sessions.find(s => s.id === idB)?.title).toBe('Name on B')
  } finally {
    client.dispose()
    await closeAll()
  }
})

it('R38 a stale list response never reverts a newer name: last WRITE WINS by issue order, not arrival', async () => {
  const { peer, client } = await connectTarget({ capabilities: { sessionCapabilities: { list: {} } } })
  const titleOf = (id: string) => client.getSnapshot().sessions.find(s => s.id === id)?.title
  const gate = deferred()
  peer.listed = [{ sessionId: 'acp-session-1', cwd: '/repo/app', title: 'Old native name' }]
  peer.listHold = gate.promise
  const { sessionId } = await client.createAndSend!('ws_app', 'first', 'req_1')
  // Turn one's name pull is out on the wire and hangs: its answer is about to become history.
  await peer.waitFor('the name pull on the wire', () => peer.recorded('session/list').length >= 1)
  await peer.update(sessionId, { sessionUpdate: 'session_info_update', title: 'Renamed meanwhile' })
  expect(titleOf(sessionId)).toBe('Renamed meanwhile')
  gate.resolve() // now the stale list answer — still carrying the OLD title — comes back
  // Drain the wire: a stale commit can only land within the next few stream turns, never later.
  const deadline = Date.now() + 150
  while (Date.now() < deadline && titleOf(sessionId) === 'Renamed meanwhile')
    await new Promise(resolve => setTimeout(resolve, 5))
  expect(titleOf(sessionId), 'a stale list response reverted the newer name').toBe('Renamed meanwhile')
  // The newer-pull direction still works: a later settled turn lands the then-current native title.
  peer.listed = [{ sessionId: 'acp-session-1', cwd: '/repo/app', title: 'Newest native name' }]
  await client.send(sessionId, 'again')
  await peer.waitFor('the newer native title projected', () => titleOf(sessionId) === 'Newest native name')
  peer.close()
})

/**
 * Round 14: the manual refresh must obey the SAME name rule as the background pull — claim the
 * sequence when the request is ISSUED, check it when the answer lands. A refresh response is
 * never a wholesale list overwrite that can roll a newer name back.
 */

it('R39 a refresh that answers after a live rename cannot revert the newer name', async () => {
  const { peer, client } = await connectTarget({ capabilities: { sessionCapabilities: { list: {} } } })
  const gate = deferred()
  peer.listed = [{ sessionId: 's-renamed', cwd: '/repo/app', title: 'Old list title' }]
  await client.openWorkspace!('ws_app')
  peer.listHold = gate.promise
  const refreshing = client.refreshSessions()
  await peer.waitFor('the refresh list request on the wire', () => peer.recorded('session/list').length === 1)
  // The fresh name arrives while the list answer is still in flight.
  await peer.update('s-renamed', { sessionUpdate: 'session_info_update', title: 'Fresh native rename' })
  expect(client.getSnapshot().sessions.find(s => s.id === 's-renamed')?.title).toBe('Fresh native rename')
  gate.resolve() // now the stale list answer — carrying the OLD title — lands
  await refreshing
  expect(client.getSnapshot().sessions.find(s => s.id === 's-renamed')?.title).toBe('Fresh native rename')
  peer.close()
})

it('R40 two refreshes answered out of order: the later-issued one wins, the stale one lands nothing', async () => {
  const { peer, client } = await connectTarget({ capabilities: { sessionCapabilities: { list: {} } } })
  const gate = deferred()
  peer.listed = [{ sessionId: 's-order', cwd: '/repo/app', title: 'Round one title' }]
  await client.openWorkspace!('ws_app')
  peer.listHold = gate.promise
  const first = client.refreshSessions()
  await peer.waitFor('the first refresh on the wire', () => peer.recorded('session/list').length === 1)
  // The second refresh is issued after — same channel, fresh data, and it answers FIRST.
  peer.listHold = undefined
  peer.listed = [{ sessionId: 's-order', cwd: '/repo/app', title: 'Round two title' }]
  const second = client.refreshSessions()
  await peer.waitFor('the second refresh on the wire', () => peer.recorded('session/list').length === 2)
  await second
  expect(client.getSnapshot().sessions.find(s => s.id === 's-order')?.title).toBe('Round two title')
  gate.resolve() // the first, now-stale answer lands last
  await first
  expect(client.getSnapshot().sessions.find(s => s.id === 's-order')?.title).toBe('Round two title')
  peer.close()
})

/**
 * A single-project seam whose `release()` only records — the wire survives being stood down, so a
 * retry after a failed handshake genuinely re-handshakes against a fresh peer (the default fixture
 * closes the whole peer on release, which would hide exactly the retry behavior under test; one
 * stream also cannot host a second SDK connection — the readable stays locked by the first).
 * `failFirstInitialize` arms the first peer to refuse initialize once; `holdInitializeAnswer`
 * parks the peer→client direction so that peer's initialize stays mid-flight.
 */
async function reconnectable(options: { holdInitializeAnswer?: boolean; failFirstInitialize?: boolean } = {}) {
  const target = await loadAcpTarget()
  const peers: HarnessPeer[] = []
  let openGate!: () => void
  const gate = new Promise<void>(resolve => { openGate = resolve })
  const acquired: string[] = [], released: string[] = []
  const spec = {
    serverInstanceId: 'https://harness.test|retry',
    harness: { id: 'pi', title: 'PI Harness' },
    listProjects: async () => [{ id: 'ws_r', normalizedPath: '/repo/r' }],
    openProject: async (id: string) => {
      if (id !== 'ws_r') throw new Error(`project-invalid: ${id}`)
      return { id, normalizedPath: '/repo/r' }
    },
    acquireChannel: async (id: string): Promise<AcpChannelHandle> => {
      acquired.push(id)
      const peer = new HarnessPeer()
      peers.push(peer)
      if (peers.length === 1 && options.failFirstInitialize)
        peer.armFailure('initialize', new RequestError(-32603, 'initialize boom'))
      let stream: acp.Stream = peer.stream
      if (options.holdInitializeAnswer) {
        const through = new TransformStream<acp.AnyMessage, acp.AnyMessage>({
          transform: async (chunk, controller) => { await gate; controller.enqueue(chunk) },
        })
        peer.stream.readable.pipeTo(through.writable).catch(() => undefined)
        stream = { readable: through.readable, writable: peer.stream.writable }
      }
      const connectionId = `chan_${acquired.length}`
      return {
        connectionId, binding: { id, normalizedPath: '/repo/r' }, stream,
        release: async () => { released.push(connectionId) },
      }
    },
  }
  const client = await target.createConnector(spec).connect()
  return { peers, client, acquired, released, openIncoming: () => openGate() }
}

async function firstPeer(peers: HarnessPeer[], timeoutMs = 2_000): Promise<HarnessPeer> {
  const deadline = Date.now() + timeoutMs
  while (!peers.length) {
    if (Date.now() > deadline) throw new Error('timed out waiting for the seam to wire a peer')
    await new Promise(resolve => setTimeout(resolve, 1))
  }
  return peers[0]
}

it('a failed initialize releases its channel and never pins the retry', async () => {
  // Counterexample for the opening-map race: a failed opening promise left in the map would hand
  // every later attempt the same stale rejection, so the project could never recover.
  const { peers, client, acquired, released } = await reconnectable({ failFirstInitialize: true })
  await expect(client.openWorkspace!('ws_r')).rejects.toBeInstanceOf(Error)
  const first = await firstPeer(peers)
  // The half-open channel's handle is stood down...
  expect(released).toEqual(['chan_1'])
  expect(first.recorded('initialize')).toHaveLength(1)
  // ...and a retry re-handshakes on a fresh channel instead of repeating the old failure.
  await client.openWorkspace!('ws_r')
  expect(acquired).toEqual(['ws_r', 'ws_r'])
  expect(peers).toHaveLength(2)
  expect(peers[1].recorded('initialize')).toHaveLength(1)
  const { sessionId } = await client.createAndSend!('ws_r', 'go', 'req_1')
  expect(peers[1].recorded('session/prompt')).toHaveLength(1)
  expect(client.getSnapshot().sessions.some(s => s.id === sessionId)).toBe(true)
  client.dispose()
  expect(released).toEqual(['chan_1', 'chan_2'])
  for (const peer of peers) peer.close()
})

it('dispose while initialize is still landing releases the late handle exactly once and registers no channel', async () => {
  // Counterexample for the acquire/dispose race: the handle is not in `channels` yet when dispose
  // runs, so a dispose that only walks registered channels leaves this channel permanently live.
  const { peers, client, released, openIncoming } = await reconnectable({ holdInitializeAnswer: true })
  const opening = client.openWorkspace!('ws_r')
  const first = await firstPeer(peers)
  await first.waitFor('the initialize request on the wire', () => first.recorded('initialize').length === 1)
  client.dispose()
  // dispose owns the still-unregistered handle: released the moment disposal runs, not on some
  // later courtesy of the handshake noticing.
  expect(released).toEqual(['chan_1'])
  openIncoming()
  expect(await opening.then(() => undefined, error => error)).toBeInstanceOf(Error)
  // Exactly one release ever: the failing attempt and dispose must not both stand it down.
  expect(released).toEqual(['chan_1'])
  // No ghost channel survived the race, and the client stays closed.
  await expect(client.openWorkspace!('ws_r')).rejects.toThrow('disposed')
  first.close()
})
