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
