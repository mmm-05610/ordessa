import { describe, expect, it } from 'vitest'
import type { WirePort } from '@extensions/ordessa.contracts/contract.js'
import { createWireClient } from '../src/wire-client'

describe('Profile wire adapter', () => {
  it('calls the real namespace and removes undefined optional params', async () => {
    const calls: unknown[] = []
    const wire: WirePort = { ready: true, scope: 'local', async call(method, params) {
      calls.push([method, params]); return { kind: 'Accepted', requestId: 'x', result: { data: [] } }
    } }
    expect(await createWireClient(wire).listProfiles(undefined, false)).toEqual([])
    expect(calls).toEqual([['profiles.v2.listProfiles', { includeArchived: false }]])
  })
  it('keeps uncertain outcomes distinct from refusals, without retry', async () => {
    let count = 0
    const wire: WirePort = { ready: true, scope: 'local', async call() {
      ++count; return { kind: 'Unknown', requestId: 'x', reason: 'connection-lost' }
    } }
    await expect(createWireClient(wire).getProfile('p')).rejects.toThrow('Profile Unknown')
    expect(count).toBe(1)
  })
})
