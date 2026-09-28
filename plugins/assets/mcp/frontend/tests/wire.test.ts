// The fetch McpWireClient speaks the server's wire/1 envelope exactly:
// POST {base}/wire/v1/{method} with {jsonrpc:"2.0",id,method,params}
// (apps/server wire/envelope.py) and reads back one of result|error.

import { describe, expect, it } from 'vitest'
import { createFetchMcpWireClient, McpWireError } from '../src/wire'

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
    const client = createFetchMcpWireClient({
      baseUrl: 'http://127.0.0.1:41207/',
      fetchImpl: jsonFetch({ jsonrpc: '2.0', id: 1, result: [{ definitionId: 'a', name: 'a' }] }, record),
    })
    const rows = await client.listDefinitions()
    expect(rows).toEqual([{ definitionId: 'a', name: 'a' }])
    expect(record[0].url).toBe('http://127.0.0.1:41207/wire/v1/mcp.listDefinitions')
    expect(record[0].init.method).toBe('POST')
    const body = JSON.parse(String(record[0].init.body))
    expect(body).toMatchObject({ jsonrpc: '2.0', method: 'mcp.listDefinitions', params: {} })
    expect(typeof body.id).toBe('number')
  })

  it('passes camelCase params through untouched and merges owner headers', async () => {
    const record: Recorded[] = []
    const client = createFetchMcpWireClient({
      baseUrl: 'http://127.0.0.1:1',
      fetchImpl: jsonFetch({ jsonrpc: '2.0', id: 1, result: { approvedRevision: 3 } }, record),
      headers: () => ({ authorization: 'Bearer token-under-owner-control' }),
    })
    await expect(client.approveRevision({ definitionId: 'a', revision: 3, expectedVersion: 2, operationKey: 'op-1' }))
      .resolves.toEqual({ approvedRevision: 3 })
    expect(JSON.parse(String(record[0].init.body)).params).toEqual({ definitionId: 'a', revision: 3, expectedVersion: 2, operationKey: 'op-1' })
    expect((record[0].init.headers as Record<string, string>).authorization).toBe('Bearer token-under-owner-control')
    expect((record[0].init.headers as Record<string, string>)['content-type']).toBe('application/json')
  })

  it('maps a typed wire error body to McpWireError with the business code', async () => {
    const client = createFetchMcpWireClient({
      baseUrl: 'http://127.0.0.1:1',
      fetchImpl: jsonFetch({ jsonrpc: '2.0', id: 1, error: { code: 'PROBE_TIMEOUT', message: 'handshake timed out' } }, []),
    })
    await expect(client.probe({ definitionId: 'a', revision: 1 })).rejects.toMatchObject({ code: 'PROBE_TIMEOUT', message: 'handshake timed out' })
  })

  it('refuses malformed envelopes instead of guessing success', async () => {
    const noMembers = createFetchMcpWireClient({ baseUrl: 'http://x', fetchImpl: jsonFetch({ jsonrpc: '2.0', id: 1 }, []) })
    await expect(noMembers.listDefinitions()).rejects.toBeInstanceOf(McpWireError)
    const notJson = createFetchMcpWireClient({
      baseUrl: 'http://x',
      fetchImpl: async () => new Response('<html>', { status: 502 }),
    })
    await expect(notJson.listDefinitions()).rejects.toMatchObject({ code: 'WIRE_BAD_RESPONSE' })
  })
})
