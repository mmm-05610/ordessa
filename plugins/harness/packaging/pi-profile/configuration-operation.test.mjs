import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { configurationReader, configurationDigest, stableJSON, jsonDigest } from './configuration-query.mjs'

// The builder gives the sibling its deployed name; load identical source with
// just that module URL resolved for source-tree tests.
const source = await readFile(new URL('./configuration-operation.mjs', import.meta.url), 'utf8')
const moduleURL = 'data:text/javascript;base64,' + Buffer.from(source.replace(
  "'./ordessa-configuration-query.mjs'", JSON.stringify(new URL('./configuration-query.mjs', import.meta.url).href))).toString('base64')
const { configurationOperations, CONFIGURATION_APPLY, CONFIGURATION_OPERATION } = await import(moduleURL)

function fixture(options = {}) {
  const config = [
    { id: 'model', type: 'select', currentValue: 'p/m1', options: [{ value: 'p/m1' }, { value: 'p/m2' }] },
    { id: 'thinkingLevel', type: 'select', currentValue: 'off', options: [{ value: 'off' }, { value: 'high' }] },
  ]
  const session = { busy: false, configOptions: () => config }
  let calls = 0
  const agent = { live: new Map([['native', session]]), async setConfigOption(context) {
    calls++
    const { configId, value } = context.params
    if (options.execute) return options.execute({ context, config, session, agent })
    config.find(item => item.id === configId).currentValue = value
    return { configOptions: [{ id: configId, currentValue: 'forged-ack' }] }
  } }
  const read = configurationReader(agent, message => new Error(message))
  const operation = configurationOperations({ agent, read: options.read ?? read,
    invalidParams: message => new Error(message), ...options.capacity })
  const before = read({ sessionId: 'native' })
  const input = { sessionId: 'native', operationId: 'op1', expectedGeneration: before.generation,
    expectedConfigDigest: configurationDigest(before), configId: 'model', value: 'p/m2' }
  return { agent, session, config, read, operation, input, calls: () => calls }
}

function actionManifest(input) {
  return { target: { server_id: 'server-incarnation', session_id: 'canonical-uid',
    channel_id: 'channel', runtime_generation: 3 }, scope: 'session', actions: [{
    publicationOwner: 'ordessa.model-provider-adapters', publicationToken: 'publication-token',
    source: { facet_id: 'assets.model-provider', item_id: 'choice', contribution_version: '1' },
    actionId: 'acp.session.set-config-option', schemaVersion: '1',
    input: { configId: input.configId, value: input.value }, expectedObservation: 'independent-session-readback',
  }] }
}

test('bound native record retains exact C4 target and canonical manifest digest without conferring authority', async () => {
  const f = fixture()
  const manifest = actionManifest(f.input)
  const input = { ...f.input, actionManifest: manifest }
  const result = await f.operation.apply(input)
  assert.equal(result.state, 'observed')
  assert.deepEqual(result.target, manifest.target)
  assert.deepEqual(result.actionManifest, manifest)
  assert.equal(result.manifestDigest, jsonDigest(manifest))
  // Independently computed by the real Python ActionBatch.manifest_digest
  // using ApplicationTarget/IntentSource/InvokeAction for this exact fixture.
  assert.equal(result.manifestDigest, '7e3046428948f6eaaadf4692860227f528e5d10f991815c81df9cc912fbffebc')
  assert.equal(result.inputDigest, jsonDigest(input))
  assert.notEqual(result.inputDigest, jsonDigest(f.input))
  assert.equal(Object.hasOwn(result, 'permit'), false)
  assert.equal(Object.hasOwn(result, 'confirmed'), false)
  result.target.runtime_generation = 99
  manifest.target.runtime_generation = 100
  const queried = f.operation.query({ sessionId: 'native', operationId: 'op1' })
  assert.equal(queried.target.runtime_generation, 3)
  assert.equal(queried.actionManifest.target.runtime_generation, 3)
  assert.equal(f.calls(), 1)
})

test('unbound six-field operation remains a development record with no C4 target/digest', async () => {
  const f = fixture()
  const result = await f.operation.apply(f.input)
  assert.equal(Object.hasOwn(result, 'target'), false)
  assert.equal(Object.hasOwn(result, 'manifestDigest'), false)
  assert.equal(Object.hasOwn(result, 'actionManifest'), false)
})

