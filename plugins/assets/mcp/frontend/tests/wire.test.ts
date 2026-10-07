// The fetch McpWireClient speaks the server's wire/1 envelope exactly:
// POST {base}/wire/v1/{method} with {jsonrpc:"2.0",id,method,params}
// (apps/server wire/envelope.py) and reads back one of result|error.

import { describe, expect, it } from 'vitest'
import { createFetchMcpWireClient, createWirePortMcpWireClient, McpWireError } from '../src/wire'

const identity = { serverScope: 'scope', principal: 'user' }

interface Recorded { url: string; init: RequestInit }

function jsonFetch(body: unknown, record: Recorded[], status = 200) {
  return async (url: string, init: RequestInit) => {
    record.push({ url, init })
    return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } })
  }
}

describe('createFetchMcpWireClient', () => {
  it('posts the wire/1 envelope to /wire/v1/mcp.<method> and returns the result', async () => {
    const record: Recorded[] = []
    const client = createFetchMcpWireClient({ identity,
      baseUrl: 'http://127.0.0.1:41207/',
      fetchImpl: jsonFetch({ jsonrpc: '2.0', id: 1, result: { definitions: [{ definitionId: 'a', nativeName: 'a' }] } }, record),
    })
    const rows = await client.listDefinitions()
    expect(rows).toEqual([{ definitionId: 'a', nativeName: 'a' }])
    expect(record[0].url).toBe('http://127.0.0.1:41207/wire/v1/mcp.list')
    expect(record[0].init.method).toBe('POST')
    const body = JSON.parse(String(record[0].init.body))
    expect(body).toMatchObject({ jsonrpc: '2.0', method: 'mcp.list', params: identity })
    expect(typeof body.id).toBe('number')
  })

  it('passes camelCase params through untouched and merges owner headers', async () => {
    const record: Recorded[] = []
    const client = createFetchMcpWireClient({ identity,
      baseUrl: 'http://127.0.0.1:1',
      fetchImpl: jsonFetch({ jsonrpc: '2.0', id: 1, result: { definitionId: 'a', revision: 3, approval: { actor: 'user', approvedAt: 'now' } } }, record),
      headers: () => ({ authorization: 'Bearer token-under-owner-control' }),
    })
    await expect(client.approveRevision({ definitionId: 'a', revision: 3 }))
      .resolves.toEqual({ definitionId: 'a', revision: 3, approval: { actor: 'user', approvedAt: 'now' } })
    expect(JSON.parse(String(record[0].init.body)).params).toEqual({ ...identity, definitionId: 'a', revision: 3 })
    expect((record[0].init.headers as Record<string, string>).authorization).toBe('Bearer token-under-owner-control')
    expect((record[0].init.headers as Record<string, string>)['content-type']).toBe('application/json')
  })

  it('maps a typed wire error body to McpWireError with the business code', async () => {
    const client = createFetchMcpWireClient({ identity,
      baseUrl: 'http://127.0.0.1:1',
      fetchImpl: jsonFetch({ jsonrpc: '2.0', id: 1, error: { code: 'PROBE_TIMEOUT', message: 'handshake timed out' } }, []),
    })
    await expect(client.probe({ definitionId: 'a', revision: 1 })).rejects.toMatchObject({ code: 'PROBE_TIMEOUT', message: 'handshake timed out' })
  })

  it('refuses malformed envelopes instead of guessing success', async () => {
    const noMembers = createFetchMcpWireClient({ identity, baseUrl: 'http://x', fetchImpl: jsonFetch({ jsonrpc: '2.0', id: 1 }, []) })
    await expect(noMembers.listDefinitions()).rejects.toBeInstanceOf(McpWireError)
    const notJson = createFetchMcpWireClient({ identity,
      baseUrl: 'http://x',
      fetchImpl: async () => new Response('<html>', { status: 502 }),
    })
    await expect(notJson.listDefinitions()).rejects.toMatchObject({ code: 'WIRE_BAD_RESPONSE' })
  })
})

describe('createWirePortMcpWireClient (EA-1: the product route rides the C-03 port)', () => {
  const identity = { serverScope: 'http://127.0.0.1:41207|server_fake', principal: 'desktop-local' }

  function portFake(answer: (method: string, params: Record<string, unknown>) => import('@extensions/ordessa.contracts/contract.js').WireResult) {
    const calls: { method: string; params: Record<string, unknown> }[] = []
    return {
      calls,
      ready: true,
      scope: identity.serverScope,
      async call(method: string, params: Readonly<Record<string, unknown>>) {
        calls.push({ method, params: { ...params } })
        return answer(method, { ...params })
      },
    }
  }

  it('sends identity-injected params through port.call and unwraps the Accepted result path', async () => {
    const wire = portFake(() => ({
      kind: 'Accepted', requestId: 'r1',
      result: { definitions: [{ definitionId: 'a', nativeName: 'a' }] },
    }))
    const client = createWirePortMcpWireClient(wire as never, identity)
    const rows = await client.listDefinitions()
    expect(rows).toEqual([{ definitionId: 'a', nativeName: 'a' }])
    // One row per operation, the registered short id, identity injected.
    expect(wire.calls).toEqual([
      { method: 'mcp.list', params: { serverScope: identity.serverScope, principal: identity.principal } },
    ])
  })

  it('maps Refused and Unknown to the typed error carrying the server reason', async () => {
    const refused = createWirePortMcpWireClient(portFake(() => ({
      kind: 'Refused', requestId: 'r2', reason: 'handshake timed out', retryable: true,
    })) as never, identity)
    await expect(refused.probe({ definitionId: 'a', revision: 1 }))
      .rejects.toMatchObject({ code: 'WIRE_ERROR', message: 'mcp.probe Refused: handshake timed out' })
    const unknown = createWirePortMcpWireClient(portFake(() => ({
      kind: 'Unknown', requestId: 'r3', reason: 'result-unknown',
    })) as never, identity)
    await expect(unknown.listDefinitions()).rejects.toBeInstanceOf(McpWireError)
  })

  it('refuses to bind without an identity, exactly like the fetch route', () => {
    expect(() => createWirePortMcpWireClient(portFake(() => ({
      kind: 'Unknown', requestId: 'r', reason: 'x',
    })) as never, { serverScope: '', principal: '' })).toThrow(McpWireError)
  })
})
