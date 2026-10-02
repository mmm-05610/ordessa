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

test('managed Codex rejects external provider effects without blocking internal read-only preparation', async () => {
  const previous = process.env.ORDESSA_CODEX_MANAGED_ACCOUNT_DIR
  process.env.ORDESSA_CODEX_MANAGED_ACCOUNT_DIR = '/synthetic/private-account'
  try {
    const bridge = nativeProfileBridge({sessions: new Map()}, 'codex', message => new Error(message))
    let effects = 0
    assert.throws(() => bridge.withExternalProvider(() => effects++), /cannot be changed/)
    assert.equal(effects, 0)
    assert.equal(await bridge.withProvider(() => 'internal'), 'internal')
  } finally {
    if (previous === undefined) delete process.env.ORDESSA_CODEX_MANAGED_ACCOUNT_DIR
    else process.env.ORDESSA_CODEX_MANAGED_ACCOUNT_DIR = previous
  }
})

// The supported non-model preference each brand exposes. Stated here rather than
// read from bridge.mjs so the gate contract is asserted independently.
const PREFERENCE = { 'codex': 'reasoning_effort', 'claude-code': 'effort' }
const PREFERENCE_VALUES = ['low', 'medium', 'high']

function fixture(brand, effect) {
  // A session whose only selector is `model` cannot show whether other supported
  // preferences survive a model-only change, so every fixture carries one.
  const preference = PREFERENCE[brand]
  const session = { configOptions: [{ id: 'model', type: 'select', currentValue: 'm1',
    options: [{ value: 'm1' }, { value: 'm2', _meta: { secret: 'do-not-project' } }],
    _meta: { headers: { authorization: 'do-not-project' } } },
    { id: preference, type: 'select', currentValue: 'high',
      options: PREFERENCE_VALUES.map(value => ({ value })) }], turnQueue: [] }
  let calls = 0
  const agent = { sessions: brand === 'codex' ? new Map([['s', session]]) : { s: session },
    activePrompts: new Map(), pendingTurnStarts: new Map(), sessionIsClosing: () => false,
    createSessionConfigOptions: current => current.configOptions,
    async setSessionConfigOption(input) {
      calls++
      if (effect) await effect({ agent, session, input })
      else {
        const option = session.configOptions.find(item => item.id === input.configId)
        if (option) option.currentValue = input.value
      }
      return { configOptions: session.configOptions.map(item => ({ id: item.id, currentValue: item.currentValue })) }
    } }
  const invalidParams = message => new Error(message)
  const { read, assertIdle } = nativeConfigurationReader({ agent, brand, invalidParams })
  const operation = configurationOperations({ agent, read, assertIdle, invalidParams,
    configIds: ['model', preference], evidencePrefix: brand + '-native-operation',
    setOption: input => agent.setSessionConfigOption(input) })
  const before = read({ sessionId: 's' })
  const input = { sessionId: 's', operationId: 'op', expectedGeneration: before.generation,
    expectedConfigDigest: configurationDigest(before), configId: 'model', value: 'm2' }
  return { agent, session, read, operation, input, calls: () => calls }
}

test('Codex model routing evidence comes from its accepted thread snapshot, not mutable provider state', () => {
  const f = fixture('codex')
  f.session.authProvider = 'custom-gateway'
  f.agent.codexAcpClient = { codexClient: { ordessaThreadRoutes: new Map([['s', {
    provider: 'custom-gateway', api: 'responses', baseUrl: 'https://thread.invalid/v1',
    headers: { authorization: 'never-export' }
  }]]) } }
  f.agent.listProviders = () => ({ current: { baseUrl: 'https://different.invalid' } })
  f.session.configOptions[0].options[0]._meta = { ordessaModel: { baseUrl: 'https://forged.invalid' } }
  const option = f.read({ sessionId: 's' }).configOptions[0].options[0]
  assert.deepEqual(option._meta.ordessaModel, {
    provider: 'custom-gateway', api: 'responses', baseUrl: 'https://thread.invalid/v1', model: 'm1'
  })
  assert.equal(JSON.stringify(option).includes('never-export'), false)
  f.session.authProvider = 'different'
  assert.equal(f.read({ sessionId: 's' }).configOptions[0].options[0]._meta, undefined)
  f.session.authProvider = 'custom-gateway'
  f.agent.codexAcpClient.codexClient.ordessaThreadRoutes.clear()
  assert.equal(f.read({ sessionId: 's' }).configOptions[0].options[0]._meta, undefined)
})