test('operation ID cannot switch target, manifest source or binding mode on replay', async () => {
  const f = fixture()
  const input = { ...f.input, actionManifest: actionManifest(f.input) }
  const result = await f.operation.apply(input)
  assert.deepEqual(await f.operation.apply(structuredClone(input)), result)
  for (const mutate of [
    value => { value.actionManifest.target.session_id = 'another-canonical-uid' },
    value => { value.actionManifest.target.runtime_generation++ },
    value => { value.actionManifest.actions[0].publicationToken = 'new-publication' },
    value => { value.actionManifest.actions[0].source.item_id = 'another-item' },
    value => { delete value.actionManifest },
  ]) {
    const altered = structuredClone(input); mutate(altered)
    await assert.rejects(f.operation.apply(altered), /different input/)
  }
  assert.equal(f.calls(), 1)
})

for (const [name, mutate] of [
  ['null manifest', input => { input.actionManifest = null }],
  ['extra root field', input => { input.actionManifest.permit = 'forged' }],
  ['wrong scope', input => { input.actionManifest.scope = 'instance' }],
  ['extra target field', input => { input.actionManifest.target.nativeId = 'native' }],
  ['missing target field', input => { delete input.actionManifest.target.channel_id }],
  ['empty target identity', input => { input.actionManifest.target.server_id = '' }],
  ['negative generation', input => { input.actionManifest.target.runtime_generation = -1 }],
  ['boolean generation', input => { input.actionManifest.target.runtime_generation = true }],
  ['unsafe generation', input => { input.actionManifest.target.runtime_generation = Number.MAX_SAFE_INTEGER + 1 }],
  ['multiple actions', input => { input.actionManifest.actions.push(structuredClone(input.actionManifest.actions[0])) }],
  ['zero actions', input => { input.actionManifest.actions = [] }],
  ['unknown action', input => { input.actionManifest.actions[0].actionId = 'acp.session.restart' }],
  ['unknown schema', input => { input.actionManifest.actions[0].schemaVersion = '2' }],
  ['wrong model input', input => { input.actionManifest.actions[0].input.value = 'p/m1' }],
  ['wrong config input', input => { input.actionManifest.actions[0].input.configId = 'thinkingLevel' }],
  ['secret input', input => { input.actionManifest.actions[0].input.secret = 'forged' }],
  ['missing expected observation', input => { input.actionManifest.actions[0].expectedObservation = '' }],
  ['unknown source business field', input => { input.actionManifest.actions[0].source.business_ref = 'not-an-IntentSource-field' }],
  ['unknown source batch field', input => { input.actionManifest.actions[0].source.batch_item_ids = ['choice'] }],
  ['missing source identity', input => { delete input.actionManifest.actions[0].source.contribution_version }],
  ['oversized source', input => { input.actionManifest.actions[0].publicationToken = 'x'.repeat(4097) }],
]) test(`manifest refuses ${name} with zero effects/reservation`, async () => {
  const f = fixture()
  const input = { ...f.input, actionManifest: actionManifest(f.input) }; mutate(input)
  await assert.rejects(f.operation.apply(input))
  assert.equal(f.calls(), 0)
  assert.throws(() => f.operation.query({ sessionId: 'native', operationId: 'op1' }), /not known/)
})

test('bound unknown record retains target and manifest; no repeat effect', async () => {
  const f = fixture({ execute: ({ config }) => { config[0].currentValue = 'p/m2'; throw new Error('response lost') } })
  const input = { ...f.input, actionManifest: actionManifest(f.input) }
  const result = await f.operation.apply(input)
  assert.equal(result.state, 'unknown')
  assert.deepEqual(result.target, input.actionManifest.target)
  assert.equal(result.manifestDigest, jsonDigest(input.actionManifest))
  assert.equal(result.evidenceRef, null)
  assert.deepEqual(await f.operation.apply(input), result)
  assert.equal(f.calls(), 1)
})

test('canonical JSON/digest are stable and reject non-JSON input', () => {
  assert.equal(stableJSON({ z: 1, a: [{ c: true, b: null }] }), '{"a":[{"b":null,"c":true}],"z":1}')
  assert.equal(jsonDigest({ b: 2, a: 1 }), jsonDigest({ a: 1, b: 2 }))
  assert.notEqual(jsonDigest([1, 2]), jsonDigest([2, 1]))
  assert.match(jsonDigest({}), /^[0-9a-f]{64}$/)
  const cycle = {}; cycle.cycle = cycle
  for (const value of [undefined, NaN, Infinity, 1n, new Date(), cycle, [, 1]])
    assert.throws(() => stableJSON(value))
})

