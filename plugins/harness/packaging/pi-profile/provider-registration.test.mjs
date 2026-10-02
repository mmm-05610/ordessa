import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
const url = source => 'data:text/javascript;base64,' + Buffer.from(source).toString('base64')
const query = url(await readFile(new URL('./configuration-query.mjs', import.meta.url), 'utf8'))
const load = async name => import(url((await readFile(new URL(name, import.meta.url), 'utf8'))
  .replace("'./ordessa-configuration-query.mjs'", JSON.stringify(query))))
const { configurationDigest } = await import(query)
const { piCreation } = await load('./creation.mjs')
const { piProviderRegistration } = await load('./provider-registration.mjs')

function fixture() {
  const calls = []
  let available = [{ id: 'old', provider: 'original', api: 'openai-completions', baseUrl: 'https://old.example/v1' }]
  const session = { value: 'original/old', availableModels: available,
    publishAvailableModels(models) { calls.push('publish'); this.availableModels = models } }
  const runtime = {
    registerProvider(provider, config) { calls.push('register'); available = [...available,
      ...config.models.map(model => ({ ...model, provider, api: config.api, baseUrl: config.baseUrl }))]
      available = available.filter((model, index) => available.findLastIndex(other =>
        other.provider === model.provider && other.id === model.id) === index) },
    async setRuntimeApiKey() { calls.push('key') },
    async refresh(options) { assert.deepEqual(options, { allowNetwork: false }); calls.push('refresh') },
    async getAvailable() { return available },
  }
  const agent = { live: new Map([['native', session]]), deps: { modelRuntime: runtime } }
  const read = ({ sessionId }) => ({ sessionId, generation: 'same-generation', busy: Boolean(session.busy),
    configOptions: [{ id: 'model', type: 'select', currentValue: session.value,
      options: session.availableModels.map(model => ({ value: model.provider + '/' + model.id,
        _meta: { ordessaModel: { provider: model.provider, model: model.id, api: model.api, baseUrl: model.baseUrl } } })) }] })
  const invalidParams = message => new Error(message)
  const creation = piCreation({ agent, read, invalidParams })
  const registration = piProviderRegistration({ agent, read, creation, invalidParams })
  const input = { sessionId: 'native', operationId: 'provider:one', expectedGeneration: 'same-generation',
    expectedConfigDigest: configurationDigest(read({ sessionId: 'native' })),
    target: { server_id: 'server', session_id: 'canonical', channel_id: 'channel', runtime_generation: 3 },
    model: 'new', models: ['new'], provider: { providerId: 'next', apiType: 'openai-completions',
      baseUrl: 'https://new.example/v1', apiKey: 'opaque-private-key' } }
  return { calls, session, runtime, agent, registration, creation, read, input }
}

test('a startup-admitted provider can add a model after the first turn without replacing credentials or losing models', async () => {
  const f = fixture()
  f.agent.live.clear()
  f.agent.setConfigOption = async ({params}) => { f.session.value = params.value }
  await f.creation.prepare({operationId:'create:first',provider:f.input.provider,model:'new',models:['new']})
  await f.creation.create({}, async () => {
    f.session.availableModels = await f.runtime.getAvailable()
    f.agent.live.set('native',f.session)
    return {sessionId:'native'}
  })
  const after = await f.registration.apply({...f.input,model:'extra',models:['extra'],
    expectedConfigDigest:configurationDigest(f.read({sessionId:'native'}))})
  assert.equal(after.state,'observed')
  assert.equal(f.session.value,'next/new')
  assert.ok(after.after.configOptions[0].options.some(o=>o.value==='next/new'))
  assert.ok(after.after.configOptions[0].options.some(o=>o.value==='next/extra'))
  await assert.rejects(f.registration.apply({...f.input,operationId:'provider:rotate',
    expectedConfigDigest:configurationDigest(after.after),provider:{...f.input.provider,apiKey:'different'}}),/already exists/)
})

test('new provider admission preserves session, generation, selection and prior catalogue', async () => {
  const f = fixture()
  const result = await f.registration.apply(f.input)
  assert.equal(result.state, 'observed')
  assert.equal(result.before.generation, result.after.generation)
  assert.equal(f.agent.live.get('native'), f.session)
  assert.equal(f.session.value, 'original/old')
  assert.deepEqual(result.after.configOptions[0].options.map(x => x.value), ['original/old', 'next/new'])
  assert.equal(JSON.stringify(result).includes(f.input.provider.apiKey), false)
  await f.registration.apply(f.input)
  assert.deepEqual(f.calls, ['register', 'key', 'refresh', 'publish'])
  assert.equal(f.registration.query({ sessionId: 'native', operationId: 'provider:one' }).state, 'observed')
  await assert.rejects(f.registration.apply({ ...f.input, model: 'different', models: ['different'] }), /different input/)
})

test('busy, stale, shared and existing provider inputs refuse before effects', async () => {
  for (const setup of [f => { f.session.busy = true }, f => { f.input.expectedGeneration = 'stale' },
    f => { f.input.expectedConfigDigest = '0'.repeat(64) }, f => { f.agent.live.set('other', {}) },
    f => { f.input.provider.providerId = 'original' }]) {
    const f = fixture(); setup(f)
    await assert.rejects(f.registration.apply(f.input))
    assert.deepEqual(f.calls, [])
  }
})

test('partial provider effect stays unknown, secret-free, query-only and blocks new work', async () => {
  const f = fixture()
  f.runtime.setRuntimeApiKey = async () => { throw Error(f.input.provider.apiKey) }
  assert.equal((await f.registration.apply(f.input)).state, 'unknown')
  assert.equal(f.registration.isBusy(), true)
  await f.registration.apply(f.input)
  assert.deepEqual(f.calls, ['register'])
  await assert.rejects(f.registration.apply({ ...f.input, operationId: 'provider:two' }), /query only/)
  assert.equal(JSON.stringify(f.registration.query({ sessionId: 'native', operationId: 'provider:one' }))
    .includes(f.input.provider.apiKey), false)
})

test('owner loss or unfaithful catalogue readback never confirms registration', async () => {
  for (const patch of [f => { f.runtime.refresh = async () => f.agent.live.clear() },
    f => { f.session.publishAvailableModels = () => {} },
    f => { f.session.publishAvailableModels = models => { f.session.availableModels = models; f.session.value = 'next/new' } }]) {
    const f = fixture(); patch(f)
    assert.equal((await f.registration.apply(f.input)).state, 'unknown')
  }
})

test('concurrent admissions cannot race runtime provider effects', async () => {
  const f = fixture(); let release
  f.runtime.refresh = () => new Promise(resolve => { release = resolve })
  const first = f.registration.apply(f.input)
  await assert.rejects(f.registration.apply({ ...f.input, operationId: 'provider:two' }), /query only/)
  release(); assert.equal((await first).state, 'observed')
})

test('adding another model to an admitted route retains earlier models, but cannot rotate its credentials', async () => {
  const f = fixture()
  const first = await f.registration.apply(f.input)
  const next = { ...f.input, operationId: 'provider:second', model: 'extra', models: ['extra'],
    expectedConfigDigest: configurationDigest(first.after) }
  const second = await f.registration.apply(next)
  assert.equal(second.state, 'observed')
  assert.deepEqual(second.after.configOptions[0].options.map(x => x.value), ['original/old', 'next/new', 'next/extra'])
  await assert.rejects(f.registration.apply({ ...next, operationId: 'provider:third',
    expectedConfigDigest: configurationDigest(second.after), provider: { ...next.provider, apiKey: 'changed-key' } }), /already exists/)
})
