/** Run from a temporary npm install of packed public client/contracts artifacts. */
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { HttpWirePort, QueryClient } from '@ordessa/system-access-client'
import type { WireResult } from '@ordessa/interface-contracts'

test('response loss sends once and preserves the original ACP payload', async () => {
  const payload = { sessionId: 'native-session', prompt: [{ type: 'text', text: 'native prompt' }], _meta: { native: true } }
  let calls = 0
  const port = new HttpWirePort({ origin: 'http://127.0.0.1', wirePathPrefix: '/wire/v1/', scope: 'test|server',
    readToken: async () => 'synthetic-token', fetchImpl: async (_url, options) => {
      calls++
      assert.deepEqual(JSON.parse(String(options?.body)).params, payload)
      throw Error('controlled response loss')
    } })
  const result = await port.call('units.prompt', payload)
  assert.equal(calls, 1)
  assert.equal(result.kind, 'Unknown')
  assert.equal('retryable' in result, false)
  assert.equal('token' in port, false)
})

test('server refusal and missing transport remain distinct', async () => {
  const port = new HttpWirePort({ origin: 'http://127.0.0.1', wirePathPrefix: '/wire/v1/', scope: 'test|server',
    readToken: async () => 'synthetic-token', fetchImpl: async (_url, options) => {
      const id = JSON.parse(String(options?.body)).id
      return new Response(JSON.stringify({ jsonrpc: '2.0', id, error: { code: 'FORBIDDEN', message: 'refused', details: { retryable: false } } }), { status: 200 })
    } })
  const result = await port.call('engineering.artifacts.create', {})
  assert.equal(result.kind, 'Refused')
  if (result.kind === 'Refused') assert.equal(result.retryable, false)
  const absent = new HttpWirePort({ origin: 'http://127.0.0.1', wirePathPrefix: '/wire/v1/', scope: null, readToken: async () => null })
  assert.equal((await absent.call('server.hello', {})).kind, 'Unknown')
})

test('coalesced read refresh keeps the last backend fact on disconnect', async () => {
  let calls = 0
  let complete!: (result: WireResult) => void
  const query = new QueryClient({ call: () => { calls++; return new Promise(resolve => { complete = resolve }) } }, 'server.hello')
  const first = query.refresh()
  assert.equal(query.refresh(), first)
  complete({ kind: 'Accepted', requestId: 'read-1', result: { serverId: 'one-backend' } })
  await first
  const later = query.refresh()
  complete({ kind: 'Unknown', requestId: 'read-2', reason: 'transport-unreachable' })
  await later
  assert.equal(calls, 2)
  assert.deepEqual(query.getSnapshot().data, { serverId: 'one-backend' })
  assert.equal(query.getSnapshot().stale, true)
})