test('Codex accepts the native nullable description for an active custom model', () => {
  const f = fixture('codex')
  const option = f.session.configOptions[0]
  option.currentValue = 'gpt-6-luna'
  option.options.unshift({value: 'gpt-6-luna', name: 'gpt-6-luna', description: null})
  const observed = f.read({sessionId: 's'}).configOptions[0]
  assert.equal(observed.currentValue, 'gpt-6-luna')
  assert.deepEqual(observed.options[0], {value: 'gpt-6-luna', name: 'gpt-6-luna'})
  option.options[0].description = {secret: 'never-project'}
  assert.throws(() => f.read({sessionId: 's'}), /Invalid option text/)
})

test('Claude routing evidence uses captured query configuration and rejects secret-bearing endpoints', () => {
  const f = fixture('claude-code')
  f.session.ordessaProviderRoute = { apiType: 'anthropic', baseUrl: 'https://query.invalid' }
  assert.equal(f.read({ sessionId: 's' }).configOptions[0].options[0]._meta.ordessaModel.baseUrl,
    'https://query.invalid')
  for (const baseUrl of ['https://user:secret@query.invalid', 'https://query.invalid?key=secret']) {
    f.session.ordessaProviderRoute.baseUrl = baseUrl
    assert.equal(f.read({ sessionId: 's' }).configOptions[0].options[0]._meta, undefined)
  }
})

test('Claude exposes an off-picker effective model only with captured native routing', () => {
  const f = fixture('claude-code')
  f.session.configOptions[0].currentValue = 'minimax-m2.7'
  assert.equal(f.read({sessionId: 's'}).configOptions[0].options.some(o => o.value === 'minimax-m2.7'), false)
  f.session.ordessaProviderRoute = {apiType: 'anthropic', baseUrl: 'https://native-query.invalid'}
  const selector = f.read({sessionId: 's'}).configOptions[0]
  const current = selector.options.find(o => o.value === 'minimax-m2.7')
  assert.equal(current._meta.ordessaModel.model, 'minimax-m2.7')
  assert.equal(current._meta.ordessaModel.baseUrl, 'https://native-query.invalid')
  assert.equal(f.session.configOptions[0].options.length, 2) // projection never changes native state
})

