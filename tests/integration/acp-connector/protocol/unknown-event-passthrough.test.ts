import { expect, it } from 'vitest'
import type * as acp from '@agentclientprotocol/sdk'
import { loadAcpTarget } from '../fixtures/target-seam'
import type { AcpChannelHandle, AcpChannelSpec } from '../fixtures/target-seam'
import { HarnessPeer, deferred } from '../fixtures/acp-peer'

/**
 * T007-06 verification half at the real Desktop connector seam.
 *
 * The controlled Harness peer is the SDK-based fixture over the pinned
 * `@agentclientprotocol/sdk` (fixtures/acp-peer.ts), so every frame crosses the
 * actual wire codec the product uses — nothing is re-fed around the SDK.
 *
 * What the pinned chain actually does today, and what this file pins:
 *
 *  * an unknown `sessionUpdate` kind is dropped by the SDK deserializer before
 *    `ClientSideConnection` can hand it to the product (`Error handling
 *    notification … Invalid params`); the connector's raw-frame tap sees it
 *    first and only degrades the native command catalog of that channel to
 *    `{kind: 'unknown', reason: 'malformed'}` — no crash, no approval, no run
 *    verdict;
 *  * because that drop happens below the product, the unknown payload never
 *    reaches any surface outlet: the snapshot carries no trace of it.  This is
 *    the REGISTERED DRIFT against lifecycle-evidence.md §SDK真实穿透与样例
 *    ("原协议解码会丢未知type时，在破坏性过滤前保通用出口") — the pre-filter
 *    tap exists but has no generic outlet yet;
 *  * a non-standard native command (`/workflow`) is not filtered by any core
 *    whitelist: the peer's `available_commands_update` catalog is projected
 *    as-is, and the command text is carried to the native session verbatim.
 *
 * No real model, no credential, no user data: the peer is the in-process
 * controlled fixture and the connector is the production module.
 */

const binding = { id: 'ws_app', normalizedPath: '/repo/app' }

async function connectControlled(capabilities: acp.AgentCapabilities = {}) {
  const target = await loadAcpTarget()
  const peer = new HarnessPeer({ capabilities })
  const released: string[] = []
  const handle: AcpChannelHandle = {
    connectionId: 'chan_t706',
    binding,
    stream: peer.stream,
    // The production host supplies the terminal-fact subscription; the client
    // refuses to publish any command catalog without it.
    subscribeDown: () => () => undefined,
    release: async () => { released.push(handle.connectionId); peer.close() },
  }
  const spec: AcpChannelSpec = {
    serverInstanceId: 'https://harness.test|server_1',
    harness: { id: 'pi', title: 'PI Harness' },
    listProjects: async () => [binding],
    openProject: async id => {
      if (id !== binding.id) throw new Error(`project-invalid: ${id} is not offered by this Server`)
      return binding
    },
    acquireChannel: async () => handle,
  }
  const connector = target.createConnector(spec)
  const client = await connector.connect()
  return { client, peer, released }
}

const unknownUpdate = {
  sessionUpdate: 'vendor_extension_update',
  payload: { keep: 'me' },
} as unknown as acp.SessionUpdate

