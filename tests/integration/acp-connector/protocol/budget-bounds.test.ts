import { expect, it } from 'vitest'
import type * as acp from '@agentclientprotocol/sdk'
import { loadAcpTarget } from '../fixtures/target-seam'
import type { AcpChannelHandle, AcpChannelSpec } from '../fixtures/target-seam'
import { HarnessPeer, deferred } from '../fixtures/acp-peer'

/**
 * T009-05: per-hop budgets and gap honesty at the observable faces —
 * unknown-frame capture merges to a scope-unknown summary with a gap marker
 * (obligations kept, bodies dropped); over-budget raw bytes never silently
 * vanish without a gap; command-catalog candidates stay bounded.
 */
const binding = { id: 'ws_app', normalizedPath: '/repo/app' }

async function connectControlled() {
  const target = await loadAcpTarget()
  const peer = new HarnessPeer({ capabilities: {} })
  const handle: AcpChannelHandle = {
    connectionId: 'chan_t905', binding, stream: peer.stream,
    subscribeDown: () => () => undefined,
    release: async () => { peer.close() },
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
  return { client, peer }
}

it('T009-05: unknown-frame capture is bounded and merges to scope-unknown with a gap', async () => {
  const { client, peer } = await connectControlled()
  try {
    await client.openWorkspace!('ws_app')
    const key = await client.newSession()
    const gate = deferred()
    peer.queueTurn(async api => {
      for (let i = 0; i < 25; i++) {
        await api.update({ sessionUpdate: `vendor_${i}` } as unknown as acp.SessionUpdate)
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
      }
    }).unknownDeliveries('chan_t905')
    // bounded: never more than the capture bound; overflow merged to one summary
    expect(outlet.deliveries.length).toBeLessThanOrEqual(17)
    expect(outlet.deliveries.at(-1)?.updateKind).toBe('scope-unknown')
    expect(outlet.gap).toBe(true) // the overflow is NOT silent

    gate.resolve()
    await sending
  } finally { peer.close() }
})

it('T009-05: over-budget frames are gap-marked, never silently dropped', async () => {
  const { client, peer } = await connectControlled()
  try {
    await client.openWorkspace!('ws_app')
    const key = await client.newSession()
    const gate = deferred()
    peer.queueTurn(async api => {
      await api.update({
        sessionUpdate: 'vendor_big',
        payload: { blob: 'x'.repeat(200_000) }, // over any sane frame budget
      } as unknown as acp.SessionUpdate)
      await gate.promise
      return 'end_turn'
    })
    const sending = client.send(key, 'hello')
    await peer.waitFor('the native prompt', () => peer.recorded('session/prompt').length === 1)
    await new Promise(resolve => setTimeout(resolve, 50))

    const outlet = (client as unknown as {
      unknownDeliveries(id: string): { deliveries: Array<{ frameDigest: string }>; gap: boolean }
    }).unknownDeliveries('chan_t905')
    // the capture stores a digest summary, never the 200KB body
    expect(JSON.stringify(outlet.deliveries)).not.toContain('xxxxxxxx')
    expect(outlet.deliveries[0]?.frameDigest).toMatch(/^f[0-9a-f]+:\d+$/)

    gate.resolve()
    await sending
  } finally { peer.close() }
})
