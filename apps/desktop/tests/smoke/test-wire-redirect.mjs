import assert from 'node:assert/strict'
import { createServer } from 'node:http'
import { readFile } from 'node:fs/promises'
import { transform } from 'esbuild'

// A local synthetic HTTP fixture exercises the actual Node fetch redirect path.
// It uses only fake credentials and never starts an Ordessa Server or Agent.
const source = await readFile(new URL('../../../plugins/agents/connectors/ordessa/src/wire.ts', import.meta.url), 'utf8')
const compiled = await transform(source, { loader: 'ts', format: 'esm' })
const { WireClient, WireError } = await import(`data:text/javascript;base64,${Buffer.from(compiled.code).toString('base64')}`)
const listen = server => new Promise(resolve => server.listen(0, '127.0.0.1', resolve))
const close = server => new Promise((resolve, reject) => server.close(error => error ? reject(error) : resolve()))
let redirectedCalls = 0
const redirected = createServer((_request, response) => { redirectedCalls++; response.end('unexpected') })
const first = createServer((_request, response) => {
  firstCalls++
  response.writeHead(307, { location: redirectTarget })
  response.end()
})
let firstCalls = 0
let redirectTarget = ''

await listen(redirected)
await listen(first)
try {
  const origin = `http://127.0.0.1:${first.address().port}`
  redirectTarget = `http://127.0.0.1:${redirected.address().port}/capture`
  const client = new WireClient({ origin, socket: origin.replace(/^http:/, 'ws:'), token: 'FAKE_BEARER' })
  const call = () => client.call('sessions.createAndSend', { text: 'FAKE_PROMPT' })
  await assert.rejects(call(), error => error instanceof WireError && error.code === 'UNAVAILABLE' &&
    !error.message.includes('FAKE_BEARER') && !error.message.includes('FAKE_PROMPT'))
  assert.equal(firstCalls, 1)
  assert.equal(redirectedCalls, 0, '307 must not replay bearer or body at a second origin')

  redirectTarget = `${origin}/elsewhere`
  await assert.rejects(call(), error => error instanceof WireError && error.code === 'UNAVAILABLE')
  assert.equal(firstCalls, 2, 'same-origin redirect must not trigger a second request')
  assert.equal(redirectedCalls, 0)
  console.log(JSON.stringify({ synthetic: 'PASS', crossOrigin307Blocked: true, sameOrigin307Blocked: true }))
} finally {
  await Promise.all([close(first), close(redirected)])
}
