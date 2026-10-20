import assert from 'node:assert/strict'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { build } from 'esbuild'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../../..')
const bundled = await build({
  entryPoints: [path.join(root, 'plugins/agents/connectors/ordessa/src/wire.ts')],
  bundle: true, platform: 'node', format: 'esm', write: false,
})
const previous = globalThis.WebSocket
let constructed
class ConstructorOnlySocket {
  constructor(url, options) {
    constructed = { url, options }
  }
  addEventListener() {}
  close() {}
}
try {
  globalThis.WebSocket = ConstructorOnlySocket
  const { openEventStream } = await import(`data:text/javascript;base64,${Buffer.from(bundled.outputFiles[0].text).toString('base64')}`)
  const handle = openEventStream({ socket: 'ws://127.0.0.1:4471', token: 'fixture-only' },
    'session-fixture', 'cursor-fixture', { frame() {}, down() {} })
  assert.equal(constructed.url,
    'ws://127.0.0.1:4471/wire/v1/event-stream?sessionId=session-fixture&cursor=cursor-fixture')
  assert.deepEqual(constructed.options, { headers: { authorization: 'Bearer fixture-only' } })
  handle.close()
  console.log('Ordessa event stream constructor: PASS')
} finally {
  globalThis.WebSocket = previous
}