test('observed operation uses independent reads, not a forged ACK; replay is detached', async () => {
  const f = fixture()
  const result = await f.operation.apply(f.input)
  assert.equal(result.state, 'observed')
  assert.equal(result.observedValue, 'p/m2')
  assert.equal(result.inputDigest, jsonDigest(f.input))
  assert.equal(result.beforeConfigDigest, f.input.expectedConfigDigest)
  assert.equal(result.afterConfigDigest, configurationDigest(f.read({ sessionId: 'native' })))
  assert.equal(result.before.configOptions[0].currentValue, 'p/m1')
  assert.match(result.evidenceRef, /^pi-native-operation:/)
  assert.equal(Object.hasOwn(result, 'confirmed'), false)
  result.after.configOptions[0].currentValue = 'forged'
  f.session.busy = true
  const replay = await f.operation.apply(f.input)
  assert.equal(replay.after.configOptions[0].currentValue, 'p/m2')
  assert.equal(f.calls(), 1)
  replay.before.configOptions.length = 0
  assert.equal(f.operation.query({ sessionId: 'native', operationId: 'op1' }).before.configOptions.length, 2)
})

test('thinking only accepts the exact pinned live option spelling', async () => {
  const f = fixture()
  const result = await f.operation.apply({ ...f.input, configId: 'thinkingLevel', value: 'high' })
  assert.equal(result.observedValue, 'high')
  assert.equal(result.state, 'observed')
})

test('same operation id cannot change payload or native session', async () => {
  const f = fixture()
  await f.operation.apply(f.input)
  await assert.rejects(f.operation.apply({ ...f.input, value: 'p/m1' }), /different input/)
  await assert.rejects(f.operation.apply({ ...f.input, sessionId: 'other' }), /different input/)
  assert.throws(() => f.operation.query({ sessionId: 'other', operationId: 'op1' }), /not known/)
  assert.equal(f.calls(), 1)
})

for (const [name, change] of [
  ['generation', input => ({ ...input, expectedGeneration: 'stale' })],
  ['digest', input => ({ ...input, expectedConfigDigest: '0'.repeat(64) })],
  ['value not exposed', input => ({ ...input, value: 'p/missing' })],
  ['secret field', input => ({ ...input, credential: 'secret' })],
  ['unsupported provider config', input => ({ ...input, configId: 'provider' })],
  ['wrong thinking spelling', input => ({ ...input, configId: 'thought_level' })],
  ['empty id', input => ({ ...input, operationId: '' })],
  ['oversized id', input => ({ ...input, operationId: 'x'.repeat(129) })],
  ['oversized session', input => ({ ...input, sessionId: 'x'.repeat(4097) })],
  ['NUL value', input => ({ ...input, value: 'p/\0m' })],
  ['nonstring value', input => ({ ...input, value: { value: 'p/m1' } })],
]) test(`refuses ${name} before effects or reservation`, async () => {
  const f = fixture()
  await assert.rejects(f.operation.apply(change(f.input)))
  assert.equal(f.calls(), 0)
  assert.throws(() => f.operation.query({ sessionId: 'native', operationId: 'op1' }), /not known/)
})

test('busy and unknown/disposed/closing sessions refuse without interrupting output', async () => {
  for (const field of ['busy', 'disposed', 'closing']) {
    const f = fixture(); f.session[field] = true
    await assert.rejects(f.operation.apply(f.input))
    assert.equal(f.calls(), 0)
    assert.equal(f.session[field], true)
  }
  const f = fixture(); f.agent.live.clear()
  await assert.rejects(f.operation.apply(f.input), /not live/)
})

test('upstream throw after mutation records unknown, never retries', async () => {
  const f = fixture({ execute: ({ config }) => { config[0].currentValue = 'p/m2'; throw new Error('lost reply') } })
  const result = await f.operation.apply(f.input)
  assert.equal(result.state, 'unknown')
  assert.equal(result.phase, 'upstream-outcome-unknown')
  assert.equal(result.observedValue, 'p/m2')
  assert.equal(result.evidenceRef, null)
  assert.equal((await f.operation.apply(f.input)).state, 'unknown')
  assert.equal(f.calls(), 1)
})

