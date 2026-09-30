import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { nativeConfigurationReader } from './configuration-query.mjs'
import { configurationDigest } from '../pi-profile/configuration-query.mjs'

const source = await readFile(new URL('../pi-profile/configuration-operation.mjs', import.meta.url), 'utf8')
const rewritten = source.replace("'./ordessa-configuration-query.mjs'",
  JSON.stringify(new URL('../pi-profile/configuration-query.mjs', import.meta.url).href))
const { configurationOperations } = await import('data:text/javascript;base64,' + Buffer.from(rewritten).toString('base64'))
const bridgeSource = (await readFile(new URL('./bridge.mjs', import.meta.url), 'utf8'))
  .replace("'./ordessa-native-configuration-query.mjs'", JSON.stringify(new URL('./configuration-query.mjs', import.meta.url).href))
  .replace("'./ordessa-configuration-operation.mjs'", JSON.stringify('data:text/javascript;base64,' + Buffer.from(rewritten).toString('base64')))
const { nativeProfileBridge } = await import('data:text/javascript;base64,' + Buffer.from(bridgeSource).toString('base64'))

function fixture(brand, effect) {
  const session = { configOptions: [{ id: 'model', type: 'select', currentValue: 'm1',
    options: [{ value: 'm1' }, { value: 'm2', _meta: { secret: 'do-not-project' } }],
    _meta: { headers: { authorization: 'do-not-project' } } }], turnQueue: [] }
  let calls = 0
  const agent = { sessions: brand === 'codex' ? new Map([['s', session]]) : { s: session },
    activePrompts: new Map(), pendingTurnStarts: new Map(), sessionIsClosing: () => false,
    createSessionConfigOptions: current => current.configOptions,
    async setSessionConfigOption(input) {
      calls++
      if (effect) await effect({ agent, session, input })
      else session.configOptions[0].currentValue = input.value
      return { configOptions: [{ id: 'model', currentValue: input.value }] }
    } }
  const invalidParams = message => new Error(message)
  const { read, assertIdle } = nativeConfigurationReader({ agent, brand, invalidParams })
  const operation = configurationOperations({ agent, read, assertIdle, invalidParams,
    configIds: ['model'], evidencePrefix: brand + '-native-operation',
    setOption: input => agent.setSessionConfigOption(input) })
  const before = read({ sessionId: 's' })
  const input = { sessionId: 's', operationId: 'op', expectedGeneration: before.generation,
    expectedConfigDigest: configurationDigest(before), configId: 'model', value: 'm2' }
  return { agent, session, read, operation, input, calls: () => calls }
}

for (const brand of ['codex', 'claude-code']) {
  test(`${brand}: live readback and idempotent replay, no credential metadata`, async () => {
    const f = fixture(brand)
    const result = await f.operation.apply(f.input)
    assert.equal(result.state, 'observed')
    assert.match(result.evidenceRef, new RegExp('^' + brand + '-native-operation:'))
    assert.equal(JSON.stringify(result).includes('do-not-project'), false)
    assert.deepEqual(await f.operation.apply(f.input), result)
    assert.equal(f.calls(), 1)
    const readback = f.read({ sessionId: 's' })
    readback.configOptions[0].currentValue = 'mutated'
    assert.equal(f.session.configOptions[0].currentValue, 'm2')
  })
  test(`${brand}: successful setter ACK without changed live state is unknown`, async () => {
    const f = fixture(brand, async () => {})
    assert.equal((await f.operation.apply(f.input)).state, 'unknown')
    assert.equal(f.calls(), 1)
    f.operation.query({ sessionId: 's', operationId: 'op' })
    assert.equal(f.calls(), 1)
  })
  test(`${brand}: live instance replacement cannot reuse old generation evidence`, async () => {
    const f = fixture(brand, async ({ agent, session }) => {
      const replacement = structuredClone(session)
      replacement.configOptions[0].currentValue = 'm2'
      if (brand === 'codex') agent.sessions.set('s', replacement)
      else agent.sessions.s = replacement
    })
    const result = await f.operation.apply(f.input)
    assert.equal(result.state, 'unknown')
    assert.notEqual(result.after.generation, result.before.generation)
  })
  test(`${brand}: actual active turn refuses before effect`, async () => {
    const f = fixture(brand)
    if (brand === 'codex') f.agent.activePrompts.set('s', {})
    else f.session.turnQueue.push({ settled: false })
    await assert.rejects(f.operation.apply(f.input), /busy/)
    assert.equal(f.calls(), 0)
  })
  test(`${brand}: disappearing session despite successful ACK is unknown`, async () => {
    const f = fixture(brand, async ({ agent }) => {
      if (brand === 'codex') agent.sessions.delete('s')
      else delete agent.sessions.s
    })
    const result = await f.operation.apply(f.input)
    assert.equal(result.state, 'unknown')
    assert.equal(result.phase, 'read-back-unavailable')
  })
  test(`${brand}: pre-existing configuration drift refuses with zero effects`, async () => {
    const f = fixture(brand)
    f.session.configOptions[0].currentValue = 'm2'
    await assert.rejects(f.operation.apply(f.input), /fence/)
    assert.equal(f.calls(), 0)
  })
}

test('Claude provider update and closed query cannot be treated as idle live evidence', async () => {
  const f = fixture('claude-code')
  f.agent.providerUpdate = Promise.resolve()
  await assert.rejects(f.operation.apply(f.input), /busy/)
  f.agent.providerUpdate = null
  f.session.queryClosed = true
  assert.throws(() => f.read({ sessionId: 's' }), /not live/)
  assert.equal(f.calls(), 0)
})

test('duplicate/malformed selector evidence fails closed', () => {
  const f = fixture('codex')
  f.session.configOptions.push(f.session.configOptions[0])
  assert.throws(() => f.read({ sessionId: 's' }), /duplicate/)
})

for (const brand of ['codex', 'claude-code']) {
  test(`${brand}: provider and lifecycle/turn operations cannot overlap`, async () => {
    const f = fixture(brand)
    const bridge = nativeProfileBridge(f.agent, brand, message => new Error(message))
    let release
    const gate = new Promise(resolve => { release = resolve })
    const lifecycle = bridge.withLifecycle(() => gate)
    await assert.rejects(bridge.withProvider(async () => {}), /lifecycle/)
    release(); await lifecycle
    const providerGate = new Promise(resolve => { release = resolve })
    const provider = bridge.withProvider(() => providerGate)
    assert.equal(bridge.read({ sessionId: 's' }).busy, true)
    await assert.rejects(bridge.withLifecycle(async () => {}), /busy/)
    await assert.rejects(bridge.operation.withSession('s', async () => {}), /busy/)
    release(); await provider
    assert.equal(bridge.read({ sessionId: 's' }).busy, false)
    const configGate = new Promise(resolve => { release = resolve })
    const config = bridge.operation.withSession('s', () => configGate)
    await assert.rejects(bridge.withProvider(async () => {}), /busy/)
    release(); await config
  })
}