it('T007-06: an unknown sessionUpdate is no verdict, no approval, no resend, and no surface leak', async () => {
  const { client, peer } = await connectControlled()
  try {
    await client.openWorkspace!('ws_app')
    const key = await client.newSession()

    // The unknown event arrives mid-turn; the turn must settle only from the
    // native stopReason, never from the unknown payload.
    const gate = deferred()
    peer.queueTurn(async api => {
      await api.update(unknownUpdate)
      await gate.promise
      return 'end_turn'
    })
    const sending = client.send(key, 'hello')
    await peer.waitFor('the native prompt', () => peer.recorded('session/prompt').length === 1)
    await new Promise(resolve => setTimeout(resolve, 50))

    const runs = Object.values(client.getSnapshot().runs)
    expect(runs.find(run => run.sessionId === key)?.status).toBe('running')
    // Never projected as an approval/interaction out of unknown wire data.
    expect(client.getSnapshot().interactions).toEqual([])
    // No ack exists for a notification; none is invented and nothing is re-sent.
    expect(peer.recorded('session/prompt')).toHaveLength(1)
    // The SDK drops the unknown kind below the product, so no generic outlet
    // carries its payload yet (registered drift).
    const surfaced = JSON.stringify(client.getSnapshot())
    expect(surfaced).not.toContain('vendor_extension_update')
    expect(surfaced).not.toContain('keep')
    // The pre-filter tap's only reaction is bounded: the channel's command
    // knowledge reads as malformed, never as a fake catalog.
    expect(client.getNativeCommands!(key)).toEqual({ kind: 'unknown', reason: 'malformed' })

    gate.resolve()
    await sending
    await peer.waitFor('the native stopReason verdict',
      () => Object.values(client.getSnapshot().runs).find(run => run.sessionId === key)?.status === 'completed')
    expect(client.getNativeCommands!(key)).toEqual({ kind: 'unknown', reason: 'malformed' })
  } finally { peer.close() }
})

it('T007-06/R03: a non-standard /workflow command keeps the native catalog and reaches the native session verbatim', async () => {
  const { client, peer } = await connectControlled()
  try {
    await client.openWorkspace!('ws_app')
    const key = await client.newSession()
    const nativeId = client.getSnapshot().sessions.find(session => session.id === key)?.id
    expect(nativeId).toBe('acp-session-1')

    // The peer's own catalog is data; the product may not enumerate/whitelist it.
    await peer.update(nativeId!, {
      sessionUpdate: 'available_commands_update',
      availableCommands: [
        { name: '/workflow', description: 'Run the native workflow', input: { hint: 'name' } },
        { name: 'vendor:custom', description: 'Non-core name' },
      ],
    } as acp.SessionUpdate)
    await peer.waitFor('native catalog projection',
      () => client.getNativeCommands!(key).kind === 'available')
    const catalog = client.getNativeCommands!(key)
    expect(catalog).toEqual({
      kind: 'available', connectionId: 'chan_t706', nativeSessionId: 'acp-session-1',
      commands: [
        { name: '/workflow', description: 'Run the native workflow', inputHint: 'name' },
        { name: 'vendor:custom', description: 'Non-core name' },
      ],
    })

    // Invocation rides the same native channel: the command text is prompt
    // content, carried as written (no core command API in this path).
    await client.send(key, '/workflow ship-it --dry-run')
    expect(peer.recorded('session/prompt')[0].params).toMatchObject({
      sessionId: 'acp-session-1',
      prompt: [{ type: 'text', text: '/workflow ship-it --dry-run' }],
    })
    expect(peer.recorded('session/prompt')).toHaveLength(1)
    expect(Object.values(client.getSnapshot().runs).map(run => run.status)).toEqual(['completed'])
  } finally { client.dispose(); peer.close() }
})

it('T007-06: an unknown event with no snapshot subscriber neither crashes nor mutates the surface', async () => {
  const { client, peer } = await connectControlled()
  try {
    await client.openWorkspace!('ws_app')
    const key = await client.newSession()
    // Deliberately no client.subscribe(): a missing consumer is not an error.
    for (let index = 0; index < 16; index += 1) {
      await peer.update('acp-session-1', unknownUpdate)
    }
    await peer.waitFor('the pre-filter tap reaction',
      () => client.getNativeCommands!(key).kind === 'unknown')
    const snapshot = client.getSnapshot()
    expect(snapshot.interactions).toEqual([])
    expect(Object.keys(snapshot.runs)).toEqual([])
    expect(snapshot.sessions.map(session => session.id)).toEqual([key])
    expect(client.getNativeCommands!(key)).toEqual({ kind: 'unknown', reason: 'malformed' })
  } finally { peer.close() }
})