test('ACK with no actual change records unknown', async () => {
  const f = fixture({ execute: () => ({ configOptions: [{ currentValue: 'p/m2' }] }) })
  const result = await f.operation.apply(f.input)
  assert.equal(result.state, 'unknown')
  assert.equal(result.observedValue, 'p/m1')
  assert.equal(result.evidenceRef, null)
  await f.operation.apply(f.input)
  assert.equal(f.calls(), 1)
})

test('replacement, close, busy or failed independent post-read never observe success', async () => {
  for (const mutate of [
    ({ agent, config }) => agent.live.set('native', { busy: false, configOptions: () => config }),
    ({ agent }) => agent.live.clear(),
    ({ session }) => { session.busy = true },
    ({ session }) => { session.configOptions = () => { throw new Error('read lost') } },
  ]) {
    const f = fixture({ execute: env => { env.config[0].currentValue = 'p/m2'; mutate(env) } })
    const result = await f.operation.apply(f.input)
    assert.equal(result.state, 'unknown')
    assert.equal(result.evidenceRef, null)
    assert.equal((await f.operation.apply(f.input)).state, 'unknown')
    assert.equal(f.calls(), 1)
  }
})

test('inflight duplicate returns retained unknown; competing same-session action fails immediately', async () => {
  let release
  const gate = new Promise(resolve => { release = resolve })
  const f = fixture({ execute: async ({ config }) => { await gate; config[0].currentValue = 'p/m2' } })
  const running = f.operation.apply(f.input)
  assert.equal((await f.operation.apply(f.input)).phase, 'executing')
  await assert.rejects(f.operation.apply({ ...f.input, operationId: 'op2' }), /busy/)
  assert.equal(f.calls(), 1)
  release()
  assert.equal((await running).state, 'observed')
})

test('shared nonwaiting session lock blocks prompt/config/apply, isolates sessions and releases after errors', async () => {
  const f = fixture()
  f.agent.live.set('other', { busy: false })
  let release
  const running = f.operation.withSession('native', () => new Promise(resolve => { release = resolve }))
  await assert.rejects(f.operation.withSession('native', () => { throw new Error('must not run') }), /busy/)
  await assert.rejects(f.operation.apply(f.input), /busy/)
  assert.equal(await f.operation.withSession('other', () => 'independent'), 'independent')
  release(); await running
  await assert.rejects(f.operation.withSession('native', () => { throw new Error('failed') }), /failed/)
  assert.equal((await f.operation.apply(f.input)).state, 'observed')
})

test('record/lock capacity refuses without eviction or native effects; replay/query remain usable', async () => {
  const f = fixture({ capacity: { maxOperations: 1, maxLocks: 1 } })
  await f.operation.apply(f.input)
  const now = f.read({ sessionId: 'native' })
  await assert.rejects(f.operation.apply({ ...f.input, operationId: 'op2', value: 'p/m1',
    expectedConfigDigest: configurationDigest(now) }), /capacity/)
  assert.equal(f.calls(), 1)
  assert.equal((await f.operation.apply(f.input)).state, 'observed')
  assert.equal(f.operation.query({ sessionId: 'native', operationId: 'op1' }).state, 'observed')
  let release
  const held = f.operation.withSession('native', () => new Promise(resolve => { release = resolve }))
  f.agent.live.set('other', { busy: false })
  await assert.rejects(f.operation.withSession('other', () => 'no'), /capacity/)
  release(); await held
})

test('oversized native readback and duplicate options refuse before effects', async () => {
  const f = fixture()
  f.config.push({ id: 'oversized', currentValue: 'x'.repeat(65536) })
  await assert.rejects(f.operation.apply(f.input), /capacity/)
  assert.equal(f.calls(), 0)
  const g = fixture(); g.config.push(structuredClone(g.config[0]))
  g.input.expectedConfigDigest = configurationDigest(g.read({ sessionId: 'native' }))
  await assert.rejects(g.operation.apply(g.input), /not exposed/)
  assert.equal(g.calls(), 0)
})

test('query is exact and bounded, rejects arbitrary methods/extra data', () => {
  const f = fixture()
  for (const query of [{}, { sessionId: 'native', operationId: 'x', value: 'p/m1' },
    { sessionId: 'native', operationId: 'x'.repeat(129) }])
    assert.throws(() => f.operation.query(query))
  assert.equal(f.calls(), 0)
  assert.equal(CONFIGURATION_APPLY, '_ordessa/session/configuration/apply')
  assert.equal(CONFIGURATION_OPERATION, '_ordessa/session/configuration/operation')
})