for (const brand of ['codex', 'claude-code']) {
  test(`${brand}: initial provider precedes new, native model is applied before returning, and never resumes`, async () => {
    const f = fixture(brand)
    if (brand === 'codex') f.agent.sessions.clear()
    else f.agent.sessions = {}
    const order = []
    f.agent.codexAcpClient = { config: {}, codexClient: { ordessaThreadRoutes: new Map() } }
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
      if (brand === 'codex') {
        session.authProvider = 'custom-gateway'
        f.agent.codexAcpClient.codexClient.ordessaThreadRoutes.set('s', {
          provider: 'custom-gateway', api: 'responses', baseUrl: input.provider.baseUrl })
        f.agent.sessions.set('s', session)
      } else {
        session.ordessaProviderRoute = { apiType: 'anthropic', baseUrl: input.provider.baseUrl }
        f.agent.sessions.s = session
      }
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

test('initial model readback alone cannot confirm a different or missing provider route', async () => {
  for (const baseUrl of [undefined, 'https://other.invalid']) {
    const f = fixture('claude-code')
    f.agent.sessions = {}
    f.agent.unstable_setProvider = async () => ({})
    f.agent.setSessionConfigOption = async input => {
      f.agent.sessions[input.sessionId].configOptions[0].currentValue = input.value
      return {}
    }
    const bridge = nativeProfileBridge(f.agent, 'claude-code', message => new Error(message))
    await bridge.prepareCreation({ operationId: 'create:route', model: 'm2', provider: {
      providerId: 'main', apiType: 'anthropic', baseUrl: 'https://controlled.invalid' } })
    await assert.rejects(bridge.withCreation({ cwd: '/controlled', mcpServers: [] }, async () => {
      f.agent.sessions.s = structuredClone(f.session)
      f.agent.sessions.s.ordessaProviderRoute = { apiType: 'anthropic', baseUrl }
      return { sessionId: 's' }
    }), /Initial native construction routing differs/)
    assert.equal(bridge.queryCreation({ operationId: 'create:route' }).state, 'unknown')
  }
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
      f.agent.codexAcpClient = { config: {}, codexClient: { ordessaThreadRoutes: new Map() } }
      f.agent.setProvider = input => { providerCalls++; f.agent.route = input }
      f.agent.closeSession = async ({ sessionId }) => { f.agent.sessions.delete(sessionId) }
      f.agent.ordessaReplaceCodexProcess = async ({sessionId}) => {
        await f.agent.closeSession({sessionId})
        f.agent.codexAcpClient = {config: {model: 'm2'}, codexClient: {ordessaThreadRoutes: new Map()}}
      }
      f.agent.resumeSession = async params => {
        resumeCalls++
        assert.equal(params.sessionId, 's')
        assert.equal(params.cwd, '/controlled-project')
        assert.deepEqual(params.mcpServers, [{ name: 'test', command: 'controlled-peer', args: [] }])
        const replacement = structuredClone(f.session)
        replacement.configOptions[0].currentValue = f.agent.codexAcpClient.config.model
        replacement.authProvider = 'custom-gateway'
        f.agent.sessions.set('s', replacement)
        f.agent.codexAcpClient.codexClient.ordessaThreadRoutes.set('s', {
          provider: 'custom-gateway', api: 'responses', baseUrl: f.agent.route.baseUrl })
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

test('Codex return to managed account uses replacement, never a gateway setter or account login', async () => {
  const f = fixture('codex')
  const bridge = nativeProfileBridge(f.agent, 'codex', message => new Error(message))
  let restarts = 0, resumes = 0
  f.agent.ordessaReplaceCodexProcess = async input => {
    assert.equal(input.provider.authentication, 'managed-account')
    restarts++; f.agent.sessions.delete('s')
    f.agent.codexAcpClient = {codexClient: {ordessaThreadRoutes: new Map()}}
  }
  f.agent.setProvider = () => assert.fail('managed route must not use gateway setter')
  f.agent.resumeSession = async () => {
    resumes++
    const session = structuredClone(f.session); session.authProvider = 'openai'
    f.agent.sessions.set('s', session)
    f.agent.codexAcpClient.codexClient.ordessaThreadRoutes.set('s',
      {provider: 'openai', authentication: 'managed-account'})
  }
  f.agent.setSessionConfigOption = async input => {
    f.agent.sessions.get('s').configOptions.find(item => item.id === input.configId).currentValue = input.value
  }
  await bridge.withCreation({cwd: '/controlled-project'}, async () => ({sessionId: 's'}))
  const before = bridge.read({sessionId: 's'})
  const input = {sessionId: 's', operationId: 'restore:official', expectedGeneration: before.generation,
    expectedConfigDigest: configurationDigest(before), model: 'm2',
    target: {server_id: 'server', session_id: 'canonical', channel_id: 'channel', runtime_generation: 1},
    provider: {providerId: 'openai', authentication: 'managed-account', accountDirectory: '/private/account'}}
  const result = await bridge.restoration.apply(input)
  assert.equal(result.state, 'observed'); assert.notEqual(result.before.generation, result.after.generation)
  assert.deepEqual(await bridge.restoration.apply(input), result)
  assert.deepEqual(bridge.queryOperation({sessionId: 's', operationId: input.operationId}), result)
  assert.equal(restarts, 1); assert.equal(resumes, 1)
  assert.equal(JSON.stringify(result).includes('/private/account'), false)
  await assert.rejects(bridge.restoration.apply({...input, extra: true}), /exact/)
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

// --- B09: a model-only change must not cost the user's other supported preferences ---

const RESTORE_BASE_URL = 'https://controlled.invalid'
const GATEWAY = { providerId: 'custom-gateway', apiType: 'openai', baseUrl: RESTORE_BASE_URL }

function fence(before, operationId, configId, value) {
  return { sessionId: before.sessionId, operationId, expectedGeneration: before.generation,
    expectedConfigDigest: configurationDigest(before), configId, value }
}
function restorationInput(before, operationId, provider = GATEWAY) {
  return { sessionId: 's', operationId, expectedGeneration: before.generation,
    expectedConfigDigest: configurationDigest(before), model: 'm2',
    target: { server_id: 'server', session_id: 'canonical', channel_id: 'channel', runtime_generation: 1 },
    provider }
}

/** Codex restoration replaces the process, so the resumed session comes back on native
 *  defaults: the user's reasoning preference only survives if the bridge re-applies it. */
async function restartingCodex(f, apply = ({ option, input }) => { option.currentValue = input.value }) {
  const bridge = nativeProfileBridge(f.agent, 'codex', message => new Error(message))
  const writes = []
  f.agent.setSessionConfigOption = async input => {
    writes.push({ configId: input.configId, value: input.value })
    const live = f.agent.sessions.get(input.sessionId)
    const option = live?.configOptions.find(item => item.id === input.configId)
    if (option) await apply({ option, input })
  }
  f.agent.codexAcpClient = { config: {}, codexClient: { ordessaThreadRoutes: new Map() } }
  f.agent.setProvider = () => {}
  f.agent.closeSession = async ({ sessionId }) => { f.agent.sessions.delete(sessionId) }
  f.agent.ordessaReplaceCodexProcess = async () => {
    await f.agent.closeSession({ sessionId: 's' })
    f.agent.codexAcpClient = { config: { model: 'm1' }, codexClient: { ordessaThreadRoutes: new Map() } }
  }
  f.agent.resumeSession = async () => {
    const replacement = structuredClone(f.session)
    replacement.configOptions[0].currentValue = 'm1'
    replacement.configOptions[1].currentValue = 'medium' // the user's 'high' did not survive
    replacement.authProvider = 'custom-gateway'
    f.agent.sessions.set('s', replacement)
    f.agent.codexAcpClient.codexClient.ordessaThreadRoutes.set('s', {
      provider: 'custom-gateway', api: 'responses', baseUrl: RESTORE_BASE_URL })
  }
  await bridge.withCreation({ cwd: '/controlled-project' }, async () => ({ sessionId: 's' }))
  return { bridge, writes }
}

for (const brand of ['codex', 'claude-code']) {
  test(`${brand}: the supported non-model preference is admitted by the model-only gate, unknown ids and unexposed values are not`, async () => {
    const f = fixture(brand)
    const bridge = nativeProfileBridge(f.agent, brand, message => new Error(message))
    const preference = PREFERENCE[brand]
    const before = bridge.read({ sessionId: 's' })
    assert.deepEqual(before.configOptions.map(option => option.id).sort(), ['model', preference].sort())
    assert.equal(before.configOptions.find(option => option.id === preference).currentValue, 'high')

    const applied = await bridge.operation.apply(fence(before, 'op:preference', preference, 'low'))
    assert.equal(applied.state, 'observed')
    assert.equal(applied.observedValue, 'low')
    assert.equal(f.calls(), 1)
    assert.equal(f.session.configOptions[0].currentValue, 'm1') // the model was not touched
    assert.equal(bridge.read({ sessionId: 's' }).configOptions.find(o => o.id === preference).currentValue, 'low')
    assert.deepEqual(await bridge.operation.apply(fence(before, 'op:preference', preference, 'low')), applied)
    assert.equal(f.calls(), 1)

    await assert.rejects(bridge.operation.apply(fence(bridge.read({ sessionId: 's' }),
      'op:unknown', 'sandbox_mode', 'low')), /bounded session model/)
    await assert.rejects(bridge.operation.apply(fence(bridge.read({ sessionId: 's' }),
      'op:unexposed', preference, 'unsupported-level')), /not exposed by the live session/)
    assert.equal(f.calls(), 1) // both refusals happened before any upstream effect
  })
}

test('codex restoration re-applies the preserved reasoning preference instead of the restarted default', async () => {
  const f = fixture('codex')
  const { bridge, writes } = await restartingCodex(f)
  const before = bridge.read({ sessionId: 's' })
  assert.equal(before.configOptions.find(option => option.id === 'reasoning_effort').currentValue, 'high')

  const result = await bridge.restoration.apply(restorationInput(before, 'restore:preserved'))
  assert.equal(result.state, 'observed')
  // Model first, then the preserved preference, carrying the user's own value.
  assert.deepEqual(writes, [{ configId: 'model', value: 'm2' },
    { configId: 'reasoning_effort', value: 'high' }])
  const after = bridge.read({ sessionId: 's' })
  assert.equal(after.configOptions.find(option => option.id === 'reasoning_effort').currentValue, 'high')
  assert.equal(after.configOptions.find(option => option.id === 'model').currentValue, 'm2')
})

for (const [value, nativeDisabled, expected] of [['off', true, 'observed'], [false, true, 'observed'],
    ['off', false, 'unknown'], ['on', true, 'unknown']]) {
  test(`codex absent fast selector preserves only proven disabled state: ${value}/${nativeDisabled}`, async () => {
    const f = fixture('codex')
    f.session.configOptions.push(typeof value === 'boolean'
      ? {id: 'fast-mode', type: 'boolean', currentValue: value}
      : {id: 'fast-mode', type: 'select', currentValue: value,
          options: [{value: 'off', name: 'Off'}, {value: 'on', name: 'On'}]})
    const {bridge} = await restartingCodex(f)
    const resume = f.agent.resumeSession
    f.agent.resumeSession = async (...args) => {
      await resume(...args)
      const replacement = f.agent.sessions.get('s')
      replacement.configOptions = replacement.configOptions.filter(x => x.id !== 'fast-mode')
      replacement.currentModelSupportsFast = false
      if (nativeDisabled) replacement.fastModeEnabled = false
    }
    const before = bridge.read({sessionId: 's'})
    const result = await bridge.restoration.apply(restorationInput(before, 'restore:fast-proof'))
    assert.equal(result.state, expected)
    assert.equal(bridge.read({sessionId: 's'}).configOptions.some(x => x.id === 'fast-mode'), false)
  })
}

test('codex restoration records an explicit refusal when the target rejects the preserved preference', async () => {
  const f = fixture('codex')
  const { bridge, writes } = await restartingCodex(f, ({ option, input }) => {
    if (input.configId !== 'model') throw new Error('option value not accepted by this build')
  })
  const before = bridge.read({ sessionId: 's' })
  const result = await bridge.restoration.apply(restorationInput(before, 'restore:refused'))
  assert.equal(result.state, 'unknown')
  assert.equal(result.failureStep, 'preferences')
  assert.equal(result.failureReason, 'native-request-rejected')
  assert.equal(result.evidenceRef, null) // never reported as a successful restoration
  assert.deepEqual(writes, [{ configId: 'model', value: 'm2' },
    { configId: 'reasoning_effort', value: 'high' }])
  assert.deepEqual(await bridge.restoration.apply(restorationInput(before, 'restore:refused')), result)
  assert.equal(writes.length, 2) // a replay never re-offers the refused preference
})

test('codex restoration never reports success when the target silently keeps a native default', async () => {
  const f = fixture('codex')
  // The setter acknowledges every request but only the model ever lands.
  const { bridge } = await restartingCodex(f, ({ option, input }) => {
    if (input.configId === 'model') option.currentValue = input.value
  })
  const before = bridge.read({ sessionId: 's' })
  const result = await bridge.restoration.apply(restorationInput(before, 'restore:silent'))
  assert.equal(result.state, 'unknown')
  assert.equal(result.failureStep, 'preferences')
  assert.equal(result.evidenceRef, null)
  assert.equal(bridge.read({ sessionId: 's' }).configOptions
    .find(option => option.id === 'reasoning_effort').currentValue, 'medium')
})

test('claude-code restoration keeps the supported effort preference at the user value', async () => {
  const f = fixture('claude-code')
  const bridge = nativeProfileBridge(f.agent, 'claude-code', message => new Error(message))
  const writes = []
  f.agent.unstable_setProvider = async provider => {
    const replacement = structuredClone(f.session)
    replacement.ordessaProviderRoute = { apiType: provider.apiType, baseUrl: provider.baseUrl }
    f.agent.sessions.s = replacement
  }
  f.agent.setSessionConfigOption = async input => {
    writes.push({ configId: input.configId, value: input.value })
    const option = f.agent.sessions[input.sessionId].configOptions.find(item => item.id === input.configId)
    if (option) option.currentValue = input.value
  }
  const before = bridge.read({ sessionId: 's' })
  assert.equal(before.configOptions.find(option => option.id === 'effort').currentValue, 'high')
  const result = await bridge.restoration.apply(restorationInput(before, 'restore:effort',
    { providerId: 'main', apiType: 'anthropic', baseUrl: RESTORE_BASE_URL }))
  assert.equal(result.state, 'observed')
  assert.deepEqual(writes, [{ configId: 'model', value: 'm2' }]) // no process restart, so nothing to re-apply
  const after = bridge.read({ sessionId: 's' })
  assert.equal(after.configOptions.find(option => option.id === 'effort').currentValue, 'high')
  assert.equal(after.configOptions.find(option => option.id === 'model').currentValue, 'm2')
})
