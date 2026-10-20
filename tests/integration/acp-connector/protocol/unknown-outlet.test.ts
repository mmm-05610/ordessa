import { expect, it } from 'vitest'
import type * as acp from '@agentclientprotocol/sdk'
import { loadAcpTarget } from '../fixtures/target-seam'
import type { AcpChannelHandle, AcpChannelSpec } from '../fixtures/target-seam'
import { HarnessPeer, deferred } from '../fixtures/acp-peer'

/**
 * T009-01: the E2 generic outlet closes the registered SDK-drop drift.
 *
 * The pinned `@agentclientprotocol/sdk` drops unknown `sessionUpdate` kinds
 * at deserialization ("Invalid params") — below the product. The connector's
 * raw tap (pre-destructive-filter) now records a RAW-SAFE SUMMARY into a
 * bounded generic outlet: no payload bodies, no verdict, no approval
 * interpretation, and the session snapshot still carries no trace of the
 * unknown payload (the no-leak assertions in
 * `unknown-event-passthrough.test.ts` remain true by construction).
 *
 * Bounded capture merges on overflow to one scope-unknown summary with a
 * gap marker — obligations are never dropped, bodies are (E2/V3-7).
 */
const binding = { id: 'ws_app', normalizedPath: '/repo/app' }

async function connectControlled(capabilities: acp.AgentCapabilities = {}) {
  const target = await loadAcpTarget()
  const peer = new HarnessPeer({ capabilities })
  const released: string[] = []
  const handle: AcpChannelHandle = {
    connectionId: 'chan_t901',
    binding,
    stream: peer.stream,
    subscribeDown: () => () => undefined,
    release: async () => { released.push(handle.connectionId); peer.close() },
  }
  const spec: AcpChannelSpec = {
    serverInstanceId: 'https://harness.test|server_1',
    harness: { id: 'pi', title: 'PI Harness' },
    listProjects: async () => [binding],
    openProject: async id => {
      if (id !== binding.id) throw new Error(`project-invalid: ${id}`)
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
  payload: { secretBody: 'never-leaves-the-tap' },
} as unknown as acp.SessionUpdate

it('T009-01: unknown frames reach the generic outlet as raw-safe summaries, no verdict', async () => {
  const { client, peer } = await connectControlled()
  try {
    await client.openWorkspace!('ws_app')
    const key = await client.newSession()
    const gate = deferred()
    peer.queueTurn(async api => {
      await api.update(unknownUpdate)
      await gate.promise
      return 'end_turn'
    })
    const sending = client.send(key, 'hello')
    await peer.waitFor('the native prompt', () => peer.recorded('session/prompt').length === 1)
    await new Promise(resolve => setTimeout(resolve, 50))

    const outlet = (client as unknown as {
      unknownDeliveries(id: string): {
        deliveries: Array<{ updateKind: string; sessionId?: string; frameDigest: string }>
        scopeUnknown: boolean
        gap: boolean
      } | undefined
    }).unknownDeliveries('chan_t901')
    expect(outlet).toBeDefined()
    expect(outlet!.deliveries).toHaveLength(1)
    const entry = outlet!.deliveries[0]
    expect(entry.updateKind).toBe('vendor_extension_update')
    expect(entry.frameDigest).toMatch(/^f[0-9a-f]+:\d+$/)
    // raw-safe: the payload body NEVER crosses the tap
    expect(JSON.stringify(outlet)).not.toContain('never-leaves-the-tap')
    // no verdict state anywhere in the outlet
    expect(JSON.stringify(outlet)).not.toMatch(/approval|verdict|terminal/)
    // the session snapshot stays clean of the unknown payload
    expect(JSON.stringify(client.getSnapshot())).not.toContain('vendor_extension_update')
    // the pre-filter reaction stays bounded: command knowledge reads malformed
    expect(client.getNativeCommands!(key)).toEqual({ kind: 'unknown', reason: 'malformed' })

    gate.resolve()
    await sending
  } finally { peer.close() }
})

it('T009-01: overflow merges to one scope-unknown summary with a gap marker', async () => {
  const { client, peer } = await connectControlled()
  try {
    await client.openWorkspace!('ws_app')
    const key = await client.newSession()
    const gate = deferred()
    peer.queueTurn(async api => {
      for (let i = 0; i < 20; i++) {
        await api.update({ sessionUpdate: `vendor_kind_${i}` } as unknown as acp.SessionUpdate)
      }
      await gate.promise
      return 'end_turn'
    })
    const sending = client.send(key, 'hello')
    await peer.waitFor('the native prompt', () => peer.recorded('session/prompt').length === 1)
    await new Promise(resolve => setTimeout(resolve, 50))

    const outlet = (client as unknown as {
      unknownDeliveries(id: string): {
        deliveries: Array<{ updateKind: string }>
        scopeUnknown: boolean
        gap: boolean
      } | undefined
    }).unknownDeliveries('chan_t901')
    expect(outlet!.deliveries).toHaveLength(1) // merged into one summary
    expect(outlet!.deliveries[0].updateKind).toBe('scope-unknown')
    expect(outlet!.scopeUnknown).toBe(true)
    expect(outlet!.gap).toBe(true) // the obligation survives as a gap marker

    gate.resolve()
    await sending
  } finally { peer.close() }
})

it('T009-01: known update kinds never pollute the outlet', async () => {
  const { client, peer } = await connectControlled()
  try {
    await client.openWorkspace!('ws_app')
    const key = await client.newSession()
    const gate = deferred()
    peer.queueTurn(async api => {
      await api.update({
        sessionUpdate: 'agent_message_chunk',
        content: { type: 'text', text: 'known' },
      } as unknown as acp.SessionUpdate)
      await gate.promise
      return 'end_turn'
    })
    const sending = client.send(key, 'hello')
    await peer.waitFor('the native prompt', () => peer.recorded('session/prompt').length === 1)
    await new Promise(resolve => setTimeout(resolve, 50))

    const outlet = (client as unknown as {
      unknownDeliveries(id: string): { deliveries: unknown[] } | undefined
    }).unknownDeliveries('chan_t901')
    expect(outlet!.deliveries).toEqual([]) // known kinds: zero outlet entries
    // and the known content still projects through the normal surface
    expect(JSON.stringify(client.getSnapshot())).toContain('known')

    gate.resolve()
    await sending
  } finally { peer.close() }
})