test('actual server registration wraps prompt/setConfigOption/apply with one session lock', async () => {
  const f = fixture()
  const handlers = new Map()
  let release
  let promptCalls = 0
  const promptGate = new Promise(resolve => { release = resolve })
  f.agent.prompt = async () => { promptCalls++; await promptGate; return { stopReason: 'end_turn' } }
  const shared = { agent: f.agent, handlers }
  const key = '__ordessaPiOperationRegistrationTest'
  globalThis[key] = shared
  const data = source => 'data:text/javascript;base64,' + Buffer.from(source).toString('base64')
  const sdk = data(`
    export const RequestError = { invalidParams: (_unused, message) => new Error(message) };
    export const ndJsonStream = () => ({});
    export const methods = {agent: {initialize:'initialize',authenticate:'authenticate',session:{
      new:'new',load:'load',resume:'resume',fork:'fork',list:'list',close:'close',
      setConfigOption:'session/set_config_option',prompt:'session/prompt',cancel:'cancel'}}};
    export function agent() { return {
      onRequest(name, parser, handler) {
        if (name.startsWith('_ordessa/') && typeof parser?.parse !== 'function') throw new Error('Custom method requires parser');
        globalThis.${key}.handlers.set(name, handler ?? parser); return this
      },
      onNotification() { return this }, connect() { return {} }
    } }
  `)
  const agent = data(`export class PiAcpAgent { constructor() { return globalThis.${key}.agent } }`)
  const deps = data('export const resolveDeps = async () => ({})')
  const steering = data("export const SESSION_STEERING_METHOD = 'steer'; export const steeringRequestParser = {}")
  const loaded = data("export const LOADED_TURN_QUERY_METHOD = 'loaded'; export const loadedTurnQueryParser = {}")
  const creation = data((await readFile(new URL('./creation.mjs', import.meta.url), 'utf8'))
    .replace("'./ordessa-configuration-query.mjs'", JSON.stringify(new URL('./configuration-query.mjs', import.meta.url).href)))
  let server = await readFile(new URL('./server.mjs', import.meta.url), 'utf8')
  for (const [from, to] of [
    ['@agentclientprotocol/sdk', sdk], ['./agent.js', agent], ['./deps.js', deps],
    ['./steering.js', steering], ['./loaded-turn.js', loaded],
    ['./ordessa-configuration-query.mjs', new URL('./configuration-query.mjs', import.meta.url).href],
    ['./ordessa-configuration-operation.mjs', moduleURL],
    ['./ordessa-creation.mjs', creation],
  ]) server = server.replace(`'${from}'`, JSON.stringify(to))
  try {
    const { runAcp } = await import(data(server))
    await runAcp({ stream: {} })
    const read = handlers.get('_ordessa/session/configuration')
    const observed = read({ params: { sessionId: 'native' } })
    const params = { ...f.input, expectedGeneration: observed.generation,
      expectedConfigDigest: configurationDigest(observed) }
    const prompt = handlers.get('session/prompt')({ params: { sessionId: 'native' } })
    assert.equal(read({ params: { sessionId: 'native' } }).busy, true)
    await assert.rejects(handlers.get('session/set_config_option')({ params: {
      sessionId: 'native', configId: 'model', value: 'p/m2' } }), /busy/)
    await assert.rejects(handlers.get(CONFIGURATION_APPLY)({ params }), /busy/)
    assert.equal(f.calls(), 0)
    assert.equal(promptCalls, 1)
    release(); await prompt
    assert.equal(read({ params: { sessionId: 'native' } }).busy, false)
    assert.equal((await handlers.get(CONFIGURATION_APPLY)({ params })).state, 'observed')
    assert.equal(handlers.get(CONFIGURATION_OPERATION)({ params: { sessionId: 'native', operationId: 'op1' } }).state, 'observed')
    assert.equal(f.calls(), 1)
    f.session.busy = true
    await assert.rejects(handlers.get('session/prompt')({ params: { sessionId: 'native' } }), /busy/)
    await assert.rejects(handlers.get('session/set_config_option')({ params: {
      sessionId: 'native', configId: 'model', value: 'p/m1' } }), /busy/)
    assert.equal(promptCalls, 1)
    assert.equal(f.calls(), 1)
  } finally { release(); delete globalThis[key] }
})
