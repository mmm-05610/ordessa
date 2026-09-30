import { test } from 'node:test'
import assert from 'node:assert/strict'
import { configurationReader } from './configuration-query.mjs'

test('readback uses live state, is detached, and generation tracks actual instances', () => {
  const options = [{ id: 'model', currentValue: 'p/m1' }]
  const session = { configOptions: () => options, busy: false }
  const agent = { live: new Map([['native', session]]) }
  const read = configurationReader(agent, message => new Error(message))
  const before = read({ sessionId: 'native' })
  before.configOptions[0].currentValue = 'forged'
  assert.equal(read({ sessionId: 'native' }).configOptions[0].currentValue, 'p/m1')
  options[0].currentValue = 'p/m2'; session.busy = true
  const after = read({ sessionId: 'native' })
  assert.equal(after.generation, before.generation)
  assert.equal(after.configOptions[0].currentValue, 'p/m2')
  assert.equal(after.busy, true)
  agent.live.set('native', { configOptions: () => options })
  assert.notEqual(read({ sessionId: 'native' }).generation, before.generation)
})
test('unknown, closed and disposed sessions never report applied configuration', () => {
  const agent = { live: new Map() }
  const read = configurationReader(agent, message => new Error(message))
  assert.throws(() => read({ sessionId: 'missing' }), /not live/)
  agent.live.set('native', { disposed: true })
  assert.throws(() => read({ sessionId: 'native' }), /not live/)
  agent.live.set('native', { closing: true })
  assert.throws(() => read({ sessionId: 'native' }), /not live/)
  agent.live.set('native', { configOptions: () => [] }); agent.disposed = true
  assert.throws(() => read({ sessionId: 'native' }), /not live/)
})

test('model readback exposes exact live routing facts but never credential material', () => {
  const model = { provider: 'p', id: 'm/path', api: 'openai-completions',
    baseUrl: 'https://fixture.test/v1', apiKey: 'do-not-project',
    headers: { Authorization: 'do-not-project' } }
  const options = [{ id: 'model', type: 'select', currentValue: 'p/m/path',
    options: [{ value: 'p/m/path', name: 'Display label' }] }]
  const session = { availableModels: [model], configOptions: () => options }
  const agent = { live: new Map([['native', session]]) }
  const read = configurationReader(agent, message => new Error(message))
  const result = read({ sessionId: 'native' })
  assert.deepEqual(result.configOptions[0].options[0]._meta.ordessaModel,
    { provider: 'p', model: 'm/path', api: 'openai-completions', baseUrl: 'https://fixture.test/v1' })
  assert.ok(!JSON.stringify(result).includes('do-not-project'))
  result.configOptions[0].options[0]._meta.ordessaModel.baseUrl = 'forged'
  assert.equal(read({ sessionId: 'native' }).configOptions[0].options[0]._meta.ordessaModel.baseUrl,
    'https://fixture.test/v1')
  assert.equal(options[0].options[0]._meta, undefined)
})

test('missing or ambiguous native model routing facts are not invented', () => {
  const entry = { provider: 'p', id: 'm', api: 'openai-completions', baseUrl: 'https://fixture.test' }
  const session = { availableModels: [entry, { ...entry, baseUrl: 'https://other.test' }],
    configOptions: () => [{ id: 'model', options: [{ value: 'p/m', name: 'p/m' }] }] }
  const read = configurationReader({ live: new Map([['native', session]]) }, message => new Error(message))
  assert.equal(read({ sessionId: 'native' }).configOptions[0].options[0]._meta, undefined)
})

test('reserved routing evidence cannot survive missing or unsafe native facts', () => {
  for (const baseUrl of ['https://user:secret@fixture.test', 'https://fixture.test?key=secret',
    'https://fixture.test#secret', 'file:///private', 'not a URL', null]) {
    const session = { availableModels: [{ provider: 'p', id: 'm', api: 'openai-completions', baseUrl }],
      configOptions: () => [{ id: 'model', options: [{ value: 'p/m',
        _meta: { other: 'preserved', ordessaModel: { baseUrl: 'forged' } } }] }] }
    const read = configurationReader({ live: new Map([['native', session]]) }, message => new Error(message))
    assert.deepEqual(read({ sessionId: 'native' }).configOptions[0].options[0]._meta,
      { other: 'preserved' })
  }
  const session = { availableModels: [], configOptions: () => [{ id: 'model', options: [
    { value: 'p/m', _meta: { ordessaModel: { provider: 'forged' } } }] }] }
  const read = configurationReader({ live: new Map([['native', session]]) }, message => new Error(message))
  assert.equal(read({ sessionId: 'native' }).configOptions[0].options[0]._meta, undefined)
})
