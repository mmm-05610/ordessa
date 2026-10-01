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
  .replace("'./ordessa-configuration-query.mjs'", JSON.stringify(new URL('../pi-profile/configuration-query.mjs', import.meta.url).href))
  .replace("'./ordessa-restoration.mjs'", JSON.stringify('data:text/javascript;base64,' + Buffer.from(
    (await readFile(new URL('./restoration.mjs', import.meta.url), 'utf8')).replace(
      "'./ordessa-configuration-query.mjs'", JSON.stringify(new URL('../pi-profile/configuration-query.mjs', import.meta.url).href))).toString('base64')))
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
  test(`${brand}: initial provider precedes new, native model is applied before returning, and never resumes`, async () => {
    const f = fixture(brand)
    if (brand === 'codex') f.agent.sessions.clear()
    else f.agent.sessions = {}
    const order = []
    f.agent.codexAcpClient = { config: {} }
    f.agent.setProvider = input => { order.push('provider'); f.agent.route = input }
    f.agent.unstable_setProvider = f.agent.setProvider
    f.agent.setSessionConfigOption = async input => {
      order.push('model')
      const live = brand === 'codex' ? f.agent.sessions.get(input.sessionId) : f.agent.sessions[input.sessionId]
      live.configOptions.find(item => item.id === input.configId).currentValue = input.value
      return {}
    }
    const bridge = nativeProfileBridge(f.agent, brand, message => new Error(message))
    const input = { operationId: 'create:first', model: 'm2', provider: {
      providerId: brand === 'codex' ? 'custom-gateway' : 'main', apiType: brand === 'codex' ? 'openai' : 'anthropic',
      baseUrl: 'https://controlled.invalid', headers: { authorization: 'synthetic-first-secret' } } }
    const prepared = await bridge.prepareCreation(input)
    assert.equal(prepared.state, 'prepared')
    assert.deepEqual(await bridge.prepareCreation(input), prepared)
    await bridge.withCreation({ cwd: '/controlled', mcpServers: [], _meta: { untouched: true } }, async params => {
      order.push('new')
      assert.equal(params._meta.untouched, true)
      if (brand === 'claude-code') assert.equal(params._meta.claudeCode.options.model, 'm2')
      const session = structuredClone(f.session)
      session.configOptions[0].currentValue = 'm1'
      if (brand === 'codex') f.agent.sessions.set('s', session)
      else f.agent.sessions.s = session
      return { sessionId: 's' }
    })
    assert.deepEqual(order, ['provider', 'new', 'model'])
    const result = bridge.queryCreation({ operationId: input.operationId })
    assert.equal(result.state, 'observed')
    assert.equal(result.after.sessionId, 's')
    assert.equal(JSON.stringify(result).includes('synthetic-first-secret'), false)
    await assert.rejects(bridge.prepareCreation({ ...input, operationId: 'create:second' }), /already reserved/)
  })
}

test('first configuration refuses live siblings and cannot report native ACK as readback', async () => {
  const f = fixture('claude-code')
  const bridge = nativeProfileBridge(f.agent, 'claude-code', message => new Error(message))
  const input = { operationId: 'create:refuse', model: 'm2',
    provider: { providerId: 'main', apiType: 'anthropic', baseUrl: 'https://controlled.invalid' } }
  await assert.rejects(bridge.prepareCreation(input), /dedicated empty/)
  f.agent.sessions = {}
  f.agent.unstable_setProvider = async () => ({})
  f.agent.setSessionConfigOption = async () => ({}) // ACK must not stand in for readback.
  await bridge.prepareCreation(input)
  await assert.rejects(bridge.withCreation({ cwd: '/controlled', mcpServers: [] }, async () => {
    f.agent.sessions.s = structuredClone(f.session) // Native ignored requested m2.
    return { sessionId: 's' }
  }), /Initial model readback differs/)
  assert.equal(bridge.queryCreation({ operationId: input.operationId }).state, 'unknown')
  await assert.rejects(bridge.withCreation({ cwd: '/controlled', mcpServers: [] }, async () => {
    throw Error('must not execute a second creation')
  }), /already attempted/)
})

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

