import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
const source = await readFile(new URL('./creation.mjs', import.meta.url), 'utf8')
const query = await readFile(new URL('./configuration-query.mjs', import.meta.url), 'utf8')
const { piCreation } = await import('data:text/javascript;base64,' + Buffer.from(source.replace(
  "'./ordessa-configuration-query.mjs'", JSON.stringify('data:text/javascript;base64,' + Buffer.from(query).toString('base64')))).toString('base64'))

function fixture() {
  const calls = []
  const agent = { live: new Map(), disposed: false, deps: { modelRuntime: {
    registerProvider(id, value) { calls.push(['register', id, value]); this.models = value.models.map(m =>
      ({ id: m.id, provider: id, api: value.api, baseUrl: value.baseUrl })) },
    async setRuntimeApiKey(id, key) { calls.push(['key', id, key]) },
    async refresh(options) { calls.push(['refresh', options]) },
    async getAvailable() { return this.models },
  } }, async setConfigOption({ params }) { calls.push(['select', params]); this.live.get(params.sessionId).value = params.value } }
  const read = ({ sessionId }) => ({ sessionId, generation: 'observed-generation', busy: false,
    configOptions: [{ id: 'model', type: 'select', currentValue: agent.live.get(sessionId).value,
      options: agent.deps.modelRuntime.models.map(m => ({ value: m.provider + '/' + m.id,
        _meta: { ordessaModel: { provider: m.provider, model: m.id, api: m.api, baseUrl: m.baseUrl } } })) }] })
  const bridge = piCreation({ agent, read, invalidParams: message => new Error(message) })
  const input = { operationId: 'create:scope', model: 'm1', models: ['m1', 'm2'],
    provider: { providerId: 'custom', apiType: 'openai-completions', baseUrl: 'http://127.0.0.1:9/v1', apiKey: '!opaque-key-not-a-command' } }
  const create = async () => { agent.live.set('native', { value: 'other/model' }); return { sessionId: 'native' } }
  return { agent, calls, bridge, input, create }
}

test('registers privately, opaque key via runtime API, observes native creation once', async () => {
  const f = fixture()
  assert.equal((await f.bridge.prepare(f.input)).state, 'prepared')
  assert.equal(Object.hasOwn(f.calls[0][2], 'apiKey'), false)
  assert.deepEqual(f.calls.find(c => c[0] === 'refresh'), ['refresh', { allowNetwork: false }])
  assert.equal(JSON.stringify(f.bridge.query({ operationId: f.input.operationId })).includes(f.input.provider.apiKey), false)
  assert.equal((await f.bridge.create({}, f.create)).sessionId, 'native')
  const record = f.bridge.query({ operationId: f.input.operationId })
  assert.equal(record.state, 'observed'); assert.equal(record.after.generation, 'observed-generation')
  await assert.rejects(f.bridge.create({}, f.create), /already attempted/)
  await f.bridge.prepare(f.input)
  assert.equal(f.calls.filter(c => c[0] === 'register').length, 1)
})

test('extension model definitions contain the pinned Pi request fields', async () => {
  const f = fixture()
  await f.bridge.prepare(f.input)
  for (const model of f.calls.find(c => c[0] === 'register')[2].models) {
    assert.deepEqual(model.input, ['text'])
    assert.equal(model.reasoning, false)
    assert.ok(Number.isFinite(model.contextWindow) && model.contextWindow > 0)
    assert.ok(Number.isFinite(model.maxTokens) && model.maxTokens > 0)
    assert.deepEqual(Object.keys(model.cost).sort(), ['cacheRead', 'cacheWrite', 'input', 'output'])
  }
})

test('unknown preparation is query-only and never exposes upstream key', async () => {
  const f = fixture()
  f.agent.deps.modelRuntime.setRuntimeApiKey = async () => { throw Error(f.input.provider.apiKey) }
  assert.equal((await f.bridge.prepare(f.input)).state, 'unknown')
  assert.equal((await f.bridge.prepare(f.input)).state, 'unknown')
  assert.equal(f.calls.filter(c => c[0] === 'register').length, 1)
  await assert.rejects(f.bridge.create({}, f.create), /not prepared/)
  assert.equal(JSON.stringify(f.bridge.query({ operationId: f.input.operationId })).includes(f.input.provider.apiKey), false)
})

test('refuses malformed dialect, shared adapter, changed replay and lifecycle competition', async () => {
  for (const patch of [{ models: ['m1', 'm1'] }, { models: ['m2'] }, { model: '' },
    { provider: { providerId: 'x/y', apiType: 'openai-completions', baseUrl: 'https://x.test' } },
    { provider: { ...fixture().input.provider, apiType: 'anthropic' } },
    { provider: { ...fixture().input.provider, baseUrl: 'https://user:pass@x.test' } }, { extra: true }]) {
    const f = fixture(); await assert.rejects(f.bridge.prepare({ ...f.input, ...patch })); assert.equal(f.calls.length, 0)
  }
  const f = fixture(); f.agent.live.set('existing', {});
  await assert.rejects(f.bridge.prepare(f.input), /dedicated empty/); assert.equal(f.calls.length, 0)
  f.agent.live.clear(); await f.bridge.prepare(f.input)
  await assert.rejects(f.bridge.prepare({ ...f.input, model: 'm2' }), /already reserved/)
  await assert.rejects(f.bridge.lifecycle(f.create), /fresh creation/)
})

test('provider request during creation and mismatched native route never confirm', async () => {
  const f = fixture(); await f.bridge.prepare(f.input)
  let resolve
  const pending = f.bridge.create({}, async () => { await new Promise(r => { resolve = r }); return f.create() })
  await assert.rejects(f.bridge.prepare(f.input), /busy/)
  resolve(); await pending
  const bad = fixture(); await bad.bridge.prepare(bad.input)
  bad.agent.setConfigOption = async () => {}
  await assert.rejects(bad.bridge.create({}, bad.create), /readback differs/)
  assert.equal(bad.bridge.query({ operationId: bad.input.operationId }).state, 'unknown')
})
