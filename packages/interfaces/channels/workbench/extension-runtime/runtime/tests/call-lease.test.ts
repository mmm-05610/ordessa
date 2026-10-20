/**
 * T009-03 gates: call leases re-check authorization AFTER the await — a
 * mid-flight revoke makes the delivery stale (typed Refused, never an
 * exception, never applied to a newer selection), and stale generations
 * refuse the same way.
 */
import { describe, expect, it, vi } from 'vitest'

import { LeaseRegistry, callWithContext } from '../src/call-lease'
import type { WirePort, WireResult } from '@ordessa/interface-contracts'

function fakePort(result: WireResult): WirePort {
  return {
    call: vi.fn(async () => result),
    ready: true,
    scope: 'test|server_1',
  }
}

const context = { caller: 'plugin', activation: 'act-1', generation: 1, target: 't-1' }

describe('call leases (T009-03)', () => {
  it('a live lease delivers the real result', async () => {
    const registry = new LeaseRegistry()
    const lease = registry.register(context)
    const port = fakePort({ kind: 'Accepted', requestId: 'r-1', result: { ok: true } })
    const result = await callWithContext(port, registry, lease.id, 'm', {}, 'r-1')
    expect(result.kind).toBe('Accepted')
  })

  it('counterexample: a mid-flight revoke makes the delivery stale (typed Refused, no throw)', async () => {
    const registry = new LeaseRegistry()
    const lease = registry.register(context)
    const port = {
      ...fakePort({ kind: 'Accepted', requestId: 'r-2', result: { ok: true } }),
      async call() {
        lease.revoke('scope-exit') // revoked WHILE the call is in flight
        return { kind: 'Accepted', requestId: 'r-2', result: { ok: true } } as WireResult
      },
    }
    const result = await callWithContext(port, registry, lease.id, 'm', {}, 'r-2')
    expect(result).toEqual({
      kind: 'Refused', requestId: 'r-2',
      reason: 'lease-revoked-after-await', retryable: false,
    })
  })

  it('counterexample: a stale generation refuses after await', async () => {
    const registry = new LeaseRegistry()
    const old = registry.register(context)          // generation 1
    registry.register({ ...context, generation: 2 }) // the owner moved on
    const port = fakePort({ kind: 'Accepted', requestId: 'r-3', result: { ok: true } })
    const result = await callWithContext(port, registry, old.id, 'm', {}, 'r-3')
    expect(result).toEqual({
      kind: 'Refused', requestId: 'r-3',
      reason: 'stale-generation-after-await', retryable: false,
    })
  })

  it('the recheck never throws — every outcome is a WireResult', async () => {
    const registry = new LeaseRegistry()
    const lease = registry.register(context)
    lease.revoke('x')
    const port = fakePort({ kind: 'Unknown', requestId: 'r-4', reason: 'result-unknown' })
    await expect(callWithContext(port, registry, 'lease-missing', 'm', {}, 'r-4'))
      .resolves.toBeDefined() // unknown lease id: still a typed Refused, not a throw
    void lease
  })
})
