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
  it('maps actual server facet items and preview sources without rewriting saved values', async () => {
    const value = { harnessId: 'pi', providerConfigId: 'p', modelId: 'm' }
    const wire: WirePort = { ready: true, scope: 'local', async call(method) {
      const data = method.endsWith('describeFacets') ? [{ facetId: 'model', items: [{ itemId: 'choice', valueSchema: { type: 'object' } }] }]
        : { profileId: 'p', harnessId: 'pi', revision: 2, items: [{ facetId: 'model', itemId: 'choice', value, source: 'profile', revision: 2 }] }
      return { kind: 'Accepted', requestId: 'x', result: { data } }
    } }
    const client = createWireClient(wire)
    expect((await client.describeFacets('pi'))[0]?.itemDescriptors[0]?.itemId).toBe('choice')
    const preview = await client.resolvePreview('p')
    expect(preview.items[0]).toEqual({ facetId: 'model', itemId: 'choice', value, source: { kind: 'profile', revision: 2 }, state: 'explicit', revision: 2 })
  })
  it('does not promote a malformed preview into editable data', async () => {
    const wire: WirePort = { ready: true, scope: 'local', async call() {
      return { kind: 'Accepted', requestId: 'x', result: { data: { items: [{ source: 'invented', revision: 1 }] } } }
    } }
    await expect(createWireClient(wire).resolvePreview('p')).rejects.toThrow('malformed item source')
  })
})