for (const brand of ['codex', 'claude-code']) {
  test(`${brand}: dedicated provider resume retains native session, proves new generation and never leaks headers`, async () => {
    const f = fixture(brand)
    const bridge = nativeProfileBridge(f.agent, brand, message => new Error(message))
    let providerCalls = 0, resumeCalls = 0
    f.agent.setSessionConfigOption = async input => {
      const session = brand === 'codex' ? f.agent.sessions.get(input.sessionId) : f.agent.sessions[input.sessionId]
      session.configOptions.find(item => item.id === input.configId).currentValue = input.value
    }
    if (brand === 'codex') {
      f.agent.codexAcpClient = { config: {} }
      f.agent.setProvider = input => { providerCalls++; f.agent.route = input }
      f.agent.closeSession = async ({ sessionId }) => { f.agent.sessions.delete(sessionId) }
      f.agent.resumeSession = async params => {
        resumeCalls++
        assert.equal(params.sessionId, 's')
        assert.equal(params.cwd, '/controlled-project')
        assert.deepEqual(params.mcpServers, [{ name: 'test', command: 'controlled-peer', args: [] }])
        const replacement = structuredClone(f.session)
        replacement.configOptions[0].currentValue = f.agent.codexAcpClient.config.model
        replacement.authProvider = 'custom-gateway'
        f.agent.sessions.set('s', replacement)
      }
      f.agent.listProviders = () => ({ providers: [{ providerId: 'custom-gateway', current: f.agent.route }] })
      await bridge.withCreation({ cwd: '/controlled-project', mcpServers: [{ name: 'test', command: 'controlled-peer', args: [] }] },
        async () => ({ sessionId: 's' }))
    } else {
      f.agent.unstable_setProvider = async input => {
        providerCalls++; resumeCalls++
        const replacement = structuredClone(f.session)
        replacement.ordessaProviderRoute = { apiType: input.apiType, baseUrl: input.baseUrl }
        f.agent.sessions.s = replacement
      }
    }
    const before = bridge.read({ sessionId: 's' })
    const input = { sessionId: 's', operationId: 'restore:one', expectedGeneration: before.generation,
      expectedConfigDigest: configurationDigest(before), model: 'm2',
      target: { server_id: 'server', session_id: 'canonical', channel_id: 'channel', runtime_generation: 1 },
      provider: { providerId: brand === 'codex' ? 'custom-gateway' : 'main',
        apiType: brand === 'codex' ? 'openai' : 'anthropic', baseUrl: 'https://controlled.invalid',
        headers: { authorization: 'synthetic-never-export' } } }
    const result = await bridge.restoration.apply(input)
    assert.equal(result.state, 'observed')
    assert.notEqual(result.before.generation, result.after.generation)
    assert.equal(result.after.sessionId, 's')
    assert.equal(JSON.stringify(result).includes('synthetic-never-export'), false)
    assert.deepEqual(await bridge.restoration.apply(input), result)
    assert.deepEqual(bridge.queryOperation({ sessionId: 's', operationId: input.operationId }), result)
    assert.equal(providerCalls, 1); assert.equal(resumeCalls, 1)
    await assert.rejects(bridge.restoration.apply({ ...input, model: 'changed' }), /different input/)
  })
}

test('Claude swallowed resume failure is Unknown, query/replay never attempts another resume', async () => {
  const f = fixture('claude-code')
  let calls = 0
  f.agent.unstable_setProvider = async () => { calls++; delete f.agent.sessions.s; return {} }
  const bridge = nativeProfileBridge(f.agent, 'claude-code', message => new Error(message))
  const before = bridge.read({ sessionId: 's' })
  const input = { sessionId: 's', operationId: 'restore:lost', expectedGeneration: before.generation,
    expectedConfigDigest: configurationDigest(before), model: 'm2',
    target: { server_id: 'server', session_id: 'canonical', channel_id: 'channel', runtime_generation: 1 },
    provider: { providerId: 'main', apiType: 'anthropic', baseUrl: 'https://controlled.invalid' } }
  const result = await bridge.restoration.apply(input)
  assert.equal(result.state, 'unknown')
  assert.deepEqual(await bridge.restoration.apply(input), result)
  bridge.queryOperation({ sessionId: 's', operationId: input.operationId })
  assert.equal(calls, 1)
})

test('provider resume refuses adapter siblings and unsupported protocols before effect', async () => {
  const f = fixture('claude-code')
  let calls = 0
  f.agent.unstable_setProvider = async () => { calls++ }
  const bridge = nativeProfileBridge(f.agent, 'claude-code', message => new Error(message))
  const before = bridge.read({ sessionId: 's' })
  const input = { sessionId: 's', operationId: 'restore:refuse', expectedGeneration: before.generation,
    expectedConfigDigest: configurationDigest(before), model: 'm2',
    target: { server_id: 'server', session_id: 'canonical', channel_id: 'channel', runtime_generation: 1 },
    provider: { providerId: 'main', apiType: 'unsupported', baseUrl: 'https://controlled.invalid' } }
  await assert.rejects(bridge.restoration.apply(input), /Supported Claude/)
  f.agent.sessions.sibling = structuredClone(f.session)
  await assert.rejects(bridge.restoration.apply({ ...input, provider: { ...input.provider, apiType: 'anthropic' } }), /dedicated/)
  assert.equal(calls, 0)
})

test('restoration failure exposes only closed diagnostics, never upstream secrets, and replay has no effect', async () => {
  const f = fixture('claude-code')
  let calls = 0
  f.agent.unstable_setProvider = async () => {
    calls++
    throw new Error('credential rejected: synthetic-secret-never-export')
  }
  const bridge = nativeProfileBridge(f.agent, 'claude-code', message => new Error(message))
  const before = bridge.read({ sessionId: 's' })
  const input = { sessionId: 's', operationId: 'restore:diagnostic', expectedGeneration: before.generation,
    expectedConfigDigest: configurationDigest(before), model: 'm2',
    target: { server_id: 'server', session_id: 'canonical', channel_id: 'channel', runtime_generation: 1 },
    provider: { providerId: 'main', apiType: 'anthropic', baseUrl: 'https://controlled.invalid' } }
  const record = await bridge.restoration.apply(input)
  assert.equal(record.state, 'unknown')
  assert.equal(record.failureStep, 'provider')
  assert.equal(record.failureReason, 'native-authentication-rejected')
  assert.equal(JSON.stringify(record).includes('synthetic-secret'), false)
  assert.deepEqual(await bridge.restoration.apply(input), record)
  assert.equal(calls, 1)
})

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
